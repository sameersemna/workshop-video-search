import asyncio
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from app.models.video import AddYouTubeVideoRequest
from app.routes.library import add_youtube_video, get_video_transcript, video_library_service


class _FailingSearchService:
    def get_transcript_segments_by_video_id(self, video_id: str):
        raise RuntimeError("search backend unavailable")


def test_get_video_transcript_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        video_library_service,
        "get_video",
        lambda video_id: SimpleNamespace(title="Demo Video"),
    )
    monkeypatch.setattr(
        "app.routes.library._get_search_service",
        lambda: _FailingSearchService(),
    )

    response = asyncio.run(get_video_transcript("video-1"))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"TRANSCRIPT_FETCH_FAILED","message":"Failed to fetch transcript"}}'


def test_add_youtube_video_error_envelope(monkeypatch) -> None:
    def _raise_error(url: str, model: str):
        raise RuntimeError("ingestion failed")

    monkeypatch.setattr(video_library_service, "add_youtube_video", _raise_error)

    request = AddYouTubeVideoRequest(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        model="base",
    )

    response = asyncio.run(add_youtube_video(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"YOUTUBE_VIDEO_ADD_FAILED","message":"Failed to add video"}}'
