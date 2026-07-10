import asyncio

from fastapi.responses import JSONResponse

from app.models.summarization import SummarizationRequest
from app.routes.summarization import summarize_transcript


def test_summarize_transcript_not_found_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.summarization._get_summarize_by_video_id",
        lambda: lambda _: None,
    )

    response = asyncio.run(
        summarize_transcript(SummarizationRequest(video_id="video-1"))
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert b'"code":"TRANSCRIPT_NOT_FOUND"' in response.body


def test_summarize_transcript_error_envelope(monkeypatch) -> None:
    def _raise_error(_: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.routes.summarization._get_summarize_by_video_id",
        lambda: _raise_error,
    )

    response = asyncio.run(
        summarize_transcript(SummarizationRequest(video_id="video-1"))
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"SUMMARIZATION_FAILED","message":"Internal server error during summarization"}}'


def test_summarize_transcript_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.summarization._get_summarize_by_video_id",
        lambda: lambda _: "summary",
    )

    response = asyncio.run(
        summarize_transcript(SummarizationRequest(video_id="video-1"))
    )

    assert response.summary == "summary"
