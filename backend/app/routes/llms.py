import logging

from fastapi import APIRouter

from app.models.llms import (
    LlmListResponse,
    LlmSelectRequest,
    LlmSelectResponse,
    CurrentLlmInfoResponse,
)
from app.utils.api_errors import build_error_response

llm_router = APIRouter()
logger = logging.getLogger(__name__)


def _get_llm_service():
    # Delay heavy service import to request time.
    from app.services.llms import llm_service

    return llm_service


@llm_router.get("", response_model=LlmListResponse)
async def list_llms():
    """Get list of available LLM models."""
    try:
        llm_service = _get_llm_service()
        models = llm_service.get_available_models()
        active_model_id = llm_service.get_active_model_id()
        has_gpu = llm_service.has_gpu()

        return LlmListResponse(
            models=models, active_model_id=active_model_id, has_gpu=has_gpu
        )
    except Exception as exc:
        logger.exception("Failed to list LLMs: %s", exc)
        return build_error_response(
            status_code=500,
            code="LLM_LIST_FAILED",
            message="Failed to list LLMs",
        )


@llm_router.post("/select", response_model=LlmSelectResponse)
async def select_llm(request: LlmSelectRequest):
    """Select and load a specific LLM model."""
    try:
        llm_service = _get_llm_service()
        success = llm_service.select_model(request.model_id)

        if success:
            return LlmSelectResponse(success=True, model_id=request.model_id)
        else:
            return LlmSelectResponse(success=False, model_id=None)
    except Exception as exc:
        logger.exception("Failed to select LLM: %s", exc)
        return build_error_response(
            status_code=500,
            code="LLM_SELECT_FAILED",
            message="Failed to select LLM",
        )


@llm_router.get("/current", response_model=CurrentLlmInfoResponse)
async def get_current_llm():
    """Get the currently active LLM."""
    try:
        llm_service = _get_llm_service()
        current_model_id = llm_service.get_active_model_id()
        if current_model_id:
            models = llm_service.get_available_models()
            current_model = next(
                (m for m in models if m.model_id == current_model_id), None
            )
            return current_model
        else:
            return None
    except Exception as exc:
        logger.exception("Failed to get current LLM: %s", exc)
        return build_error_response(
            status_code=500,
            code="LLM_CURRENT_FAILED",
            message="Failed to get current LLM",
        )
