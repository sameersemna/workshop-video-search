import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.config import get_settings
from app.models.video import (
    AddVideosResponse,
    AddVideoResponse,
    AddYouTubeVideoRequest,
    ProcessingStatusResponse,
    TranscriptSegmentResponse,
    VideoDetailResponse,
    VideoLibraryResponse,
    VideoMetadata,
    VideoTranscriptResponse,
)
from app.services.video_library import SUPPORTED_VIDEO_EXTENSIONS, video_library_service
from app.utils.api_errors import build_error_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

library_router = APIRouter()
settings = get_settings()

ALLOWED_VIDEO_TYPES = set(settings.allowed_video_content_types)
ALLOWED_WHISPER_MODELS = set(settings.allowed_whisper_models)


def _get_search_service():
    from app.services.search import search_service

    return search_service


def _get_background_processor():
    from app.services.background_processor import background_processor

    return background_processor


@library_router.get("/videos", response_model=VideoLibraryResponse)
async def get_video_library():
    """Get all videos in the library."""
    videos = video_library_service.get_all_videos()
    processing_count = len(
        [v for v in videos if v.status.value in ["pending", "processing"]]
    )

    return VideoLibraryResponse(
        videos=videos,
        processing_count=processing_count,
        total_count=len(videos),
    )


@library_router.get("/videos/grouped")
async def get_videos_grouped():
    """Get videos grouped by source (YouTube vs Uploaded)."""
    grouped = video_library_service.get_videos_by_source()
    return {
        "groups": [
            {"name": name, "videos": videos} for name, videos in grouped.items()
        ]
    }


@library_router.get("/videos/{video_id}", response_model=VideoDetailResponse)
async def get_video(video_id: str):
    """Get details for a specific video."""
    video = video_library_service.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    # Get transcript text if available
    transcript_text = None
    segment_count = 0
    try:
        search_service = _get_search_service()
        transcript_text = search_service.get_transcript_text_by_video_id(video_id)
        if transcript_text:
            segment_count = search_service.get_transcript_segment_count_by_video_id(
                video_id
            )
    except Exception as e:
        logger.warning(f"Could not get transcript for video {video_id}: {e}")

    return VideoDetailResponse(
        video=video,
        transcript_text=transcript_text,
        segment_count=segment_count,
    )


@library_router.get("/videos/{video_id}/transcript", response_model=VideoTranscriptResponse)
async def get_video_transcript(video_id: str):
    """Get transcript segments for a specific video."""
    video = video_library_service.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    try:
        search_service = _get_search_service()
        segments_data = search_service.get_transcript_segments_by_video_id(video_id)

        if not segments_data:
            return VideoTranscriptResponse(
                video_id=video_id, video_title=video.title, segments=[]
            )

        segments = [
            TranscriptSegmentResponse(
                segment_id=segment["segment_id"],
                start_time=segment["start_time"],
                end_time=segment["end_time"],
                text=segment["text"],
            )
            for segment in segments_data
        ]

        return VideoTranscriptResponse(
            video_id=video_id, video_title=video.title, segments=segments
        )

    except Exception as exc:
        logger.error(f"Error fetching transcript for video {video_id}: {exc}")
        return build_error_response(
            status_code=500,
            code="TRANSCRIPT_FETCH_FAILED",
            message="Failed to fetch transcript",
        )


@library_router.post("/videos/youtube", response_model=AddVideoResponse)
async def add_youtube_video(request: AddYouTubeVideoRequest):
    """Add a YouTube video to the library."""
    logger.info(f"Adding YouTube video: {request.url} with model: {request.model}")

    try:
        response = video_library_service.add_youtube_video(str(request.url), request.model)

        # Enqueue for background processing
        background_processor = _get_background_processor()
        await background_processor.enqueue(response.video_id)

        return response
    except Exception as exc:
        logger.error(f"Error adding YouTube video: {exc}")
        return build_error_response(
            status_code=500,
            code="YOUTUBE_VIDEO_ADD_FAILED",
            message="Failed to add video",
        )


@library_router.post("/videos/upload", response_model=AddVideosResponse)
async def upload_videos(
    files: list[UploadFile] = File(...),
    model: str = Form(default="base"),
):
    """Upload one or more video files to the library."""
    logger.info(f"Uploading {len(files)} video file(s) with model: {model}")

    if model not in ALLOWED_WHISPER_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported whisper model '{model}'",
        )

    if len(files) > settings.max_upload_files_per_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Too many files uploaded in one request. "
                f"Maximum allowed: {settings.max_upload_files_per_request}"
            ),
        )

    added = []
    errors = []

    for file in files:
        try:
            if not file.filename:
                errors.append({"filename": "<missing>", "error": "Missing filename"})
                continue

            suffix = Path(file.filename).suffix.lower()
            if suffix not in SUPPORTED_VIDEO_EXTENSIONS:
                errors.append(
                    {
                        "filename": file.filename,
                        "error": f"Unsupported extension: {suffix or '<none>'}",
                    }
                )
                continue

            # Validate file type
            if file.content_type not in ALLOWED_VIDEO_TYPES:
                errors.append(
                    {
                        "filename": file.filename,
                        "error": f"Unsupported file type: {file.content_type}",
                    }
                )
                continue

            # Read file content
            content = await file.read()

            if not content:
                errors.append({"filename": file.filename, "error": "File is empty"})
                continue

            if len(content) > settings.max_upload_file_size_bytes:
                errors.append(
                    {
                        "filename": file.filename,
                        "error": (
                            "File exceeds max allowed size of "
                            f"{settings.max_upload_file_size_mb} MB"
                        ),
                    }
                )
                continue

            # Add to library
            response = video_library_service.add_uploaded_video(
                file.filename or "video.mp4", content, model
            )
            added.append(response)

            # Enqueue for background processing
            background_processor = _get_background_processor()
            await background_processor.enqueue(response.video_id)

            logger.info(f"Added video: {file.filename} ({response.video_id})")

        except Exception as e:
            logger.error(f"Error uploading {file.filename}: {e}")
            errors.append({"filename": file.filename, "error": str(e)})

    return AddVideosResponse(added=added, errors=errors)


@library_router.delete("/videos/{video_id}")
async def delete_video(video_id: str):
    """Delete a video from the library."""
    video = video_library_service.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    # Delete from ChromaDB
    try:
        search_service = _get_search_service()
        deleted = search_service.delete_video_index_data(video_id)
        logger.info(
            "Deleted index data for video %s (transcript=%s, visual=%s)",
            video_id,
            deleted["transcript"],
            deleted["visual"],
        )
    except Exception as e:
        logger.error(f"Error deleting from ChromaDB: {e}")

    # Delete from library (also cleans up files)
    success = video_library_service.delete_video(video_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete video",
        )

    return {"message": "Video deleted successfully", "video_id": video_id}


@library_router.get("/status", response_model=ProcessingStatusResponse)
async def get_processing_status():
    """Get the current processing queue status."""
    background_processor = _get_background_processor()
    status = background_processor.get_status()
    return ProcessingStatusResponse(
        queue_length=status["queue_length"],
        processing=status["processing"],
    )


@library_router.post("/videos/{video_id}/retry")
async def retry_video(video_id: str):
    """Retry processing a failed video."""
    video = video_library_service.get_video(video_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    if video.status.value not in ["failed", "pending"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video is {video.status.value}, cannot retry",
        )

    # Reset status and re-enqueue
    from app.models.video import ProcessingStatus

    video_library_service.update_video_status(video_id, ProcessingStatus.PENDING)
    background_processor = _get_background_processor()
    await background_processor.enqueue(video_id)

    return {"message": "Video re-queued for processing", "video_id": video_id}


@library_router.delete("/clear")
async def clear_library():
    """Clear all videos from the library and clean up all associated data."""
    logger.info("Clearing entire video library")

    # Clear ChromaDB collections
    try:
        search_service = _get_search_service()
        deleted = search_service.clear_all_index_data()
        logger.info(
            "Cleared index data (transcript=%s, visual=%s)",
            deleted["transcript"],
            deleted["visual"],
        )
    except Exception as e:
        logger.error(f"Error clearing ChromaDB: {e}")

    # Clear video library (files and metadata)
    result = video_library_service.clear_library()

    return {
        "message": "Library cleared successfully",
        "deleted_count": result["deleted_count"],
        "errors": result["errors"],
    }
