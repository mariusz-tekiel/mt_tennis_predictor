"""
Computes per-player statistics from historical matches:
  - Recent form (exponential decay over last N matches)
  - Surface win rates
  - Head-to-head records
  - Serve stats (ace%, df%, 1st serve %, 1st won %, 2nd won %)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TypedDict

import numpy as np
import pandas as pd

from config import FORM_HALF_LIFE_DAYS, FORM_LAST_N_MATCHES, SURFACES


class PlayerStats(TypedDict):
    name: str
    matches_played: int
    current_rank: int
    # Elo ratings
    elo_overall: float
    elo_hard: float
    elo_clay: float
    elo_grass: float
    elo_carpet: float
    # Form
    form_score: float        # 0-1, recent weighted win rate
    form_last_n: list[int]   # 1=win, 0=loss, most-recent first
    # Surface win rates (last 3 years)
    wr_hard: float
    wr_clay: float
    wr_grass: float
    wr_carpet: float
    wr_overall: float
    # Serve stats
    ace_pct: float
    df_pct: float
    first_serve_in_pct: float
    first_serve_won_pct: float
    second_serve_won_pct: float


def _decay_weight(days_ago: float, half_life: float = FORM_HALF_LIFE_DAYS) -> float:
    return math.exp(-math.log(2) * days_ago / half_life)


def compute_form(player_name: str, matches: pd.DataFrame, as_of: datetime) -> tuple[float, list[int]]:
    """
    Returns (form_score 0-1, list of last N results) for a player.
    Matches must be sorted ascending by tourney_date.
    """
    mask = (matches["winner_name"] == player_name) | (matches["loser_name"] == player_name)
    player_matches = matches[mask].copy()
    player_matches = player_matches.sort_values("tourney_date", ascending=False).head(FORM_LAST_N_MATCHES)

    if player_matches.empty:
        return 0.5, []

    total_weight = 0.0
    win_weight = 0.0
    results: list[int] = []

    for row in player_matches.itertuples(index=False):
        days_ago = max(0, (as_of - row.tourney_date.to_pydatetime()).days)
        w = _decay_weight(days_ago)
        won = 1 if row.winner_name == player_name else 0
        results.append(won)
        win_weight += w * won
        total_weight += w

    form = win_weight / total_weight if total_weight > 0 else 0.5
    return round(form, 4), results


def compute_surface_wr(
    player_name: str, matches: pd.DataFrame, years_back: int = 3
) -> dict[str, float]:
    """Win rate per surface over the last `years_back` years."""
    cutoff = matches["tourney_date"].max() - pd.DateOffset(years=years_back)
    recent = matches[matches["tourney_date"] >= cutoff]
    mask = (recent["winner_name"] == player_name) | (recent["loser_name"] == player_name)
    player_matches = recent[mask]

    wr: dict[str, float] = {}
    for surface in SURFACES:
        surf_matches = player_matches[player_matches["surface"] == surface]
        if surf_matches.empty:
            wr[surface.lower()] = 0.5
            continue
        wins = (surf_matches["winner_name"] == player_name).sum()
        wr[surface.lower()] = round(wins / len(surf_matches), 4)

    total_matches = player_matches
    if len(total_matches) == 0:
        wr["overall"] = 0.5
    else:
        total_wins = (total_matches["winner_name"] == player_name).sum()
        wr["overall"] = round(total_wins / len(total_matches), 4)
    return wr


def compute_h2h(
    player1: str, player2: str, matches: pd.DataFrame
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """
    Returns (p1_wins, p2_wins, surface_breakdown).
    surface_breakdown: {surface: (p1_wins, p2_wins)}
    """
    mask = (
        ((matches["winner_name"] == player1) & (matches["loser_name"] == player2))
        | ((matches["winner_name"] == player2) & (matches["loser_name"] == player1))
    )
    h2h_matches = matches[mask]

    p1_wins = (h2h_matches["winner_name"] == player1).sum()
    p2_wins = (h2h_matches["winner_name"] == player2).sum()

    surface_breakdown: dict[str, tuple[int, int]] = {}
    for surface in SURFACES:
        sm = h2h_matches[h2h_matches["surface"] == surface]
        if sm.empty:
            continue
        s_p1 = int((sm["winner_name"] == player1).sum())
        s_p2 = int((sm["winner_name"] == player2).sum())
        surface_breakdown[surface] = (s_p1, s_p2)

    return int(p1_wins), int(p2_wins), surface_breakdown


def compute_serve_stats(player_name: str, matches: pd.DataFrame, last_n: int = 20) -> dict[str, float]:
    """Average serve stats over last `last_n` matches."""
    mask = (matches["winner_name"] == player_name) | (matches["loser_name"] == player_name)
    player_matches = matches[mask].sort_values("tourney_date", ascending=False).head(last_n)

    stats = {k: [] for k in ["ace", "df", "svpt", "first_in", "first_won", "second_won"]}

    for row in player_matches.itertuples(index=False):
        prefix = "w_" if row.winner_name == player_name else "l_"
        try:
            ace = float(getattr(row, f"{prefix}ace", 0) or 0)
            df = float(getattr(row, f"{prefix}df", 0) or 0)
            svpt = float(getattr(row, f"{prefix}svpt", 0) or 0)
            first_in = float(getattr(row, f"{prefix}1stIn", 0) or 0)
            first_won = float(getattr(row, f"{prefix}1stWon", 0) or 0)
            second_won = float(getattr(row, f"{prefix}2ndWon", 0) or 0)
            second_pts = svpt - first_in if svpt > first_in else 0

            if svpt > 0:
                stats["ace"].append(ace / svpt)
                stats["df"].append(df / svpt)
                stats["first_in"].append(first_in / svpt)
            if first_in > 0:
                stats["first_won"].append(first_won / first_in)
            if second_pts > 0:
                stats["second_won"].append(second_won / second_pts)
        except Exception:
            continue

    def avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 4) if lst else 0.0

    return {
        "ace_pct": avg(stats["ace"]),
        "df_pct": avg(stats["df"]),
        "first_serve_in_pct": avg(stats["first_in"]),
        "first_serve_won_pct": avg(stats["first_won"]),
        "second_serve_won_pct": avg(stats["second_won"]),
    }


def get_current_rank(player_name: str, matches: pd.DataFrame) -> int:
    """Return the most recent known ranking for a player."""
    mask_w = matches["winner_name"] == player_name
    mask_l = matches["loser_name"] == player_name

    last_w = matches[mask_w].sort_values("tourney_date").tail(1)
    last_l = matches[mask_l].sort_values("tourney_date").tail(1)

    rank_w = int(last_w["winner_rank"].iloc[0]) if not last_w.empty else 999
    rank_l = int(last_l["loser_rank"].iloc[0]) if not last_l.empty else 999

    # The more recent one wins
    if not last_w.empty and not last_l.empty:
        if last_w["tourney_date"].iloc[0] >= last_l["tourney_date"].iloc[0]:
            return rank_w
        else:
            return rank_l
    return min(rank_w, rank_l)
