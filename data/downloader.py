"""
Downloads and caches Jeff Sackmann's tennis_atp CSV data from GitHub.
Provides one merged DataFrame of all historical ATP matches.
"""
import asyncio
import logging
from pathlib import Path

import httpx
import pandas as pd

from config import DATA_DIR, SACKMANN_BASE, YEARS_TO_LOAD

logger = logging.getLogger(__name__)

REQUIRED_COLS = [
    "tourney_date", "tourney_name", "surface", "tourney_level",
    "winner_id", "winner_name", "winner_rank", "winner_rank_points",
    "loser_id", "loser_name", "loser_rank", "loser_rank_points",
    "score", "best_of", "round", "minutes",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon",
    "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon",
    "l_bpSaved", "l_bpFaced",
]


async def _download_year(client: httpx.AsyncClient, year: int) -> pd.DataFrame | None:
    url = f"{SACKMANN_BASE}/atp_matches_{year}.csv"
    cache_path = DATA_DIR / f"atp_matches_{year}.csv"

    if cache_path.exists():
        try:
            return pd.read_csv(cache_path, low_memory=False)
        except Exception:
            cache_path.unlink(missing_ok=True)

    try:
        logger.info(f"Downloading {year}...")
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)
        return pd.read_csv(cache_path, low_memory=False)
    except Exception as e:
        logger.warning(f"Failed to download {year}: {e}")
        return None


async def load_all_matches() -> pd.DataFrame:
    """Return merged DataFrame of all ATP matches across configured years."""
    async with httpx.AsyncClient() as client:
        tasks = [_download_year(client, y) for y in YEARS_TO_LOAD]
        frames = await asyncio.gather(*tasks)

    valid = [df for df in frames if df is not None and not df.empty]
    if not valid:
        raise RuntimeError("No match data could be loaded.")

    combined = pd.concat(valid, ignore_index=True)

    # Normalise surface names
    combined["surface"] = combined["surface"].str.strip().str.capitalize()
    surface_map = {"Hard": "Hard", "Clay": "Clay", "Grass": "Grass", "Carpet": "Carpet"}
    combined["surface"] = combined["surface"].map(surface_map).fillna("Hard")

    # Parse date
    combined["tourney_date"] = pd.to_datetime(
        combined["tourney_date"].astype(str), format="%Y%m%d", errors="coerce"
    )
    combined = combined.dropna(subset=["tourney_date"])
    combined = combined.sort_values("tourney_date").reset_index(drop=True)

    # Fill missing rank with a high number (unranked)
    combined["winner_rank"] = pd.to_numeric(combined["winner_rank"], errors="coerce").fillna(500)
    combined["loser_rank"] = pd.to_numeric(combined["loser_rank"], errors="coerce").fillna(500)
    combined["winner_rank_points"] = pd.to_numeric(
        combined["winner_rank_points"], errors="coerce"
    ).fillna(0)
    combined["loser_rank_points"] = pd.to_numeric(
        combined["loser_rank_points"], errors="coerce"
    ).fillna(0)

    logger.info(f"Loaded {len(combined):,} matches ({YEARS_TO_LOAD[0]}-{YEARS_TO_LOAD[-1]})")
    return combined


def load_all_matches_sync() -> pd.DataFrame:
    return asyncio.run(load_all_matches())
