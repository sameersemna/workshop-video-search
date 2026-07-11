import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.execution import shutdown_shared_executor
from app.routes.library import library_router
from app.routes.llms import llm_router
from app.routes.media import media_router
from app.routes.search import search_router
from app.routes.summarization import summarization_router
from app.routes.transcription import transcription_router
from app.services.background_processor import background_processor
from app.services.llms import llm_service
from app.services.search import search_service
from app.services.transcription import get_model, model_cache, WHISPER_BACKEND
from app.utils.exception_handlers import register_exception_handlers
from app.utils.health import build_default_health_checks, build_health_response
from app.services.video_library import video_library_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load default model into memory on startup, start background processor,
    and clean up on shutdown.
    """
    if WHISPER_BACKEND == "remote":
        logger.info(
            "WHISPER_BACKEND=remote: skipping local Whisper model load."
        )
    else:
        logger.info("Loading default model...")
        try:
            get_model()
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise RuntimeError(f"Model loading failed: {e}")

    # Start background processor
    logger.info("Starting background processor...")
    await background_processor.start()

    # Resume any pending or processing videos
    pending_videos = video_library_service.get_pending_videos()
    if pending_videos:
        logger.info(f"Resuming {len(pending_videos)} pending videos...")
        for video in pending_videos:
            await background_processor.enqueue(video.id)

    yield

    # Cleanup
    logger.info("Stopping background processor...")
    await background_processor.stop()

    logger.info("Shutting down shared thread pool executor...")
    shutdown_shared_executor(wait=True)

    logger.info("Unloading models...")
    model_cache.clear()

    logger.info("Shutting down...")


app = FastAPI(title="Video search and transcription API", lifespan=lifespan)
register_exception_handlers(app)

allow_credentials = settings.allow_credentials and "*" not in settings.cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcription_router, prefix="/transcribe")
app.include_router(search_router, prefix="/search")
app.include_router(llm_router, prefix="/llms")
app.include_router(summarization_router, prefix="/summarize")
app.include_router(media_router, prefix="/media")
app.include_router(library_router, prefix="/library")


@app.get("/health")
async def health_check():
    checks = build_default_health_checks(
        model_cache=model_cache,
        search_service=search_service,
        llm_service=llm_service,
    )

    return build_health_response(checks)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=9091, reload=True)
