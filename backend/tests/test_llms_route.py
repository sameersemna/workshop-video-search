import asyncio

from fastapi.responses import JSONResponse

from app.models.llms import LlmInfo, LlmSelectRequest
from app.routes.llms import get_current_llm, list_llms, select_llm


class _FakeLLMService:
    def __init__(self, behavior: str = "ok") -> None:
        self.behavior = behavior

    def get_available_models(self):
        if self.behavior == "list_error":
            raise RuntimeError("list failed")
        return [
            LlmInfo(
                model_id="qwen3:8b",
                display_name="qwen3:8b",
                hf_model_id="Qwen/Qwen2.5-3B-Instruct",
                requires_gpu=True,
                loaded=True,
            )
        ]

    def get_active_model_id(self):
        if self.behavior == "current_error":
            raise RuntimeError("current failed")
        return "qwen3:8b"

    def has_gpu(self):
        return False

    def select_model(self, model_id: str):
        if self.behavior == "select_error":
            raise RuntimeError("select failed")
        return model_id == "qwen3:8b"


def test_list_llms_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.llms._get_llm_service",
        lambda: _FakeLLMService("ok"),
    )

    response = asyncio.run(list_llms())

    assert response.active_model_id == "qwen3:8b"
    assert response.has_gpu is False
    assert len(response.models) == 1


def test_list_llms_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.llms._get_llm_service",
        lambda: _FakeLLMService("list_error"),
    )

    response = asyncio.run(list_llms())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"LLM_LIST_FAILED","message":"Failed to list LLMs"}}'


def test_select_llm_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.llms._get_llm_service",
        lambda: _FakeLLMService("select_error"),
    )

    response = asyncio.run(select_llm(LlmSelectRequest(model_id="qwen3:8b")))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"LLM_SELECT_FAILED","message":"Failed to select LLM"}}'


def test_current_llm_error_envelope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.llms._get_llm_service",
        lambda: _FakeLLMService("current_error"),
    )

    response = asyncio.run(get_current_llm())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert response.body == b'{"error":{"code":"LLM_CURRENT_FAILED","message":"Failed to get current LLM"}}'
