from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Jeff Sackmann tennis_atp raw CSVs
SACKMANN_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
YEARS_TO_LOAD = list(range(2015, 2025))  # 2015–2024 (Sackmann repo)

# BALLDONTLIE ATP API
BALLDONTLIE_BASE = "https://api.balldontlie.io/atp/v1"
BALLDONTLIE_KEY = ""  # free key from balldontlie.io

# TheSportsDB
THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

# Elo parameters
ELO_INITIAL = 1500
ELO_K_GRAND_SLAM = 40
ELO_K_MASTERS = 32
ELO_K_STANDARD = 24

# Surface-specific Elo blend: overall_weight + surface_weight = 1
ELO_OVERALL_WEIGHT = 0.60
ELO_SURFACE_WEIGHT = 0.40

# Prediction weights (must sum to 1)
WEIGHT_ELO = 0.45
WEIGHT_FORM = 0.25
WEIGHT_SURFACE_WR = 0.20
WEIGHT_H2H = 0.10

# Form: exponential decay half-life in days
FORM_HALF_LIFE_DAYS = 90
FORM_LAST_N_MATCHES = 30

SURFACES = ["Hard", "Clay", "Grass", "Carpet"]
