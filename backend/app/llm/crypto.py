"""API Key 加密：Fernet。主密钥来自 NOVELOS_SECRET，否则自动生成并保存在数据目录。"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.secret:
        key = base64.urlsafe_b64encode(hashlib.sha256(s.secret.encode("utf-8")).digest())
        return Fernet(key)
    path = s.data_dir / "secret.key"
    if path.exists():
        return Fernet(path.read_bytes().strip())
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        pass
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii") if plain else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("API Key 解密失败：NOVELOS_SECRET 可能已变更，请重新填写该渠道的 Key") from e


def mask(plain: str) -> str:
    if not plain:
        return ""
    if len(plain) <= 8:
        return plain[:2] + "****"
    return f"{plain[:3]}****{plain[-4:]}"


def reset_cache() -> None:
    _fernet.cache_clear()
