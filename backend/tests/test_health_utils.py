import json
from typing import Any

from fastapi.responses import JSONResponse

from app.utils.health import build_default_health_checks, build_health_response


class _DummySearchService:
    def __init__(self, collection: Any) -> None:
        self._collection = collection


class _DummyLlmService:
    def __init__(self, model_id: str | None) -> None:
        self._model_id = model_id

    def get_active_model_id(self) -> str | None:
        return self._model_id


class _FailingSearchService:
    @property
    def _collection(self):
        raise RuntimeError("search service unavailable")


class _FailingLlmService:
    def get_active_model_id(self) -> str | None:
        raise RuntimeError("llm service unavailable")


def test_build_health_response_returns_ok_payload_when_healthy() -> None:
    checks = {
        "transcription_model_loaded": True,
        "search_collection_ready": True,
        "llm_configured": True,
    }

    response = build_health_response(checks)

    assert isinstance(response, dict)
    assert response == {
        "status": "ok",
        "checks": checks,
    }


def test_build_health_response_returns_503_when_degraded() -> None:
    checks = {
        "transcription_model_loaded": False,
        "search_collection_ready": True,
        "llm_configured": False,
    }

    response = build_health_response(checks)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "degraded",
        "checks": checks,
    }


def test_build_default_health_checks_all_true() -> None:
    checks = build_default_health_checks(
        model_cache={"small": object()},
        search_service=_DummySearchService(collection=object()),
        llm_service=_DummyLlmService(model_id="qwen3:8b"),
    )

    assert checks == {
        "transcription_model_loaded": True,
        "search_collection_ready": True,
        "llm_configured": True,
    }


def test_build_default_health_checks_handles_check_exceptions() -> None:
    checks = build_default_health_checks(
        model_cache={},
        search_service=_FailingSearchService(),
        llm_service=_FailingLlmService(),
    )

    assert checks == {
        "transcription_model_loaded": False,
        "search_collection_ready": False,
        "llm_configured": False,
    }
