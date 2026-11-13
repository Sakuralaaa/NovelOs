"""API 密钥：给脚本、命令行和外部 AI 助手用的长期凭证。

- 格式 `nvk_<8位id>_<随机串>`，只在创建时返回一次；服务端只存 SHA-256 摘要（data/api_keys.json，权限 600）。
- 请求头任选其一：`Authorization: Bearer nvk_...` 或 `X-API-Key: nvk_...`。
- 环境变量 NOVELOS_API_KEY 可再指定一个固定密钥（适合 compose 部署时预先写好）。
- 修改登录密码不会让 API 密钥失效；要收回请在“设置 → API 密钥”里删除。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

PREFIX = "nvk_"
MAX_KEYS = 20


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ApiKeyStore:
    def __init__(self, data_dir: Path, env_key: str | None = None) -> None:
        self.path = data_dir / "api_keys.json"
        self._lock = threading.Lock()
        self._env_digest = _digest(env_key) if env_key else None
        self._keys: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return [k for k in data.get("keys", []) if isinstance(k, dict) and k.get("id") and k.get("hash")]
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"keys": self._keys}, ensure_ascii=False), "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    @staticmethod
    def _public(k: dict) -> dict:
        return {
            "id": k["id"], "name": k.get("name", ""), "preview": f"{PREFIX}{k['id']}_…{k.get('tail', '')}",
            "created_at": k.get("created_at"), "last_used_at": k.get("last_used_at"),
        }

    def list(self) -> list[dict]:
        with self._lock:
            return [self._public(k) for k in self._keys]

    @property
    def env_key_enabled(self) -> bool:
        return self._env_digest is not None

    def create(self, name: str) -> tuple[dict, str]:
        name = (name or "").strip()[:40] or "未命名"
        with self._lock:
            if len(self._keys) >= MAX_KEYS:
                raise ValueError(f"最多 {MAX_KEYS} 个密钥，请先删除不用的")
            kid = secrets.token_hex(4)
            token = f"{PREFIX}{kid}_{secrets.token_urlsafe(32)}"
            k = {"id": kid, "name": name, "hash": _digest(token), "tail": token[-4:],
                 "created_at": int(time.time()), "last_used_at": None}
            self._keys.append(k)
            self._save()
            return self._public(k), token

    def revoke(self, kid: str) -> bool:
        with self._lock:
            before = len(self._keys)
            self._keys = [k for k in self._keys if k["id"] != kid]
            if len(self._keys) == before:
                return False
            self._save()
            return True

    def check(self, token: str | None) -> bool:
        if not token or not token.startswith(PREFIX) or len(token) > 200:
            return False
        d = _digest(token)
        if self._env_digest and hmac.compare_digest(d, self._env_digest):
            return True
        kid = token[len(PREFIX):].split("_", 1)[0]
        with self._lock:
            for k in self._keys:
                if k["id"] == kid and hmac.compare_digest(d, k["hash"]):
                    now = int(time.time())
                    # 最近使用时间每 5 分钟落盘一次，避免每个请求写文件
                    if not k.get("last_used_at") or now - k["last_used_at"] > 300:
                        k["last_used_at"] = now
                        self._save()
                    return True
        return False


def token_from_headers(headers) -> str | None:
    x = headers.get("x-api-key")
    if x:
        return x.strip()
    scheme, _, value = headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip().startswith(PREFIX):
        return value.strip()
    return None
