from pydantic import ValidationError

from app.models.video import AddYouTubeVideoRequest


def test_add_youtube_video_request_rejects_non_youtube_url() -> None:
    try:
        AddYouTubeVideoRequest(url="https://example.com/watch?v=123", model="base")
        assert False, "Expected ValidationError for non-YouTube host"
    except ValidationError:
        assert True


def test_add_youtube_video_request_accepts_youtube_url() -> None:
    payload = AddYouTubeVideoRequest(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        model="base",
    )
    assert payload.model == "base"


def test_add_youtube_video_request_rejects_unknown_model() -> None:
    try:
        AddYouTubeVideoRequest(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            model="ultra",
        )
        assert False, "Expected ValidationError for unsupported whisper model"
    except ValidationError:
        assert True
