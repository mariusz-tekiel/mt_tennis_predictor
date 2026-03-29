"""
Main prediction engine combining:
  1. Surface-specific Elo (45%)
  2. Recent form with exponential decay (25%)
  3. Surface win rate differential (20%)
  4. Head-to-head record (10%)

Win probability is computed in log-odds space (logistic regression analogy)
so adjustments are additive and the final probability stays in (0, 1).

Player composite score (0-100) is derived from the same components
and shown in the UI as a comparative strength indicator.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd

from config import (
    ELO_INITIAL,
    WEIGHT_ELO,
    WEIGHT_FORM,
    WEIGHT_H2H,
    WEIGHT_SURFACE_WR,
)
from models.elo import PlayerElo, build_elo_ratings, win_probability_from_elo
from models.stats import (
    compute_form,
    compute_h2h,
    compute_serve_stats,
    compute_surface_wr,
    get_current_rank,
)


def _logit(p: float) -> float:
    p = max(1e-9, min(1 - 1e-9, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class TennisPredictor:
    """
    One instance per application lifetime.
    Call `.initialize(matches_df)` once at startup.
    """

    def __init__(self) -> None:
        self._matches: pd.DataFrame | None = None
        self._elo_ratings: dict[str, PlayerElo] = {}
        self._player_names: list[str] = []
        self._ready = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def initialize(self, matches: pd.DataFrame) -> None:
        self._matches = matches
        self._elo_ratings = build_elo_ratings(matches)
        # Build sorted unique player list for autocomplete
        winners = set(matches["winner_name"].dropna().unique())
        losers = set(matches["loser_name"].dropna().unique())
        self._player_names = sorted(winners | losers)
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------
    # Player search
    # ------------------------------------------------------------------

    def search_players(self, query: str, limit: int = 20) -> list[str]:
        if not query or len(query) < 2:
            return []
        q = query.lower()
        return [n for n in self._player_names if q in n.lower()][:limit]

    # ------------------------------------------------------------------
    # Per-player stats (for UI display)
    # ------------------------------------------------------------------

    def player_profile(self, name: str) -> dict[str, Any]:
        assert self._ready and self._matches is not None
        as_of = self._matches["tourney_date"].max().to_pydatetime()

        elo = self._elo_ratings.get(name, PlayerElo())
        form_score, form_results = compute_form(name, self._matches, as_of)
        surface_wr = compute_surface_wr(name, self._matches)
        serve = compute_serve_stats(name, self._matches)
        rank = get_current_rank(name, self._matches)

        # Matches played total
        mask = (self._matches["winner_name"] == name) | (self._matches["loser_name"] == name)
        matches_played = int(mask.sum())

        return {
            "name": name,
            "current_rank": rank,
            "matches_played": matches_played,
            "elo": elo.to_dict(),
            "form_score": form_score,
            "form_last_n": form_results[:10],
            "surface_wr": surface_wr,
            **serve,
        }

    # ------------------------------------------------------------------
    # Core prediction
    # ------------------------------------------------------------------

    def predict(self, player1: str, player2: str, surface: str) -> dict[str, Any]:
        assert self._ready and self._matches is not None
        surface = surface.capitalize()
        as_of = self._matches["tourney_date"].max().to_pydatetime()

        elo1 = self._elo_ratings.get(player1, PlayerElo())
        elo2 = self._elo_ratings.get(player2, PlayerElo())

        # ---- 1. Elo component ----------------------------------------
        p_elo = win_probability_from_elo(elo1, elo2, surface)
        log_odds = _logit(p_elo)

        # ---- 2. Form component ----------------------------------------
        form1, form1_list = compute_form(player1, self._matches, as_of)
        form2, form2_list = compute_form(player2, self._matches, as_of)
        # Scale: form diff in [-1, 1], amplify by 1.2 in log-odds space
        form_adj = 1.2 * (form1 - form2)

        # ---- 3. Surface win rate component ---------------------------
        swr1 = compute_surface_wr(player1, self._matches)
        swr2 = compute_surface_wr(player2, self._matches)
        surf_key = surface.lower()
        swr_diff = swr1.get(surf_key, 0.5) - swr2.get(surf_key, 0.5)
        surf_adj = 1.0 * swr_diff  # ±1 in log-odds

        # ---- 4. H2H component ----------------------------------------
        p1_h2h, p2_h2h, h2h_surf = compute_h2h(player1, player2, self._matches)
        total_h2h = p1_h2h + p2_h2h
        if total_h2h >= 3:
            h2h_p = p1_h2h / total_h2h
            # Weight grows with number of H2H matches (caps at 0.6 logit units)
            h2h_weight = min(0.6, 0.15 * math.log1p(total_h2h))
            h2h_adj = h2h_weight * (h2h_p - 0.5) * 2  # scaled to [-weight, +weight]
        else:
            h2h_adj = 0.0

        # ---- Combine in log-odds space --------------------------------
        # Weighted blend: Elo already embedded in log_odds as base
        # Other components are additive adjustments with configured weights
        total_adj = (
            WEIGHT_FORM / (1 - WEIGHT_ELO) * form_adj
            + WEIGHT_SURFACE_WR / (1 - WEIGHT_ELO) * surf_adj
            + WEIGHT_H2H / (1 - WEIGHT_ELO) * h2h_adj
        )
        final_log_odds = log_odds + total_adj
        p1_win = _sigmoid(final_log_odds)
        p2_win = 1.0 - p1_win

        # ---- Composite player score (0-100) ---------------------------
        # Normalize Elo to 0-1 range (typical range ~1200-2200)
        def elo_norm(elo_val: float) -> float:
            return max(0.0, min(1.0, (elo_val - 1200) / 800))

        def player_score(elo: PlayerElo, form: float, swr: dict, rank: int) -> float:
            e = elo_norm(elo.combined(surface))
            rank_factor = max(0.0, min(1.0, 1.0 - (rank - 1) / 200))
            raw = (
                WEIGHT_ELO * e
                + WEIGHT_FORM * form
                + WEIGHT_SURFACE_WR * swr.get(surf_key, 0.5)
                + WEIGHT_H2H * 0.5  # neutral H2H contribution in solo score
                + 0.05 * rank_factor  # small rank bonus
            )
            return round(raw * 100, 1)

        rank1 = get_current_rank(player1, self._matches)
        rank2 = get_current_rank(player2, self._matches)

        score1 = player_score(elo1, form1, swr1, rank1)
        score2 = player_score(elo2, form2, swr2, rank2)

        serve1 = compute_serve_stats(player1, self._matches)
        serve2 = compute_serve_stats(player2, self._matches)

        # H2H on the chosen surface
        surf_h2h = h2h_surf.get(surface, (0, 0))

        return {
            "player1": {
                "name": player1,
                "win_pct": round(p1_win * 100, 1),
                "score": score1,
                "rank": rank1,
                "elo": elo1.to_dict(),
                "form_score": round(form1 * 100, 1),
                "form_last_10": form1_list[:10],
                "surface_wr": {k: round(v * 100, 1) for k, v in swr1.items()},
                "h2h_wins": p1_h2h,
                "h2h_wins_surface": surf_h2h[0],
                **serve1,
            },
            "player2": {
                "name": player2,
                "win_pct": round(p2_win * 100, 1),
                "score": score2,
                "rank": rank2,
                "elo": elo2.to_dict(),
                "form_score": round(form2 * 100, 1),
                "form_last_10": form2_list[:10],
                "surface_wr": {k: round(v * 100, 1) for k, v in swr2.items()},
                "h2h_wins": p2_h2h,
                "h2h_wins_surface": surf_h2h[1],
                **serve2,
            },
            "surface": surface,
            "h2h_total": total_h2h,
            "h2h_surface_total": surf_h2h[0] + surf_h2h[1],
            "method": "Surface-Elo + Form + SurfaceWR + H2H (log-odds blend)",
        }
