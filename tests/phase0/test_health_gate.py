from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest


def test_live_backend_reports_database_and_redis_healthy() -> None:
    url = os.environ.get("PHASE0_HEALTH_URL", "http://localhost:8000/api/health")
    try:
        with urlopen(url, timeout=2) as response:  # noqa: S310 - local gate endpoint
            status_code = response.status
            body = json.load(response)
    except HTTPError as exc:
        pytest.fail(f"health endpoint returned HTTP {exc.code}: {exc.read().decode()}")
    except (TimeoutError, URLError) as exc:
        pytest.skip(f"Phase 0 stack is not running at {url}: {exc}")

    assert status_code == 200
    assert body == {"status": "ok", "db": "ok", "redis": "ok"}
