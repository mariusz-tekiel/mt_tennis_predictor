"""
Fetches recent/upcoming ATP matches from TheSportsDB (free API, key=3).
Strategy: scan rounds of the current season to find the latest available matches.
Returns normalised list with surface inferred from tournament name.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
ATP_LEAGUE_ID = "4464"   # ATP World Tour
CACHE_TTL_SECONDS = 1800  # 30 minutes — in-memory cache
DISK_CACHE_TTL_HOURS = 6  # hours — disk cache survives restarts
DISK_CACHE_FILE = Path(__file__).parent / "cache" / "atp_matches.json"

_mem_cache: dict = {"data": None, "ts": None}


def _load_disk_cache() -> list[dict] | None:
    try:
        if not DISK_CACHE_FILE.exists():
            return None
        with DISK_CACHE_FILE.open() as f:
            obj = json.load(f)
        ts = datetime.fromisoformat(obj["ts"])
        if (datetime.now() - ts).total_seconds() < DISK_CACHE_TTL_HOURS * 3600:
            return obj["data"]
    except Exception:
        pass
    return None


def _save_disk_cache(data: list[dict]) -> None:
    try:
        DISK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with DISK_CACHE_FILE.open("w") as f:
            json.dump({"ts": datetime.now().isoformat(), "data": data}, f)
    except Exception as e:
        logger.warning(f"Could not save disk cache: {e}")

# ── Surface inference ─────────────────────────────────────────────────────────
GRASS_KEYWORDS = [
    "wimbledon", "queens", "queen's", "halle", "s-hertogenbosch", "hertogenbosch",
    "eastbourne", "newport",
]
CLAY_KEYWORDS = [
    "roland garros", "french open", "monte-carlo", "monte carlo",
    "madrid", "rome", "italian open", "barcelona", "munich", "hamburg",
    "estoril", "bucharest", "istanbul", "marrakech", "gstaad", "umag",
    "kitzbuhel", "bastad", "geneva", "lyon", "cordoba", "buenos aires",
    "rio", "sao paulo", "santiago",
]
HARD_KEYWORDS = [
    "australian open", "us open", "miami", "indian wells", "montreal", "toronto",
    "cincinnati", "shanghai", "paris", "vienna", "dubai", "doha", "qatar",
    "acapulco", "rotterdam", "washington", "brisbane", "sydney", "adelaide",
    "astana", "metz", "st. petersburg", "antwerp", "beijing", "tokyo",
]

SURFACE_LABELS = {"Hard": "Twarda", "Clay": "Ceglasta", "Grass": "Trawa", "Carpet": "Dywan"}
SURFACE_ICONS  = {"Hard": "🔵",     "Clay": "🟤",       "Grass": "🟢",    "Carpet": "⚪"}


# Known multi-word ATP tournament name prefixes (longest first for greedy match)
_KNOWN_TOURNEYS = [
    "Australian Open", "Roland Garros", "French Open", "Wimbledon", "US Open",
    "BNP Paribas Open", "Miami Open", "Monte-Carlo Masters", "Mutua Madrid Open",
    "Internazionali BNL d'Italia", "French Open", "Cinch Championships",
    "Halle Open", "Wimbledon", "Rogers Cup", "Western & Southern Open",
    "Laver Cup", "Shanghai Rolex Masters", "Rolex Paris Masters",
    "Erste Bank Open", "Swiss Indoors", "Nitto ATP Finals",
    "Brisbane International", "Sydney International", "Adelaide International",
    "Dubai Duty Free Championships", "Qatar Total Open",
    "ABN AMRO World Tennis Tournament", "Open Sud de France",
    "Argentina Open", "Cordoba Open", "Rio Open", "Ecuador Open",
    "Delray Beach Open", "New York Open", "Open 13 Provence",
    "Abierto Mexicano Telcel", "Dubai Tennis Championships",
    "Abierto Mexicano", "Astana Open", "European Open",
    "Moselle Open", "Metz Open", "St. Petersburg Open",
    "Sofia Open", "Stockholm Open", "Swiss Indoors Basel",
    "Tenerife Open", "Gijon Open",
]
_KNOWN_TOURNEYS_LOWER = [(t.lower(), t) for t in sorted(_KNOWN_TOURNEYS, key=len, reverse=True)]


def _split_tourney_player(left_str: str) -> tuple[str, str]:
    """
    Split 'Tournament Name Player1Surname' into (tournament, player_name).
    Uses known tournament list, falling back to 'strip last token'.
    """
    left_lower = left_str.lower()
    for kw_lower, kw_orig in _KNOWN_TOURNEYS_LOWER:
        if left_lower.startswith(kw_lower):
            player = left_str[len(kw_lower):].strip()
            if player:
                return kw_orig, player
    # Fallback: last token(s) = player, rest = tournament
    tokens = left_str.split()
    if len(tokens) == 1:
        return "", tokens[0]
    # Try to keep multi-word player names (2 words max)
    if len(tokens) >= 3:
        return " ".join(tokens[:-1]), tokens[-1]
    return tokens[0], tokens[1]


def infer_surface(text: str) -> str:
    t = text.lower()
    for kw in GRASS_KEYWORDS:
        if kw in t: return "Grass"
    for kw in CLAY_KEYWORDS:
        if kw in t: return "Clay"
    for kw in HARD_KEYWORDS:
        if kw in t: return "Hard"
    return "Hard"


def _parse_event(ev: dict) -> dict | None:
    event_name = (ev.get("strEvent") or "").strip()
    if not event_name:
        return None

    # Skip non-tennis, doubles, women
    event_lower = event_name.lower()
    if any(w in event_lower for w in ["doubles", "mixed", "wta", "women's"]):
        return None
    if ev.get("strSport", "").lower() not in ("tennis", ""):
        return None

    # TheSportsDB tennis format: "Tournament Name Player1 vs Player2"
    # strHomeTeam/Away are sometimes null — extract from strEvent
    home = (ev.get("strHomeTeam") or "").strip()
    away = (ev.get("strAwayTeam") or "").strip()

    if not home or not away:
        # Extract from "Tournament Player1 vs Player2"
        if " vs " not in event_name:
            return None
        left, right = event_name.split(" vs ", 1)
        away = right.strip()
        # Tournament name is the known prefix — strip last 1-2 words = player name
        # Use known tournament list to be more precise
        tourney_end, home = _split_tourney_player(left.strip())
        tourney = tourney_end
    else:
        tourney = ev.get("strLeague") or event_name

    if not home or not away:
        return None

    surface = infer_surface(event_name + " " + (ev.get("strVenue") or ""))

    date_str = ev.get("dateEvent") or ""
    time_str = (ev.get("strTime") or "00:00:00")[:5]
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        dt = None

    score_h = ev.get("intHomeScore")
    score_a = ev.get("intAwayScore")
    finished = score_h is not None and score_a is not None

    return {
        "id": ev.get("idEvent", ""),
        "tournament": tourney,
        "round": str(ev.get("intRound") or ev.get("strRound") or ""),
        "date": dt.isoformat() if dt else date_str,
        "date_display": dt.strftime("%d %b %Y").lstrip("0") if dt else date_str,
        "player1_raw": home,
        "player2_raw": away,
        "surface": surface,
        "surface_label": SURFACE_LABELS[surface],
        "surface_icon": SURFACE_ICONS[surface],
        "finished": finished,
        "score": f"{score_h}–{score_a}" if finished else None,
    }


async def _fetch_round(client: httpx.AsyncClient, round_num: int, season: str) -> list[dict] | None:
    """Returns events list, or None on 429 (rate limited)."""
    url = f"{THESPORTSDB_BASE}/eventsround.php?id={ATP_LEAGUE_ID}&r={round_num}&s={season}"
    try:
        r = await client.get(url, timeout=8)
        if r.status_code == 429:
            return None  # signal rate limit
        r.raise_for_status()
        return r.json().get("events") or []
    except Exception:
        return []


async def fetch_upcoming_matches(limit: int = 30, force_refresh: bool = False) -> list[dict]:
    """
    Scan rounds sequentially (to avoid 429), find the latest ATP matches,
    and return them sorted by date desc (most recent first).
    """
    now = datetime.now()

    # 1. In-memory cache
    if (
        not force_refresh
        and _mem_cache["data"] is not None
        and _mem_cache["ts"] is not None
        and (now - _mem_cache["ts"]).total_seconds() < CACHE_TTL_SECONDS
    ):
        return _mem_cache["data"][:limit]

    # 2. Disk cache (survives restarts)
    if not force_refresh:
        disk = _load_disk_cache()
        if disk is not None:
            _mem_cache["data"] = disk
            _mem_cache["ts"] = now
            return disk[:limit]

    today = now
    current_year = str(today.year)
    prev_year = str(today.year - 1)

    all_raw: list[dict] = []
    rate_limited = False

    async with httpx.AsyncClient(timeout=10) as client:
        for season in [current_year, prev_year]:
            last_empty = 0
            for rn in range(1, 25):
                events = await _fetch_round(client, rn, season)
                if events is None:   # 429
                    rate_limited = True
                    break
                if not events:
                    last_empty += 1
                    if last_empty >= 2:
                        break
                    continue
                last_empty = 0
                all_raw.extend(events)
                await asyncio.sleep(0.3)   # gentle throttle
            if all_raw or rate_limited:
                break

    # On 429 fall back to any cached data we have
    if rate_limited and not all_raw:
        fallback = _load_disk_cache()
        if fallback:
            logger.warning("Rate limited by TheSportsDB, returning stale cache")
            return fallback[:limit]
        return []

    # Parse
    parsed: list[dict] = []
    seen: set[str] = set()
    for ev in all_raw:
        p = _parse_event(ev)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            parsed.append(p)

    if not parsed:
        return []

    # Filter: last 90 days → next 60 days
    window_start = today - timedelta(days=90)
    window_end   = today + timedelta(days=60)
    in_window: list[dict] = []
    for m in parsed:
        try:
            dt = datetime.fromisoformat(m["date"])
            if window_start <= dt <= window_end:
                in_window.append(m)
        except Exception:
            pass

    # If nothing in window, fall back to the most recent matches available
    if not in_window:
        in_window = sorted(parsed, key=lambda x: x["date"], reverse=True)[:limit]

    # Sort: most recent first
    in_window.sort(key=lambda x: x["date"], reverse=True)

    result = in_window[:limit]
    _mem_cache["data"] = result
    _mem_cache["ts"] = now
    _save_disk_cache(result)
    return result
