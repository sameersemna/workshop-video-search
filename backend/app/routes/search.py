import logging

from fastapi import APIRouter

from app.config import get_settings
from app.models.search import (
    QuestionRequest,
    QuestionResponse,
)
from app.utils.api_errors import build_error_response
from app.utils.search_query_guard import normalize_search_query

search_router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _get_search_service():
    # Delayed import avoids importing heavy search dependencies during route module import.
    from app.services.search import search_service

    return search_service


@search_router.post("/query", response_model=QuestionResponse)
async def query_transcript(request: QuestionRequest):
    """
    Query transcripts for relevant segments using the specified search type.

    Args:
        question: The question or search query
        video_ids: Optional list of video IDs to search (None = all videos)
        top_k: Maximum number of results to return
        search_type: The type of search to perform (keyword, semantic, llm, visual)
    """
    try:
        normalized_query = normalize_search_query(
            question=request.question,
            video_ids=request.video_ids,
            top_k=request.top_k,
            max_top_k=settings.max_search_results,
        )
    except ValueError as exc:
        return build_error_response(
            status_code=422,
            code="INVALID_QUERY",
            message=str(exc),
        )

    try:
        search_service = _get_search_service()
        response = search_service.query_transcript(
            question=normalized_query.question,
            video_ids=normalized_query.video_ids,
            top_k=normalized_query.top_k,
            search_type=request.search_type,
        )
        return response
    except ValueError as exc:
        return build_error_response(
            status_code=422,
            code="INVALID_QUERY",
            message=str(exc),
        )
    except Exception as exc:
        logger.exception("Failed to execute search query: %s", exc)
        return build_error_response(
            status_code=500,
            code="SEARCH_QUERY_FAILED",
            message="Failed to execute search query",
        )
