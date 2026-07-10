import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient


def _make_router_module(router_attr: str) -> ModuleType:
    module = ModuleType(f"stub.{router_attr}")
    router = APIRouter()

    @router.get("/stub")
    def _stub_route():
        return {"ok": True}

    setattr(module, router_attr, router)
    return module


def _install_main_import_stubs(
    monkeypatch,
    uvicorn_run=None,
    allow_credentials=True,
    cors_origins=None,
):
    if cors_origins is None:
        cors_origins = ["*"]

    config_module = ModuleType("app.config")
    config_module.get_settings = lambda: SimpleNamespace(
        allow_credentials=allow_credentials,
        cors_origins=cors_origins,
    )

    execution_module = ModuleType("app.services.execution")
    execution_module.shutdown_shared_executor = lambda wait=True: None

    background_processor_stub = SimpleNamespace(start=None, stop=None, enqueue=None)
    background_module = ModuleType("app.services.background_processor")
    background_module.background_processor = background_processor_stub

    llm_service_stub = SimpleNamespace(get_active_model_id=lambda: "stub-model")
    llms_module = ModuleType("app.services.llms")
    llms_module.llm_service = llm_service_stub

    search_service_stub = SimpleNamespace(_collection=object())
    search_module = ModuleType("app.services.search")
    search_module.search_service = search_service_stub

    transcription_module = ModuleType("app.services.transcription")
    transcription_module.get_model = lambda: object()
    transcription_module.model_cache = {}

    video_library_stub = SimpleNamespace(get_pending_videos=lambda: [])
    video_library_module = ModuleType("app.services.video_library")
    video_library_module.video_library_service = video_library_stub

    exception_handlers_module = ModuleType("app.utils.exception_handlers")
    exception_handlers_module.register_exception_handlers = lambda app: None

    health_module = ModuleType("app.utils.health")
    health_module.build_default_health_checks = lambda **kwargs: {}
    health_module.build_health_response = lambda checks: {"status": "ok", "checks": checks}

    uvicorn_module = ModuleType("uvicorn")
    uvicorn_module.run = uvicorn_run or (lambda *args, **kwargs: None)

    monkeypatch.setitem(sys.modules, "app.config", config_module)
    monkeypatch.setitem(sys.modules, "app.services.execution", execution_module)
    monkeypatch.setitem(sys.modules, "app.services.background_processor", background_module)
    monkeypatch.setitem(sys.modules, "app.services.llms", llms_module)
    monkeypatch.setitem(sys.modules, "app.services.search", search_module)
    monkeypatch.setitem(sys.modules, "app.services.transcription", transcription_module)
    monkeypatch.setitem(sys.modules, "app.services.video_library", video_library_module)
    monkeypatch.setitem(sys.modules, "app.utils.exception_handlers", exception_handlers_module)
    monkeypatch.setitem(sys.modules, "app.utils.health", health_module)
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_module)

    monkeypatch.setitem(sys.modules, "app.routes.library", _make_router_module("library_router"))
    monkeypatch.setitem(sys.modules, "app.routes.llms", _make_router_module("llm_router"))
    monkeypatch.setitem(sys.modules, "app.routes.media", _make_router_module("media_router"))
    monkeypatch.setitem(sys.modules, "app.routes.search", _make_router_module("search_router"))
    monkeypatch.setitem(
        sys.modules,
        "app.routes.summarization",
        _make_router_module("summarization_router"),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.routes.transcription",
        _make_router_module("transcription_router"),
    )

    return uvicorn_module


def _load_isolated_main_module(
    monkeypatch,
    allow_credentials=True,
    cors_origins=None,
):
    _install_main_import_stubs(
        monkeypatch,
        allow_credentials=allow_credentials,
        cors_origins=cors_origins,
    )

    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("tests.isolated_main", main_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _TrackingCache(dict):
    def __init__(self):
        super().__init__()
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1
        super().clear()


def test_lifespan_resumes_pending_videos_and_shutdowns_cleanly(monkeypatch):
    main_module = _load_isolated_main_module(monkeypatch)

    calls = {
        "get_model": 0,
        "start": 0,
        "stop": 0,
        "get_pending_videos": 0,
        "enqueued": [],
        "shutdown_wait_values": [],
    }

    pending_videos = [SimpleNamespace(id="video-1"), SimpleNamespace(id="video-2")]
    tracking_cache = _TrackingCache()

    def fake_get_model():
        calls["get_model"] += 1
        return object()

    async def fake_start():
        calls["start"] += 1

    async def fake_stop():
        calls["stop"] += 1

    async def fake_enqueue(video_id):
        calls["enqueued"].append(video_id)

    def fake_get_pending_videos():
        calls["get_pending_videos"] += 1
        return pending_videos

    def fake_shutdown_shared_executor(wait=True):
        calls["shutdown_wait_values"].append(wait)

    monkeypatch.setattr(main_module, "get_model", fake_get_model)
    monkeypatch.setattr(main_module.background_processor, "start", fake_start)
    monkeypatch.setattr(main_module.background_processor, "stop", fake_stop)
    monkeypatch.setattr(main_module.background_processor, "enqueue", fake_enqueue)
    monkeypatch.setattr(main_module.video_library_service, "get_pending_videos", fake_get_pending_videos)
    monkeypatch.setattr(main_module, "shutdown_shared_executor", fake_shutdown_shared_executor)
    monkeypatch.setattr(main_module, "model_cache", tracking_cache)

    with TestClient(main_module.app):
        assert calls["get_model"] == 1
        assert calls["start"] == 1
        assert calls["get_pending_videos"] == 1
        assert calls["enqueued"] == ["video-1", "video-2"]

    assert calls["stop"] == 1
    assert calls["shutdown_wait_values"] == [True]
    assert tracking_cache.clear_calls == 1


def test_lifespan_skips_enqueue_when_no_pending_videos(monkeypatch):
    main_module = _load_isolated_main_module(monkeypatch)

    calls = {"enqueued": [], "shutdown_wait_values": []}
    tracking_cache = _TrackingCache()

    async def fake_start():
        return None

    async def fake_stop():
        return None

    async def fake_enqueue(video_id):
        calls["enqueued"].append(video_id)

    monkeypatch.setattr(main_module, "get_model", lambda: object())
    monkeypatch.setattr(main_module.background_processor, "start", fake_start)
    monkeypatch.setattr(main_module.background_processor, "stop", fake_stop)
    monkeypatch.setattr(main_module.background_processor, "enqueue", fake_enqueue)
    monkeypatch.setattr(main_module.video_library_service, "get_pending_videos", lambda: [])
    monkeypatch.setattr(
        main_module,
        "shutdown_shared_executor",
        lambda wait=True: calls["shutdown_wait_values"].append(wait),
    )
    monkeypatch.setattr(main_module, "model_cache", tracking_cache)

    with TestClient(main_module.app):
        pass

    assert calls["enqueued"] == []
    assert calls["shutdown_wait_values"] == [True]
    assert tracking_cache.clear_calls == 1


def test_lifespan_raises_and_skips_side_effects_when_model_load_fails(monkeypatch, caplog):
    main_module = _load_isolated_main_module(monkeypatch)

    calls = {"start": 0, "stop": 0, "get_pending_videos": 0, "shutdown_wait_values": []}
    tracking_cache = _TrackingCache()

    def fake_get_model():
        raise RuntimeError("boom")

    async def fake_start():
        calls["start"] += 1

    async def fake_stop():
        calls["stop"] += 1

    def fake_get_pending_videos():
        calls["get_pending_videos"] += 1
        return [SimpleNamespace(id="video-1")]

    monkeypatch.setattr(main_module, "get_model", fake_get_model)
    monkeypatch.setattr(main_module.background_processor, "start", fake_start)
    monkeypatch.setattr(main_module.background_processor, "stop", fake_stop)
    monkeypatch.setattr(
        main_module.video_library_service,
        "get_pending_videos",
        fake_get_pending_videos,
    )
    monkeypatch.setattr(
        main_module,
        "shutdown_shared_executor",
        lambda wait=True: calls["shutdown_wait_values"].append(wait),
    )
    monkeypatch.setattr(main_module, "model_cache", tracking_cache)

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="Model loading failed"):
            with TestClient(main_module.app):
                pass

    assert any("Error loading model: boom" in message for message in caplog.messages)
    assert calls["start"] == 0
    assert calls["stop"] == 0
    assert calls["get_pending_videos"] == 0
    assert calls["shutdown_wait_values"] == []
    assert tracking_cache.clear_calls == 0


def test_main_module_entrypoint_invokes_uvicorn_run(monkeypatch):
    calls = []

    _install_main_import_stubs(
        monkeypatch,
        uvicorn_run=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "app" / "main.py"),
        run_name="__main__",
    )

    assert calls == [
        (("app.main:app",), {"host": "0.0.0.0", "port": 9091, "reload": True})
    ]


def test_app_cors_disables_credentials_for_wildcard_origin(monkeypatch):
    main_module = _load_isolated_main_module(
        monkeypatch,
        allow_credentials=True,
        cors_origins=["*"],
    )

    cors_middleware = next(
        middleware
        for middleware in main_module.app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_credentials"] is False


def test_app_cors_keeps_credentials_for_specific_origins(monkeypatch):
    main_module = _load_isolated_main_module(
        monkeypatch,
        allow_credentials=True,
        cors_origins=["http://localhost:5173"],
    )

    cors_middleware = next(
        middleware
        for middleware in main_module.app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_credentials"] is True


def test_app_includes_expected_router_prefixes(monkeypatch):
    main_module = _load_isolated_main_module(monkeypatch)

    route_paths = {route.path for route in main_module.app.routes}

    expected_paths = {
        "/transcribe/stub",
        "/search/stub",
        "/llms/stub",
        "/summarize/stub",
        "/media/stub",
        "/library/stub",
    }

    for path in expected_paths:
        assert path in route_paths


def test_app_registers_health_route(monkeypatch):
    main_module = _load_isolated_main_module(monkeypatch)

    route_paths = {route.path for route in main_module.app.routes}

    assert "/health" in route_paths
