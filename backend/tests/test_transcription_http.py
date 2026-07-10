from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.transcription import transcription_router
from app.utils.exception_handlers import register_exception_handlers


class _NoopSearchService:
    def index_transcript(self, transcript):
        return None

    def index_visual_embeddings(self, transcript_id, frame_data):
        return None


class _NoopVisualProcessingService:
    def extract_frames_for_segments(self, video_path, segments, interval):
        return {}

    def generate_frame_embeddings(self, frame_paths):
        return []


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(transcription_router, prefix="/transcribe")
    return app


def test_transcription_http_invalid_file_type_envelope() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.post(
        "/transcribe/video-file",
        files={"video_file": ("notes.txt", b"hello", "text/plain")},
        data={"model": "small"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_FILE_TYPE"


def test_transcription_http_processing_failure_envelope(monkeypatch) -> None:
    def _raise_processing_error(*args, **kwargs):
        raise RuntimeError("processing failed")

    monkeypatch.setattr(
        "app.routes.transcription._get_process_video_from_file",
        lambda: _raise_processing_error,
    )
    monkeypatch.setattr(
        "app.routes.transcription._get_search_service",
        lambda: _NoopSearchService(),
    )
    monkeypatch.setattr(
        "app.routes.transcription._get_visual_processing_service",
        lambda: _NoopVisualProcessingService(),
    )

    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.post(
        "/transcribe/video-file",
        files={"video_file": ("clip.mp4", b"fake-video-content", "video/mp4")},
        data={"model": "small"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "TRANSCRIPTION_FAILED",
            "message": "Internal Server Error",
        }
    }
