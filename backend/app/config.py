from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )
    allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")

    max_upload_file_size_mb: int = Field(default=500, alias="MAX_UPLOAD_FILE_SIZE_MB")
    max_upload_files_per_request: int = Field(default=10, alias="MAX_UPLOAD_FILES_PER_REQUEST")
    allowed_video_content_types: list[str] = Field(
        default_factory=lambda: [
            "video/mp4",
            "video/avi",
            "video/mov",
            "video/quicktime",
            "video/x-msvideo",
            "video/x-matroska",
            "video/mkv",
            "video/webm",
        ],
        alias="ALLOWED_VIDEO_CONTENT_TYPES",
    )
    allowed_whisper_models: list[str] = Field(
        default_factory=lambda: ["tiny", "base", "small", "medium", "large", "turbo"],
        alias="ALLOWED_WHISPER_MODELS",
    )
    max_search_results: int = Field(default=20, alias="MAX_SEARCH_RESULTS")

    @field_validator("max_upload_file_size_mb")
    @classmethod
    def validate_max_upload_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_UPLOAD_FILE_SIZE_MB must be > 0")
        return value

    @field_validator("max_upload_files_per_request")
    @classmethod
    def validate_upload_files_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_UPLOAD_FILES_PER_REQUEST must be > 0")
        return value

    @field_validator("max_search_results")
    @classmethod
    def validate_max_search_results(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_SEARCH_RESULTS must be > 0")
        return value

    @property
    def max_upload_file_size_bytes(self) -> int:
        return self.max_upload_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
