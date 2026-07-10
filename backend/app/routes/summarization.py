import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

from app.models.summarization import SummarizationRequest, SummarizationResponse
from app.utils.api_errors import build_error_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

summarization_router = APIRouter()

executor = ThreadPoolExecutor(max_workers=2)


def _get_summarize_by_video_id():
    # Delay heavy service import to request time.
    from app.services.summarization import summarize_by_video_id

    return summarize_by_video_id


@summarization_router.post("/transcript", response_model=SummarizationResponse)
async def summarize_transcript(request: SummarizationRequest):
    """
    Summarizes a video transcript using an LLM.
    """
    logger.info(f"Received summarization request for video ID: {request.video_id}")
    if not request.video_id:
        return build_error_response(
            status_code=400,
            code="INVALID_SUMMARIZATION_REQUEST",
            message="Video ID is required",
        )

    logger.info("Starting summarization...")
    try:
        summarize_by_video_id = _get_summarize_by_video_id()
        summary = await asyncio.get_event_loop().run_in_executor(
            executor,
            summarize_by_video_id,
            request.video_id,
        )
        if summary is None:
            return build_error_response(
                status_code=404,
                code="TRANSCRIPT_NOT_FOUND",
                message=f"Transcript not found for video ID: {request.video_id}",
            )
    except Exception as exc:
        logger.error(f"Unexpected error during summarization: {exc}")
        return build_error_response(
            status_code=500,
            code="SUMMARIZATION_FAILED",
            message="Internal server error during summarization",
        )

    logger.info("Summarization completed successfully")
    return SummarizationResponse(summary=summary)
