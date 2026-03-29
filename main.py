"""
MT Tennis Predictor  —  FastAPI entry point
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from data.downloader import load_all_matches
from models.predictor import TennisPredictor
from routers.prediction import router as prediction_router
from routers.matches import router as matches_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    predictor = TennisPredictor()
    app.state.predictor = predictor

    # Load data in background so server starts immediately
    async def _load():
        logger.info("Loading ATP match data...")
        try:
            matches = await load_all_matches()
            logger.info("Building Elo ratings and stats...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, predictor.initialize, matches)
            logger.info(f"Ready — {len(predictor._player_names)} players loaded.")
        except Exception as e:
            logger.error(f"Failed to load data: {e}")

    asyncio.create_task(_load())
    yield


app = FastAPI(
    title="MT Tennis Predictor",
    description="ATP tennis match outcome predictor using Elo + Form + Surface + H2H",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(prediction_router)
app.include_router(matches_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
