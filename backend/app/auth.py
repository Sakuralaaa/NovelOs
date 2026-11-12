"""登录鉴权：单用户密码 + 签名会话 Cookie。

设计要点
- 密码只保存 PBKDF2-SHA256 加盐哈希（data/auth.json），不落明文。
- 优先级：环境变量 NOVELOS_PASSWORD（兼容旧的 NOVELOS_BASIC_PASSWORD）> data/auth.json > 首次启动自动生成。
  自动生成的初始密码会打印到日志，并写入 data/initial_password.txt（权限 600），登录后请在“设置 → 账户安全”里修改。
- 会话是 HMAC 签名的无状态令牌，放在 HttpOnly + SameSite=Lax 的 Cookie 里；令牌里带密码指纹，改密码后旧会话全部失效。
- 登录失败按 IP 限流：15 分钟内失败 5 次锁定 15 分钟；每次失败额外延迟，抵御暴力破解。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("novelos.auth")

COOKIE_NAME = "novelos_session"
PBKDF2_ITERATIONS = 390_000
SESSION_SHORT_S = 12 * 3600  # 不勾选“记住我”
SESSION_LONG_S = 30 * 24 * 3600  # 勾选“记住我”
MIN_PASSWORD_LEN = 8

FAIL_WINDOW_S = 15 * 60
FAIL_MAX = 5
LOCK_S = 15 * 60


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt, digest = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64d(salt), int(iters))
        return hmac.compare_digest(dk, _b64d(digest))
    except (ValueError, TypeError):
        return False


@dataclass
class LoginBlocked(Exception):
    retry_after: int


class AuthManager:
    def __init__(self, data_dir: Path, env_password: str | None, username: str = "novelos") -> None:
        self.path = data_dir / "auth.json"
        self.initial_path = data_dir / "initial_password.txt"
        self.username = username
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        data = self._load()
        self.session_key: bytes = _b64d(data["session_key"]) if data.get("session_key") else secrets.token_bytes(32)
        self.managed_by_env = bool(env_password)
        if env_password:
            # 环境变量为准；哈希只放内存（同一明文每次启动盐不同，不影响会话：指纹基于明文 HMAC）
            self.password_hash = hash_password(env_password)
            self._fingerprint_src = env_password.encode()
            self.initial_password: str | None = None
        elif data.get("password_hash"):
            self.password_hash = data["password_hash"]
            self._fingerprint_src = self.password_hash.encode()
            self.initial_password = None
        else:
            pw = secrets.token_urlsafe(12)
            self.password_hash = hash_password(pw)
            self._fingerprint_src = self.password_hash.encode()
            self.initial_password = pw
            self._write_initial(pw)
            log.warning("=" * 60)
            log.warning("NovelOS 已生成初始登录密码：%s", pw)
            log.warning("也保存在 %s ，登录后请到“设置 → 账户安全”修改。", self.initial_path)
            log.warning("=" * 60)
        self._save()

    # ---------- 持久化 ----------
    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        data = {"session_key": _b64e(self.session_key)}
        if not self.managed_by_env:
            data["password_hash"] = self.password_hash
        else:
            old = self._load().get("password_hash")
            if old:
                data["password_hash"] = old
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def _write_initial(self, pw: str) -> None:
        try:
            self.initial_path.write_text(
                f"NovelOS 初始登录密码：{pw}\n登录后请在“设置 → 账户安全”中修改，修改后本文件会自动删除。\n", "utf-8"
            )
            os.chmod(self.initial_path, 0o600)
        except OSError:
            pass

    # ---------- 会话 ----------
    def _fingerprint(self) -> str:
        return hmac.new(self.session_key, self._fingerprint_src, hashlib.sha256).hexdigest()[:16]

    def issue(self, remember: bool) -> tuple[str, int]:
        ttl = SESSION_LONG_S if remember else SESSION_SHORT_S
        payload = {"u": self.username, "exp": int(time.time()) + ttl, "v": self._fingerprint(), "n": secrets.token_hex(4)}
        body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
        sig = _b64e(hmac.new(self.session_key, body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}", ttl

    def check(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        body, _, sig = token.partition(".")
        expect = _b64e(hmac.new(self.session_key, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return False
        try:
            payload = json.loads(_b64d(body))
        except ValueError:
            return False
        return payload.get("exp", 0) > time.time() and payload.get("v") == self._fingerprint()

    # ---------- 登录 / 改密 ----------
    def attempt(self, ip: str, password: str) -> bool:
        now = time.time()
        with self._lock:
            until = self._locked_until.get(ip, 0)
            if until > now:
                raise LoginBlocked(int(until - now) + 1)
        ok = verify_password(password, self.password_hash)
        with self._lock:
            if ok:
                self._fails.pop(ip, None)
                self._locked_until.pop(ip, None)
                return True
            fails = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW_S] + [now]
            self._fails[ip] = fails
            if len(fails) >= FAIL_MAX:
                self._locked_until[ip] = now + LOCK_S
                self._fails.pop(ip, None)
                log.warning("登录失败次数过多，已锁定 IP %s %s 秒", ip, LOCK_S)
        return False

    def verify_cached(self, password: str) -> bool:
        """供 Basic 认证使用：结果按（密码摘要, 当前指纹）缓存，避免每个请求都跑 PBKDF2。"""
        key = hmac.new(self.session_key, password.encode(), hashlib.sha256).hexdigest() + self._fingerprint()
        cache = self.__dict__.setdefault("_verified", set())
        if key in cache:
            return True
        if verify_password(password, self.password_hash):
            if len(cache) > 64:
                cache.clear()
            cache.add(key)
            return True
        return False

    def remaining_attempts(self, ip: str) -> int:
        now = time.time()
        with self._lock:
            return max(0, FAIL_MAX - len([t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW_S]))

    def change_password(self, current: str, new: str) -> None:
        if self.managed_by_env:
            raise ValueError("密码由环境变量 NOVELOS_PASSWORD 管理，请修改 .env 后重启服务")
        if not verify_password(current, self.password_hash):
            raise PermissionError("当前密码不正确")
        if len(new) < MIN_PASSWORD_LEN:
            raise ValueError(f"新密码至少 {MIN_PASSWORD_LEN} 位")
        if new == current:
            raise ValueError("新密码不能与当前密码相同")
        self.password_hash = hash_password(new)
        self._fingerprint_src = self.password_hash.encode()
        self._save()
        try:
            self.initial_path.unlink()
        except OSError:
            pass
