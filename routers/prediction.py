from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["prediction"])


class PredictRequest(BaseModel):
    player1: str
    player2: str
    surface: str = "Hard"


@router.get("/players/search")
async def search_players(q: str, request: Request):
    predictor = request.app.state.predictor
    if not predictor.is_ready:
        raise HTTPException(503, "Model not ready yet")
    results = predictor.search_players(q)
    return {"players": results}


@router.get("/players/{name}/profile")
async def player_profile(name: str, request: Request):
    predictor = request.app.state.predictor
    if not predictor.is_ready:
        raise HTTPException(503, "Model not ready yet")
    if name not in predictor._player_names:
        raise HTTPException(404, f"Player '{name}' not found")
    return predictor.player_profile(name)


@router.post("/predict")
async def predict(body: PredictRequest, request: Request):
    predictor = request.app.state.predictor
    if not predictor.is_ready:
        raise HTTPException(503, "Model is still loading data, try again in a moment")

    for pname in [body.player1, body.player2]:
        if pname not in predictor._player_names:
            raise HTTPException(404, f"Player '{pname}' not found in database")

    if body.player1 == body.player2:
        raise HTTPException(400, "Players must be different")

    valid_surfaces = ["Hard", "Clay", "Grass", "Carpet"]
    surface = body.surface.capitalize()
    if surface not in valid_surfaces:
        raise HTTPException(400, f"Surface must be one of: {valid_surfaces}")

    return predictor.predict(body.player1, body.player2, surface)


@router.get("/status")
async def status(request: Request):
    predictor = request.app.state.predictor
    return {
        "ready": predictor.is_ready,
        "players_loaded": len(predictor._player_names) if predictor.is_ready else 0,
    }
