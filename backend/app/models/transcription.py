from pydantic import BaseModel, HttpUrl
from typing import List, Literal, Optional

from app.models.camel_case import CamelCaseModel

DEFAULT_MODEL = "small"


class TranscriptionRequest(CamelCaseModel):
    video_url: HttpUrl
    model: Literal["tiny", "base", "small", "medium", "large", "turbo"] = DEFAULT_MODEL
    language: Optional[str]


class TranscriptSegment(CamelCaseModel):
    id: str
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    id: str
    text: str
    segments: List[TranscriptSegment]


class TranscriptionResponse(CamelCaseModel):
    id: str
    audio_url: str
    language: str
    text: str
    segments: List[TranscriptSegment]
