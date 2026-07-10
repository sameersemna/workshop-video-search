from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.utils.health import build_default_health_checks, build_health_response


class _SearchService:
    def __init__(self, collection):
        self._collection = collection


class _LlmService:
    def __init__(self, model_id):
        self._model_id = model_id

    def get_active_model_id(self):
        return self._model_id


class _FailingSearchService:
    @property
    def _collection(self):
        raise RuntimeError("search unavailable")


class _FailingLlmService:
    def get_active_model_id(self):
        raise RuntimeError("llm unavailable")


def _build_health_app(model_cache, search_service, llm_service) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        checks = build_default_health_checks(
            model_cache=model_cache,
            search_service=search_service,
            llm_service=llm_service,
        )
        return build_health_response(checks)

    return app


def test_health_http_returns_ok_when_all_checks_pass() -> None:
    app = _build_health_app(
        model_cache={"small": object()},
        search_service=_SearchService(collection=object()),
        llm_service=_LlmService(model_id="qwen3:8b"),
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "transcription_model_loaded": True,
            "search_collection_ready": True,
            "llm_configured": True,
        },
    }


def test_health_http_returns_503_when_any_check_fails() -> None:
    app = _build_health_app(
        model_cache={},
        search_service=_SearchService(collection=None),
        llm_service=_LlmService(model_id=None),
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "transcription_model_loaded": False,
            "search_collection_ready": False,
            "llm_configured": False,
        },
    }


def test_health_http_handles_check_exceptions_as_false() -> None:
    app = _build_health_app(
        model_cache={},
        search_service=_FailingSearchService(),
        llm_service=_FailingLlmService(),
    )
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "transcription_model_loaded": False,
            "search_collection_ready": False,
            "llm_configured": False,
        },
    }
