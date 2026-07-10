from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi.responses import JSONResponse


def _safe_check(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:
        return False


def build_default_health_checks(
    *,
    model_cache: Mapping[str, Any],
    search_service: Any,
    llm_service: Any,
) -> dict[str, bool]:
    return {
        "transcription_model_loaded": _safe_check(lambda: bool(model_cache)),
        "search_collection_ready": _safe_check(
            lambda: search_service._collection is not None
        ),
        "llm_configured": _safe_check(
            lambda: llm_service.get_active_model_id() is not None
        ),
    }


def build_health_response(checks: dict[str, bool]):
    is_healthy = all(checks.values())
    payload = {"status": "ok" if is_healthy else "degraded", "checks": checks}

    if is_healthy:
        return payload

    return JSONResponse(status_code=503, content=payload)
