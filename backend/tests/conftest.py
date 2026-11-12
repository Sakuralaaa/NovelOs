from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterator
from typing import Any

import pytest

_TMP = tempfile.mkdtemp(prefix="novelos-test-")
os.environ["NOVELOS_DATA_DIR"] = _TMP
os.environ["NOVELOS_DISABLE_SCHEDULER"] = "1"
os.environ["NOVELOS_AUTH_DISABLED"] = "1"
os.environ["NOVELOS_STATIC_DIR"] = os.path.join(_TMP, "no-static")
os.environ.pop("NOVELOS_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def wait_job(client: TestClient, job: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    assert job["status"] in ("queued", "running", "succeeded", "failed"), job
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("succeeded", "failed"):
            assert j["status"] == "succeeded", j
            return j
        time.sleep(0.05)
    raise AssertionError(f"任务超时：{job}")
