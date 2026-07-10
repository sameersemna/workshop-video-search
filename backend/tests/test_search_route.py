import asyncio
import json

import pytest
from fastapi.responses import JSONResponse

from app.models.search import KeywordSearchResponse, QuestionRequest, SearchType
from app.routes.search import query_transcript


class _FakeSearchService:
    def __init__(self, fn):
        self.query_transcript = fn


def test_query_transcript_success_normalizes_input(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_query_transcript(**kwargs):
        captured.update(kwargs)
        return KeywordSearchResponse(
            question=kwargs["question"],
            video_ids=kwargs["video_ids"],
            results=[],
            search_type=SearchType.KEYWORD,
        )

    monkeypatch.setattr(
        "app.routes.search._get_search_service",
        lambda: _FakeSearchService(fake_query_transcript),
    )

    request = QuestionRequest(
        question="  find this segment  ",
        video_ids=["video-1", " video-1 ", "", "video-2"],
        top_k=3,
        search_type=SearchType.KEYWORD,
    )

    response = asyncio.run(query_transcript(request))

    assert isinstance(response, KeywordSearchResponse)
    assert response.question == "find this segment"
    assert response.video_ids == ["video-1", "video-2"]
    assert captured["question"] == "find this segment"
    assert captured["video_ids"] == ["video-1", "video-2"]
    assert captured["top_k"] == 3


def test_query_transcript_rejects_empty_question() -> None:
    request = QuestionRequest(
        question="   ",
        video_ids=None,
        top_k=5,
        search_type=SearchType.KEYWORD,
    )

    response = asyncio.run(query_transcript(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert payload["error"]["message"] == "question must not be empty"


def test_query_transcript_rejects_top_k_above_limit() -> None:
    request = QuestionRequest(
        question="valid",
        video_ids=None,
        top_k=999,
        search_type=SearchType.KEYWORD,
    )

    response = asyncio.run(query_transcript(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert "top_k must be less than or equal to" in payload["error"]["message"]


def test_query_transcript_maps_service_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query_transcript(**kwargs):
        raise ValueError("invalid search type")

    monkeypatch.setattr(
        "app.routes.search._get_search_service",
        lambda: _FakeSearchService(fake_query_transcript),
    )

    request = QuestionRequest(
        question="valid question",
        video_ids=["video-1"],
        top_k=5,
        search_type=SearchType.KEYWORD,
    )

    response = asyncio.run(query_transcript(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert payload["error"]["message"] == "invalid search type"


def test_query_transcript_maps_unhandled_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query_transcript(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.routes.search._get_search_service",
        lambda: _FakeSearchService(fake_query_transcript),
    )

    request = QuestionRequest(
        question="valid question",
        video_ids=["video-1"],
        top_k=5,
        search_type=SearchType.KEYWORD,
    )

    response = asyncio.run(query_transcript(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "SEARCH_QUERY_FAILED"
    assert payload["error"]["message"] == "Failed to execute search query"
