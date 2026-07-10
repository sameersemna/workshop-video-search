from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.search import KeywordSearchResponse, SearchType
from app.routes.search import search_router
from app.utils.exception_handlers import register_exception_handlers


class _FakeSearchService:
    def __init__(self, behavior: str = "success"):
        self.behavior = behavior

    def query_transcript(self, **kwargs):
        if self.behavior == "value_error":
            raise ValueError("invalid search type")
        if self.behavior == "runtime_error":
            raise RuntimeError("backend failure")

        return KeywordSearchResponse(
            question=kwargs["question"],
            video_ids=kwargs["video_ids"],
            results=[],
            search_type=SearchType.KEYWORD,
        )


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(search_router, prefix="/search")
    return app


def test_search_http_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.search._get_search_service",
        lambda: _FakeSearchService("success"),
    )

    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/search/query",
        json={
            "question": "  what happened  ",
            "videoIds": ["video-1", " video-1 ", "video-2"],
            "topK": 2,
            "searchType": "keyword",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "what happened"
    assert body["videoIds"] == ["video-1", "video-2"]
    assert body["searchType"] == "keyword"
    assert body["results"] == []


def test_search_http_validation_envelope_for_invalid_body() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/search/query",
        json={
            "question": "valid",
            "videoIds": ["video-1"],
            "topK": "not-an-int",
            "searchType": "keyword",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["error"]["details"], list)


def test_search_http_invalid_query_envelope() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/search/query",
        json={
            "question": "   ",
            "videoIds": ["video-1"],
            "topK": 3,
            "searchType": "keyword",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body == {
        "error": {
            "code": "INVALID_QUERY",
            "message": "question must not be empty",
        }
    }


def test_search_http_runtime_failure_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.search._get_search_service",
        lambda: _FakeSearchService("runtime_error"),
    )

    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/search/query",
        json={
            "question": "valid question",
            "videoIds": ["video-1"],
            "topK": 3,
            "searchType": "keyword",
        },
    )

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "error": {
            "code": "SEARCH_QUERY_FAILED",
            "message": "Failed to execute search query",
        }
    }
