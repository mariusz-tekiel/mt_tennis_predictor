"""
Fetches current/upcoming ATP matches from ESPN public API (no key required).
Falls back to TheSportsDB if ESPN fails.
Caches results to disk (3h) and memory (30min).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ESPN_ATP_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
ATP_LEAGUE_ID = "4464"

CACHE_TTL_SECONDS = 1800
DISK_CACHE_TTL_HOURS = 3
DISK_CACHE_FILE = Path(__file__).parent / "cache" / "atp_matches.json"

_mem_cache: dict = {"data": None, "ts": None}

SURFACE_LABELS = {"Hard": "Twarda", "Clay": "Ceglasta", "Grass": "Trawa", "Carpet": "Dywan"}
SURFACE_ICONS  = {"Hard": "🔵",     "Clay": "🟤",       "Grass": "🟢",    "Carpet": "⚪"}

GRASS_KW = ["wimbledon","queens","queen's","halle","hertogenbosch","eastbourne","newport"]
CLAY_KW  = ["roland garros","french open","monte-carlo","monte carlo","madrid","rome","italian",
            "barcelona","munich","hamburg","estoril","bucharest","istanbul","marrakech","gstaad",
            "umag","kitzbuhel","bastad","geneva","lyon","cordoba","buenos aires","rio","sao paulo",
            "santiago","tiriac","hassan","casablanca","clay court","houston","fayez sarofim",
            "grand prix hassan","marrakesh"]
HARD_KW  = ["australian open","us open","miami","indian wells","montreal","toronto","cincinnati",
            "shanghai","paris","vienna","dubai","doha","qatar","acapulco","rotterdam","washington",
            "brisbane","sydney","adelaide","astana","metz","st. petersburg","antwerp","beijing",
            "tokyo","bnp paribas open"]


def infer_surface(text: str) -> str:
    t = text.lower()
    for kw in GRASS_KW:
        if kw in t: return "Grass"
    for kw in CLAY_KW:
        if kw in t: return "Clay"
    for kw in HARD_KW:
        if kw in t: return "Hard"
    return "Hard"


# ── Disk cache ────────────────────────────────────────────────────────────────
def _load_disk() -> list[dict] | None:
    try:
        if not DISK_CACHE_FILE.exists():
            return None
        obj = json.loads(DISK_CACHE_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(obj["ts"])
        if (datetime.now() - ts).total_seconds() < DISK_CACHE_TTL_HOURS * 3600:
            return obj["data"]
    except Exception:
        pass
    return None


def _save_disk(data: list[dict]) -> None:
    try:
        DISK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DISK_CACHE_FILE.write_text(
            json.dumps({"ts": datetime.now().isoformat(), "data": data}), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Disk cache write failed: {e}")


# ── ESPN fetcher ──────────────────────────────────────────────────────────────
def _parse_espn_competition(comp: dict, tourney: str, surface: str) -> dict | None:
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    def get_name(c: dict) -> str:
        ath = c.get("athlete") or {}
        return (ath.get("displayName") or ath.get("fullName") or "").strip()

    p1 = get_name(competitors[0])
    p2 = get_name(competitors[1])
    if not p1 or not p2:
        return None
    if any(x in (p1 + p2).upper() for x in ["TBD", "BYE", "WINNER OF"]):
        return None

    status_type = (comp.get("status") or {}).get("type") or {}
    state = status_type.get("state", "pre")       # pre | in | post
    status_text = status_type.get("description", "")

    date_str = comp.get("date") or comp.get("startDate") or ""
    try:
        dt_utc = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone().replace(tzinfo=None)
    except Exception:
        dt_local = None

    score = None
    if state in ("in", "post"):
        s0 = competitors[0].get("score", "")
        s1 = competitors[1].get("score", "")
        if s0 or s1:
            score = f"{s0}–{s1}"

    return {
        "id": comp.get("id", ""),
        "tournament": tourney,
        "round": "",
        "date": dt_local.isoformat() if dt_local else date_str,
        "date_display": dt_local.strftime("%d %b %Y").lstrip("0") if dt_local else date_str[:10],
        "time_display": dt_local.strftime("%H:%M") if dt_local else "",
        "player1_raw": p1,
        "player2_raw": p2,
        "surface": surface,
        "surface_label": SURFACE_LABELS[surface],
        "surface_icon": SURFACE_ICONS[surface],
        "state": state,
        "status_text": status_text,
        "finished": state == "post",
        "live": state == "in",
        "score": score,
    }


def _parse_espn_events(data: dict) -> list[dict]:
    matches: list[dict] = []
    for event in data.get("events") or []:
        tourney = event.get("name") or event.get("shortName") or "ATP"
        surface = infer_surface(tourney)
        groupings = event.get("groupings") or []
        if groupings:
            for grouping in groupings:
                grp = (grouping.get("grouping") or {}).get("displayName", "")
                if any(w in grp.lower() for w in ["doubles", "mixed"]):
                    continue
                for comp in grouping.get("competitions") or []:
                    m = _parse_espn_competition(comp, tourney, surface)
                    if m:
                        matches.append(m)
        else:
            for comp in event.get("competitions") or []:
                m = _parse_espn_competition(comp, tourney, surface)
                if m:
                    matches.append(m)
    return matches


async def _fetch_espn(days_back: int = 2, days_forward: int = 10) -> list[dict]:
    today = datetime.now()
    start = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    end   = (today + timedelta(days=days_forward)).strftime("%Y%m%d")

    try:
        async with httpx.AsyncClient(
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        ) as client:
            # Try with date range
            r = await client.get(ESPN_ATP_URL, params={"dates": f"{start}-{end}"})
            r.raise_for_status()
            data = r.json()
            matches = _parse_espn_events(data)

            # If date range returned nothing, try without dates (current scoreboard)
            if not matches:
                r2 = await client.get(ESPN_ATP_URL)
                r2.raise_for_status()
                matches = _parse_espn_events(r2.json())
    except Exception as e:
        logger.warning(f"ESPN fetch failed: {e}")
        return []

    logger.info(f"ESPN returned {len(matches)} matches")
    return matches


# ── TheSportsDB fallback ──────────────────────────────────────────────────────
_KNOWN_TOURNEYS = [
    ("bnp paribas open", "BNP Paribas Open"),
    ("miami open", "Miami Open"),
    ("monte-carlo", "Monte-Carlo Masters"),
    ("madrid open", "Madrid Open"),
    ("italian open", "Italian Open"),
    ("roland garros", "Roland Garros"),
    ("wimbledon", "Wimbledon"),
    ("us open", "US Open"),
    ("australian open", "Australian Open"),
    ("brisbane international", "Brisbane International"),
    ("sydney international", "Sydney International"),
]


def _split_tourney_player(left: str) -> tuple[str, str]:
    ll = left.lower()
    for kw, name in sorted(_KNOWN_TOURNEYS, key=lambda x: -len(x[0])):
        if ll.startswith(kw):
            player = left[len(kw):].strip()
            if player:
                return name, player
    tokens = left.split()
    if len(tokens) >= 3:
        return " ".join(tokens[:-1]), tokens[-1]
    if len(tokens) == 2:
        return tokens[0], tokens[1]
    return "", left


def _parse_sportsdb_event(ev: dict) -> dict | None:
    event_name = (ev.get("strEvent") or "").strip()
    if not event_name or " vs " not in event_name:
        return None
    if any(w in event_name.lower() for w in ["doubles", "mixed", "wta", "women's"]):
        return None
    if ev.get("strSport", "").lower() not in ("tennis", ""):
        return None

    left, right = event_name.split(" vs ", 1)
    away = right.strip()
    tourney, home = _split_tourney_player(left.strip())
    if not home or not away:
        return None

    date_str = ev.get("dateEvent") or ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        dt = None

    surface = infer_surface(event_name)
    score_h = ev.get("intHomeScore")
    score_a = ev.get("intAwayScore")

    return {
        "id": f"sdb-{ev.get('idEvent','')}",
        "tournament": tourney or "ATP",
        "round": str(ev.get("intRound") or ""),
        "date": dt.isoformat() if dt else date_str,
        "date_display": dt.strftime("%d %b %Y").lstrip("0") if dt else date_str,
        "time_display": "",
        "player1_raw": home,
        "player2_raw": away,
        "surface": surface,
        "surface_label": SURFACE_LABELS[surface],
        "surface_icon": SURFACE_ICONS[surface],
        "state": "post" if score_h is not None else "pre",
        "status_text": "",
        "finished": score_h is not None,
        "live": False,
        "score": score_h and f"{score_h}–{score_a}",
    }


async def _fetch_sportsdb_fallback() -> list[dict]:
    results = []
    async with httpx.AsyncClient(timeout=10) as client:
        # Primary: eventsnext.php — returns upcoming events without needing a round number
        try:
            r = await client.get(f"{THESPORTSDB_BASE}/eventsnext.php?id={ATP_LEAGUE_ID}")
            if r.status_code != 429:
                for ev in (r.json().get("events") or []):
                    m = _parse_sportsdb_event(ev)
                    if m:
                        results.append(m)
        except Exception:
            pass

        if not results:
            # Fallback: eventsround with a dynamically estimated round range
            # Calibrated from observed data: day ~54 of year ≈ round 15
            day_of_year = datetime.now().timetuple().tm_yday
            est_round = max(1, round(day_of_year * 15 / 54))
            for rn in range(max(1, est_round - 3), est_round + 8):
                try:
                    r = await client.get(
                        f"{THESPORTSDB_BASE}/eventsround.php?id={ATP_LEAGUE_ID}&r={rn}&s=2026"
                    )
                    if r.status_code == 429:
                        break
                    for ev in (r.json().get("events") or []):
                        m = _parse_sportsdb_event(ev)
                        if m:
                            results.append(m)
                    await asyncio.sleep(0.3)
                except Exception:
                    break
    return results


# ── Public API ────────────────────────────────────────────────────────────────
async def fetch_upcoming_matches(limit: int = 40, force_refresh: bool = False) -> list[dict]:
    now = datetime.now()

    if (
        not force_refresh
        and _mem_cache["data"] is not None
        and _mem_cache["ts"] is not None
        and (now - _mem_cache["ts"]).total_seconds() < CACHE_TTL_SECONDS
    ):
        return _mem_cache["data"][:limit]

    if not force_refresh:
        disk = _load_disk()
        if disk is not None:
            _mem_cache.update({"data": disk, "ts": now})
            return disk[:limit]

    matches = await _fetch_espn()

    if not matches:
        logger.info("ESPN returned no matches — trying TheSportsDB fallback")
        matches = await _fetch_sportsdb_fallback()

    if not matches:
        return []

    # Deduplicate
    seen: set[str] = set()
    unique = [m for m in matches if not (m["id"] in seen or seen.add(m["id"]))]  # type: ignore

    # Sort: live → upcoming (asc date) → finished (desc date)
    def _sort_key(m: dict):
        order = {"in": 0, "pre": 1, "post": 2}.get(m["state"], 3)
        try:
            ts = datetime.fromisoformat(m["date"]).timestamp()
        except Exception:
            ts = 0.0
        return (order, ts if m["state"] != "post" else -ts)

    unique.sort(key=_sort_key)

    def _match_date(m: dict):
        try:
            return datetime.fromisoformat(m["date"]).date()
        except Exception:
            return None

    today_date    = now.date()
    tomorrow_date = today_date + timedelta(days=1)

    # Prefer today's live/upcoming matches; fall back to tomorrow, then all future
    active_today = [m for m in unique if not m["finished"] and _match_date(m) == today_date]
    if active_today:
        result = active_today[:limit]
    else:
        tomorrow_matches = [m for m in unique if _match_date(m) == tomorrow_date]
        if tomorrow_matches:
            result = tomorrow_matches[:limit]
        else:
            future = [m for m in unique if not m["finished"]]
            result = (future or unique)[:limit]

    _mem_cache.update({"data": result, "ts": now})
    _save_disk(result)
    return result
