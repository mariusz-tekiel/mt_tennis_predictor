"""
Endpoint: GET /api/matches/upcoming
Returns upcoming ATP matches + resolved player names from our database.
"""
from __future__ import annotations

import difflib

from fastapi import APIRouter, Request

from data.live_matches import fetch_upcoming_matches

router = APIRouter(prefix="/api/matches", tags=["matches"])


def _resolve_name(raw: str, known_players: list[str]) -> str | None:
    """
    Try to match a name from TheSportsDB (e.g. 'J. Sinner' or 'Jannik Sinner')
    against our database of known player names.

    Strategy:
    1. Exact match
    2. Last-name match
    3. difflib closest match (cutoff 0.6)
    """
    if not raw or not known_players:
        return None

    raw_clean = raw.strip()

    # 1. Exact
    if raw_clean in known_players:
        return raw_clean

    raw_lower = raw_clean.lower()

    # 2. Last-name match — extract last token of the raw name
    last_token = raw_clean.split()[-1].lower()
    candidates = [p for p in known_players if p.lower().endswith(last_token)]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Try to narrow with first initial
        parts = raw_clean.split()
        if len(parts) >= 2:
            first_initial = parts[0].rstrip(".").lower()
            narrowed = [
                p for p in candidates
                if p.split()[0].lower().startswith(first_initial)
            ]
            if narrowed:
                return narrowed[0]
        return candidates[0]

    # 3. Full fuzzy match
    matches = difflib.get_close_matches(raw_clean, known_players, n=1, cutoff=0.60)
    return matches[0] if matches else None


@router.get("/upcoming")
async def upcoming_matches(request: Request, limit: int = 25, refresh: bool = False):
    predictor = request.app.state.predictor
    known_players: list[str] = predictor._player_names if predictor.is_ready else []

    raw_matches = await fetch_upcoming_matches(limit=limit, force_refresh=refresh)

    enriched = []
    for m in raw_matches:
        p1_resolved = _resolve_name(m["player1_raw"], known_players)
        p2_resolved = _resolve_name(m["player2_raw"], known_players)
        enriched.append({
            **m,
            "player1_resolved": p1_resolved,
            "player2_resolved": p2_resolved,
            "both_resolved": p1_resolved is not None and p2_resolved is not None,
        })

    return {"matches": enriched}
