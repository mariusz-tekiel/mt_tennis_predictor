"""
Surface-specific Elo rating system for ATP tennis.

Each player has 5 Elo ratings:
  - overall   : all surfaces combined
  - hard, clay, grass, carpet : surface-specific

Combined surface Elo used for prediction:
  combined = OVERALL_WEIGHT * overall + SURFACE_WEIGHT * surface_specific

K-factor scales with tournament importance:
  Grand Slam (level='G') : 40
  Masters / 1000 (level='M') : 32
  everything else : 24

Win probability (classic Elo formula):
  P(A beats B) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from config import (
    ELO_INITIAL,
    ELO_K_GRAND_SLAM,
    ELO_K_MASTERS,
    ELO_K_STANDARD,
    ELO_OVERALL_WEIGHT,
    ELO_SURFACE_WEIGHT,
    SURFACES,
)

TOURNEY_K = {"G": ELO_K_GRAND_SLAM, "M": ELO_K_MASTERS}


@dataclass
class PlayerElo:
    overall: float = ELO_INITIAL
    hard: float = ELO_INITIAL
    clay: float = ELO_INITIAL
    grass: float = ELO_INITIAL
    carpet: float = ELO_INITIAL

    def get_surface(self, surface: str) -> float:
        return getattr(self, surface.lower(), self.hard)

    def set_surface(self, surface: str, value: float) -> None:
        setattr(self, surface.lower(), value)

    def combined(self, surface: str) -> float:
        """Blended Elo for a given surface."""
        return ELO_OVERALL_WEIGHT * self.overall + ELO_SURFACE_WEIGHT * self.get_surface(surface)

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall),
            "hard": round(self.hard),
            "clay": round(self.clay),
            "grass": round(self.grass),
            "carpet": round(self.carpet),
        }


def _k_factor(tourney_level: str) -> float:
    return TOURNEY_K.get(str(tourney_level).upper(), ELO_K_STANDARD)


def _expected(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def build_elo_ratings(matches: pd.DataFrame) -> dict[str, PlayerElo]:
    """
    Process matches chronologically and return final Elo ratings per player name.
    """
    ratings: dict[str, PlayerElo] = defaultdict(PlayerElo)

    for row in matches.itertuples(index=False):
        winner = row.winner_name
        loser = row.loser_name
        surface = str(row.surface)
        k = _k_factor(getattr(row, "tourney_level", "A"))

        wr = ratings[winner]
        lr = ratings[loser]

        # --- Overall Elo update ---
        e_w_overall = _expected(wr.overall, lr.overall)
        e_l_overall = 1.0 - e_w_overall
        wr.overall += k * (1.0 - e_w_overall)
        lr.overall += k * (0.0 - e_l_overall)

        # --- Surface-specific Elo update ---
        w_surf = wr.get_surface(surface)
        l_surf = lr.get_surface(surface)
        e_w_surf = _expected(w_surf, l_surf)
        e_l_surf = 1.0 - e_w_surf
        wr.set_surface(surface, w_surf + k * (1.0 - e_w_surf))
        lr.set_surface(surface, l_surf + k * (0.0 - e_l_surf))

        ratings[winner] = wr
        ratings[loser] = lr

    return dict(ratings)


def win_probability_from_elo(elo_a: PlayerElo, elo_b: PlayerElo, surface: str) -> float:
    """Return P(player A beats player B) based on combined Elo."""
    return _expected(elo_a.combined(surface), elo_b.combined(surface))
