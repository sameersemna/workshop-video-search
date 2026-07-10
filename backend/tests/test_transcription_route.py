import asyncio
from io import BytesIO

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.routes.transcription import transcribe_video_file


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


def test_transcribe_video_file_invalid_type_envelope() -> None:
    upload = UploadFile(
        filename="notes.txt",
        file=BytesIO(b"plain text"),
        headers={"content-type": "text/plain"},
    )

    response = asyncio.run(
        transcribe_video_file(
            video_file=upload,
            model="small",
            language=None,
            background_tasks=BackgroundTasks(),
        )
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    assert b'"code":"INVALID_FILE_TYPE"' in response.body


def test_transcribe_video_file_processing_error_envelope(monkeypatch) -> None:
    upload = UploadFile(
        filename="clip.mp4",
        file=BytesIO(b"fake-video-content"),
        headers={"content-type": "video/mp4"},
    )

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

    response = asyncio.run(
        transcribe_video_file(
            video_file=upload,
            model="small",
            language=None,
            background_tasks=BackgroundTasks(),
        )
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"TRANSCRIPTION_FAILED","message":"Internal Server Error"}}'
