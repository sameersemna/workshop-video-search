from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.library import library_router, video_library_service
from app.utils.exception_handlers import register_exception_handlers


class _FailingSearchService:
    def get_transcript_segments_by_video_id(self, video_id: str):
        raise RuntimeError("search backend unavailable")


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(library_router, prefix="/library")
    return app


def test_library_http_transcript_fetch_failure_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        video_library_service,
        "get_video",
        lambda video_id: SimpleNamespace(title="Demo Video"),
    )
    monkeypatch.setattr(
        "app.routes.library._get_search_service",
        lambda: _FailingSearchService(),
    )

    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.get("/library/videos/video-1/transcript")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "TRANSCRIPT_FETCH_FAILED",
            "message": "Failed to fetch transcript",
        }
    }


def test_library_http_add_youtube_failure_envelope(monkeypatch) -> None:
    def _raise_error(url: str, model: str):
        raise RuntimeError("ingestion failed")

    monkeypatch.setattr(video_library_service, "add_youtube_video", _raise_error)

    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/library/videos/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "model": "base",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "YOUTUBE_VIDEO_ADD_FAILED",
            "message": "Failed to add video",
        }
    }
