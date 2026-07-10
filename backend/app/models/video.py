from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import HttpUrl, field_validator

from app.models.camel_case import CamelCaseModel


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoSource(str, Enum):
    YOUTUBE = "youtube"
    UPLOADED = "uploaded"


class VideoMetadata(CamelCaseModel):
    id: str
    title: str
    source: VideoSource
    file_path: str  # Path to stored video file
    youtube_url: Optional[str] = None  # Original YouTube URL if source is YOUTUBE
    duration: Optional[float] = None  # Duration in seconds
    thumbnail_path: Optional[str] = None
    whisper_model: str = "base"  # Whisper model for transcription
    status: ProcessingStatus = ProcessingStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class VideoLibraryResponse(CamelCaseModel):
    videos: list[VideoMetadata]
    processing_count: int
    total_count: int


class AddYouTubeVideoRequest(CamelCaseModel):
    url: HttpUrl
    model: str = "base"
    language: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, value: HttpUrl) -> HttpUrl:
        allowed_hosts = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
        }
        if value.host not in allowed_hosts:
            raise ValueError("Only YouTube URLs are supported")
        return value

    @field_validator("model")
    @classmethod
    def validate_whisper_model(cls, value: str) -> str:
        allowed_models = {"tiny", "base", "small", "medium", "large", "turbo"}
        if value not in allowed_models:
            raise ValueError(
                f"Unsupported whisper model '{value}'. Allowed: {sorted(allowed_models)}"
            )
        return value


class AddVideoResponse(CamelCaseModel):
    video_id: str
    title: str
    status: ProcessingStatus


class AddVideosResponse(CamelCaseModel):
    added: list[AddVideoResponse]
    errors: list[dict]


class ProcessingStatusResponse(CamelCaseModel):
    queue_length: int
    processing: list[str]  # Video IDs currently processing


class VideoDetailResponse(CamelCaseModel):
    video: VideoMetadata
    transcript_text: Optional[str] = None
    segment_count: int = 0


class TranscriptSegmentResponse(CamelCaseModel):
    segment_id: str
    start_time: float
    end_time: float
    text: str


class VideoTranscriptResponse(CamelCaseModel):
    video_id: str
    video_title: str
    segments: list[TranscriptSegmentResponse]
