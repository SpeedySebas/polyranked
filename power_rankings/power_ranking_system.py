#!/usr/bin/env python3
"""PolyTrack Global Player Power Ranking System (v10.2 Pure Leaderboard Architecture).

Unified mathematically rigorous Player Skill Rating & Power Ranking System
for PolyTrack, bridging across 17 Main Tracks and 61 Community Tracks (78 total).

Architectural Highlights (v10.2):
1. Pure Dual-Tier Leaderboard Evaluation:
   - Decommissions Plackett-Luce / ELO from GSI composite calculation.
   - Eliminates structural selection bias and volume distortion in time-attack racing.
   - Full-window normalization zero-pads unplayed depth slots without upward Bayesian inflation.
2. Dynamic Strength-of-Field (SoF) Track Difficulty (omega_k):
   - omega_k = clamp(1.0 + 0.18 * log10(N_k / 100,000), 0.65, 1.85).
3. Smooth Logarithmic Rank Scoring & 1.25x WR Crown:
   - R(Rank) = 1 / (1 + 0.6 * ln(Rank))
   - S_{i,k} = omega_k * 100.0 * R(Rank_{i,k}) * (1.25 if Rank==1 else 1.00)
4. Engine 1: Peak Quality Index (PQI - Top-6 Mechanical Ceiling):
   - PQI = [sum_{r=1}^{min(6, m)} (0.85)^(r-1) * S_{(r)}] / [sum_{r=1}^6 (0.85)^(r-1)].
5. Engine 2: Versatility & Depth Index (VDI - Top-15 Sustained Quality):
   - VDI = [sum_{r=1}^{min(15, m)} (0.90)^(r-1) * S_{(r)}] / [sum_{r=1}^15 (0.90)^(r-1)].
6. Engine 3: Global Skill Index (GSI v10.2 Composite):
   - GSI = 1000 + 200 * (0.70 * Z_pqi + 0.30 * Z_vdi).
"""

import argparse
import asyncio
import csv
import json
import math
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
import numpy as np

# Optional output redirector if present in workspace
try:
    import output_redirector
except ImportError:
    pass

# =====================================================================
# Alt Account Mappings (Player Identity Consolidation)
# =====================================================================
# Maps alternative account identifiers (case-insensitive nicknames or exact
# 64-character userIds) to their canonical primary player identity.
# On each track leaderboard:
# - All entries belonging to the same player are consolidated.
# - Only the fastest time on that track is retained and credited to the main account.
# - Duplicate entries are eliminated, and ranks for all competitors are dense-reindexed (1, 2, 3...).
ALT_MAPPINGS: Dict[str, str] = {
    # youngfella alts
    "youngfella": "youngfella",
    "yf savestate": "youngfella",
    "aidrian simon": "youngfella",
    "aidrian": "youngfella",
    "aidriansimon": "youngfella",
    "yfsavestate": "youngfella",
    "aidrian simon yf": "youngfella",
    "aidrian yf": "youngfella",
    # SpeedySebas
    "speedysebas": "SpeedySebas",
    "speedy sebas": "SpeedySebas",
    "speedy": "SpeedySebas",
    # cheesebob (81)
    "cheesebob (81)": "cheesebob (81)",
    "cheesebob": "cheesebob (81)",
    "cheesebob81": "cheesebob (81)",
    # The5andOnly ;(
    "the5andonly ;(": "The5andOnly ;(",
    "the5andonly": "The5andOnly ;(",
    "the 5 and only": "The5andOnly ;(",
    # Monstrosity
    "monstrosity": "Monstrosity",
    "monstrosity yt": "Monstrosity",
    # LanceB_YT
    "lanceb_yt": "LanceB_YT 🍃🌿",
    "lanceb_yt 🍃🌿": "LanceB_YT 🍃🌿",
    "lanceb": "LanceB_YT 🍃🌿",
    # xtuov
    "xtuov": "xtuov",
    "xtuov_": "xtuov",
    # hwadz
    "hwadz": "hwadz",
    "hwadz on app.asar": "hwadz",
    # Tvirty
    "tvirty": "Tvirty",
    "tvirty_": "Tvirty",
    # Kiki alts (merging |<iki and unicode stylizations into Rank 8 Kiki)
    "|<iki": "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı",
    "kiki": "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı",
    "ıllıllı 𝐤𝐢𝐤𝐢 ıllıllı": "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı",
    "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı": "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı",
    "illilli kiki illilli": "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı",
    # HK Wak3son HK
    "hk wak3son hk": "HK 🦈 Wak3son 🦈 HK",
    "hk 🦈 wak3son 🦈 hk": "HK 🦈 Wak3son 🦈 HK",
    "wak3son": "HK 🦈 Wak3son 🦈 HK",
    "wak3son hk": "HK 🦈 Wak3son 🦈 HK"
}

# =====================================================================
# Blacklisted Players (Banned / Cheated Run Disqualification)
# =====================================================================
# Players who are entirely discounted from the rankings due to cheated runs.
# Any run by a blacklisted player (matched by case-insensitive nickname or exact
# 64-character userId) is eliminated from each track leaderboard BEFORE
# rankings or scores are computed.
# Dense ranks on every track are automatically adjusted (1, 2, 3...) so that
# legitimate players move up to their rightful positions before their ranks
# are inputted into the PQI, VDI, and GSI formulas.
BLACKLISTED_PLAYERS: Set[str] = {
    "BadPlanet 𝄂𝄚𝅦𝄚 𝄞",
    "clipradar.net",
    # Ben (disqualified for cheated runs on 2026-09-13)
    "Ben",
    "09f0741c8e7e793380c6dee978ec3dae563f891c5d5832497efdfb709cbf92a2",
}


def normalize_identity_key(name_or_id: str) -> str:
    """Normalize username or userId for case-insensitive, whitespace-agnostic matching."""
    if not name_or_id:
        return ""
    normalized = unicodedata.normalize("NFKC", str(name_or_id)).lower()
    return re.sub(r"\s+", " ", normalized).strip()


_NORM_ALT_MAPPINGS: Dict[str, str] = {normalize_identity_key(k): v for k, v in ALT_MAPPINGS.items()}
_NORM_BLACKLISTED_PLAYERS: Set[str] = {normalize_identity_key(k) for k in BLACKLISTED_PLAYERS}


def is_player_blacklisted(
    nickname: str = "",
    user_id: str = "",
    canonical_key: Optional[str] = None,
    canonical_nick: Optional[str] = None,
    blacklisted_players: Optional[Set[str]] = None
) -> bool:
    """Check if a player or run is blacklisted by nickname, userId, or canonical identity."""
    if blacklisted_players is None or blacklisted_players is BLACKLISTED_PLAYERS:
        norm_blacklist = _NORM_BLACKLISTED_PLAYERS
    else:
        norm_blacklist = {normalize_identity_key(k) for k in blacklisted_players}

    if not norm_blacklist:
        return False

    nick_norm = normalize_identity_key(nickname)
    if nick_norm and nick_norm in norm_blacklist:
        return True

    uid_norm = normalize_identity_key(user_id)
    if uid_norm and uid_norm in norm_blacklist:
        return True

    if canonical_key:
        ck_norm = normalize_identity_key(canonical_key)
        if ck_norm and ck_norm in norm_blacklist:
            return True

    if canonical_nick:
        cn_norm = normalize_identity_key(canonical_nick)
        if cn_norm and cn_norm in norm_blacklist:
            return True

    return False


def resolve_canonical_player(nickname: str, user_id: str, alt_mappings: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """Resolve an entry's canonical identity key and display name via alt account mappings."""
    if alt_mappings is None or alt_mappings is ALT_MAPPINGS:
        norm_mappings = _NORM_ALT_MAPPINGS
    else:
        norm_mappings = {normalize_identity_key(k): v for k, v in alt_mappings.items()}

    nick_clean = str(nickname or "").strip()
    uid_clean = str(user_id or "").strip()

    nick_norm = normalize_identity_key(nick_clean)
    uid_norm = normalize_identity_key(uid_clean)

    # 1. Match by userId
    if uid_norm and uid_norm in norm_mappings:
        canonical_name = norm_mappings[uid_norm]
        return normalize_identity_key(canonical_name), canonical_name

    # 2. Match by nickname
    if nick_norm in norm_mappings:
        canonical_name = norm_mappings[nick_norm]
        return normalize_identity_key(canonical_name), canonical_name

    # 3. Default fallback: unique per userId if present, else nickname
    if uid_clean:
        return uid_norm, nick_clean
    return nick_norm, nick_clean


# Alias for backward compatibility
resolve_player_identity = resolve_canonical_player


# =====================================================================
# Constants & Configuration
# =====================================================================

BASE_URL = "https://vps.kodub.com/v6/leaderboard"
API_VERSION = "0.6.2"
# Public leaderboard reads work without a player account token.
USER_TOKEN_HASH = os.environ.get("POLYTRACK_USER_TOKEN_HASH", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://app-polytrack.kodub.com",
    "Referer": "https://app-polytrack.kodub.com/"
}

# 17 Official Main Tracks
MAIN_TRACKS: Dict[str, str] = {
    "Summer 1": "5803f9e963625804e3de3246d043dc7dde847aa32e991f7f7326b0453f1fa038",
    "Summer 2": "7eac4fee1111152cfba4d3737410264ca0f22c7f5a2211e79f0099589b8b48c0",
    "Summer 3": "148826aa16ffaa23dbc453b32cff05e025ddbce1773fc7733cc13d218926515a",
    "Summer 4": "93c7363dfea7fb09ca1d23b72cad5df43a30841d41c8ff25fb544c85bb03c7ae",
    "Summer 5": "7603aaeffa1989a649dfaa8e1804bed4481b49df233e377687d0669899566e52",
    "Summer 6": "c117823cf6788e3247b9ee63a0c091c07352bbe352c650a7790dc6718148c2fa",
    "Summer 7": "e4bcaca3a583bb0eb62a700a69d14e89c852f0c5bf740fca76e0519ebdfc9ab1",
    "Winter 1": "7239b17057127936907a805b0caa5d8c6f6c97eca9bdabf1a5312dce479629b7",
    "Winter 2": "99864b635d1891d22e17eb9267527a07a92c49c0f02893729fa2ded90e3ca0f9",
    "Winter 3": "a5341fe706097cff2a3812a3fc0d87399254557328351ae8e5c882700fc1a196",
    "Winter 4": "7d134c939df80c676a258266201beedd3b93572d5603f3ff4339ff8679803715",
    "Winter 5": "2fe4bd46b0075cc25fc770ce50adbb68447cf493c999635bb272d231811dd264",
    "Desert 1": "c20b4ee3cd517ca6cae7e43f047548757287fbd08ba81b97892a3ef520159a34",
    "Desert 2": "88647ea04145fbbbb19b55f1590e038fb0378acb2571110f02cb545cc46b0d57",
    "Desert 3": "2806030c503abb41a1a26fa9a570888be14296172bb273798ef0ad87a108a2ec",
    "Desert 4": "4697ea67b18c3f49b30a3d8884602115536650bc5435c88e3732e64d21a72d33",
    "Desert 5": "e5d084e06db4ab71196fea44efeceb23c8561266a78669c324a38f92581fe2db"
}

# Dynamic Strength-of-Field (SoF) Parameters
SOF_BASE_POP = 100000.0      # Population benchmark (100,000 players)
SOF_LOG_SLOPE = 0.18         # Scaling coefficient
OMEGA_MIN = 0.65             # Clamping floor
OMEGA_MAX = 1.85             # Clamping ceiling

# Smooth Logarithmic Rank Scoring Parameters
RANK_LOG_COEFF = 0.60        # Coefficient in 1 / (1 + 0.6 * ln(Rank))
WR_CROWN_MULTIPLIER = 1.25   # World Record Crown boost

# Engine 1: Peak Quality Index (PQI - Top-6 Mechanical Ceiling)
# Engine 1: Peak Quality Index (PQI - Top-6 Mechanical Ceiling)
PQI_TOP_K = 6                # Evaluate Top 6 best tracks per player
PQI_GAMMA = 0.85             # Geometric weight factor across Top 6 (0.85^(r-1))

# Engine 2: Versatility & Depth Index (VDI - Top-15 Sustained Quality)
VDI_TOP_K = 15               # Evaluate Top 15 best tracks per player
VDI_GAMMA = 0.90             # Geometric weight factor across Top 15 (0.90^(r-1))

# Active Competitor Threshold
ACTIVE_MIN_TRACKS_DEFAULT = 5 # Minimum tracks for established competitor status

# Engine 3: Global Skill Index (GSI v10.2) Constants
GSI_BASE = 1000.0
GSI_SCALE = 200.0
GSI_WEIGHT_PQI = 0.70        # 70% Peak Ceiling
GSI_WEIGHT_VDI = 0.30        # 30% Sustained Versatility

# 2-Domain Macro-Discipline Engine (v10.2 Dual-Axis Mastery)
DISCIPLINE_DOMAINS: List[str] = [
    "Fullspeed",
    "Technical"
]
DISCIPLINE_TOP_K = 6          # Evaluate Top 6 best tracks per domain (K = 6)
DISCIPLINE_GAMMA = 0.85       # Harmonic decay across Top 6 (0.85^(r-1))

SUBGENRES: List[str] = [
    "FS",
    "Fakespeed",
    "Tech",
    "Speedtech",
    "Speedfun"
]

# Backward compatibility alias
ALL_TRACK_STYLES = DISCIPLINE_DOMAINS


# =====================================================================
# Utilities & Scoring Formulas
# =====================================================================

def ascii_safe(text: str) -> str:
    """Return an ASCII-safe representation of text."""
    return text.encode("ascii", "ignore").decode("ascii")


def calculate_dynamic_track_weight(
    n_k: int,
    base_pop: float = SOF_BASE_POP,
    slope: float = SOF_LOG_SLOPE,
    omega_min: float = OMEGA_MIN,
    omega_max: float = OMEGA_MAX
) -> float:
    """Calculate Dynamic Track Weight from player count:

    omega_k = clamp(1.0 + 0.18 * log10(N_k / 100,000), 0.65, 1.85)
    """
    pop = max(1, n_k)
    raw_weight = 1.0 + slope * math.log10(pop / base_pop)
    clamped = max(omega_min, min(omega_max, raw_weight))
    return round(clamped, 4)


def calculate_smooth_track_score(
    rank: int,
    weight: float,
    log_coeff: float = RANK_LOG_COEFF,
    wr_crown: float = WR_CROWN_MULTIPLIER
) -> float:
    """Compute smooth logarithmic rank score with WR crown:

    R(Rank) = 1 / (1 + 0.6 * ln(Rank))
    S = omega_k * 100.0 * R(Rank) * (1.25 if Rank == 1 else 1.00)
    """
    if rank < 1:
        return 0.0
    r_factor = 1.0 / (1.0 + log_coeff * math.log(rank))
    crown = wr_crown if rank == 1 else 1.00
    return weight * 100.0 * r_factor * crown


def calculate_discipline_rating(
    domain_scores: List[float],
    top_k: int = DISCIPLINE_TOP_K,
    gamma: float = DISCIPLINE_GAMMA
) -> Tuple[float, float, int]:
    """Compute Discipline Rating for a player in a macro-discipline (v10.2 Dual-Axis Mastery).

    1. Full-Window Discipline Rating across Top 6 window (K = 6, gamma = 0.85):
       Rating(i, D) = [sum_{r=1}^{min(6, m)} (0.85)^(r-1) * S_{(r)}] / [sum_{r=1}^6 (0.85)^(r-1)]
    2. Raw Intensity across driven runs:
       Raw Score(i, D) = [sum_{r=1}^{min(6, m)} (0.85)^(r-1) * S_{(r)}] / [sum_{r=1}^{min(6, m)} (0.85)^(r-1)]

    Returns:
       Tuple[discipline_rating, raw_discipline_score, n_eff]
       (If player has 0 runs in domain D, rating = 0.0 and marked unranked).
    """
    if not domain_scores:
        return 0.0, 0.0, 0

    sorted_scores = sorted(domain_scores, reverse=True)
    top_scores = sorted_scores[:top_k]
    n_eff = len(top_scores)

    if n_eff == 0:
        return 0.0, 0.0, 0

    w_full = sum(gamma ** r for r in range(top_k))
    weights = [gamma ** r for r in range(n_eff)]
    sum_w = sum(weights)
    weighted_sum = sum(w * s for w, s in zip(weights, top_scores))

    raw_score = weighted_sum / sum_w if sum_w > 0 else 0.0
    rating = weighted_sum / w_full if w_full > 0 else 0.0
    return round(rating, 4), round(raw_score, 4), n_eff


# Alias for backward compatibility
calculate_style_pqi = calculate_discipline_rating


def calculate_discipline_bias(rating_fs: float, rating_tech: float) -> float:
    """Compute Discipline Bias Ratio:

    Bias(i) = Rating(i, Fullspeed) / (Rating(i, Fullspeed) + Rating(i, Technical))
    Defaults to 0.50 if both ratings are 0.
    """
    total = rating_fs + rating_tech
    if total <= 0.0:
        return 0.50
    return round(rating_fs / total, 4)


def determine_discipline_archetype(
    bias: float,
    count_fs: int,
    count_tech: int,
    total_tracks_driven: int = 0
) -> str:
    """Determine player's driving archetype based on Discipline Bias Ratio and track counts.

    - Fullspeed Specialist: Bias >= 0.70 and >= 4 Fullspeed tracks driven.
    - Technical Specialist: Bias <= 0.30 and >= 4 Technical tracks driven.
    - Generalist: 0.30 < Bias < 0.70 and >= 4 tracks driven in both domains.
    - Player: Default classification for profiles with fewer than 4 tracks per domain.
    """
    if total_tracks_driven == 0 and (count_fs == 0 and count_tech == 0):
        return "Player"

    if bias >= 0.70 and count_fs >= 4:
        return "Fullspeed Specialist"
    elif bias <= 0.30 and count_tech >= 4:
        return "Technical Specialist"
    elif (0.30 < bias < 0.70) and count_fs >= 4 and count_tech >= 4:
        return "Generalist"
    else:
        return "Player"


# Alias for backward compatibility
def determine_driving_archetype(style_pqi_map: Dict[str, float], style_counts_map: Dict[str, int], total_tracks_driven: int) -> str:
    fs_pqi = style_pqi_map.get("Fullspeed", 0.0)
    tech_pqi = style_pqi_map.get("Technical", 0.0)
    fs_cnt = style_counts_map.get("Fullspeed", 0)
    tech_cnt = style_counts_map.get("Technical", 0)
    bias = calculate_discipline_bias(fs_pqi, tech_pqi)
    return determine_discipline_archetype(bias, fs_cnt, tech_cnt, total_tracks_driven)


def map_track_to_domain_and_subgenre(track_name: str, raw_style: str) -> Tuple[str, str]:
    """Map any track name and raw style string to (domain, subgenre).

    Corrected Mappings:
    1. Fullspeed Discipline:
       - Fullspeed (FS)
       - Fakespeed
       - Last Remnant (mapped to Fullspeed discipline, subgenre FS)
       - Apostle (mapped to Fullspeed discipline, subgenre FS)
       - Launch Control (mapped to Fullspeed discipline, subgenre FS)
    2. Technical Discipline:
       - Tech
       - Speedtech
       - Speedfun
       - ShardMir (mapped to Technical discipline, subgenre Tech)
    """
    t_clean = track_name.strip()
    s_clean = raw_style.strip()

    # Explicit track-specific overrides
    if t_clean == "Last Remnant":
        return "Fullspeed", "FS"
    if t_clean == "ShardMir":
        return "Technical", "Tech"
    if t_clean == "Apostle":
        return "Fullspeed", "FS"
    if t_clean in ("Launch Control", "Launch Controll", "Lauch Controll", "Lauch Control"):
        return "Fullspeed", "FS"
    if t_clean == "Flying Dreams":
        return "Technical", "Speedfun"
    if t_clean in ("Lu Muvimento", "lu muvimento", "Lu Muvimiento", "lu muvimiento"):
        return "Fullspeed", "FS"

    # Sub-genre matching
    s_lower = s_clean.lower()
    if "fakespeed" in s_lower:
        return "Fullspeed", "Fakespeed"
    elif "fullspeed" in s_lower or s_clean == "FS":
        return "Fullspeed", "FS"
    elif "speedtech" in s_lower:
        return "Technical", "Speedtech"
    elif "speedfun" in s_lower:
        return "Technical", "Speedfun"
    elif "tech" in s_lower:
        return "Technical", "Tech"
    elif "rpg" in s_lower:
        # Fallback for RPG
        if t_clean == "Last Remnant":
            return "Fullspeed", "FS"
        return "Technical", "Tech"

    # Default fallback
    return "Fullspeed", "FS"


# =====================================================================
# Engine 4: GSI Optimization Strategy & Target Advisor Architecture (v11.0 Modular ROI Model)
# =====================================================================

# Configurable Evidence / Confidence Adjustment Factors (Fixed Heuristic Conservatism)
CONFIDENCE_FACTOR_HIGH = 0.90     # Tightly clustered placements / proven track record
CONFIDENCE_FACTOR_MEDIUM = 0.60   # Moderate cross-track dispersion or moderate volume
CONFIDENCE_FACTOR_LOW = 0.30      # High dispersion / sparse track volume

# Effort Model Constants
FRONTIER_PENALTY_COEFF = 1.20     # Universal rank frontier penalty: 1.20 / sqrt(Rank)
UNPLAYED_ENTRY_EFFORT = 1.00      # Learning / exploration baseline cost for unplayed tracks
UPGRADE_ENTRY_EFFORT = 0.50       # Setup baseline cost for upgrading an existing track

# Precomputed weights for fast closed-form PQI / VDI evaluation
_PQI_WEIGHTS = [PQI_GAMMA ** r for r in range(PQI_TOP_K)]
_VDI_WEIGHTS = [VDI_GAMMA ** r for r in range(VDI_TOP_K)]
_W_FULL_PQI = sum(_PQI_WEIGHTS)
_W_FULL_VDI = sum(_VDI_WEIGHTS)


def calculate_normalized_skill_intensity(
    player_scores_map: Dict[str, float],
    all_tracks_dict: Dict[str, Dict[str, Any]]
) -> float:
    """Compute player's Informational Skill Scoring Standard (S*):
    S* = 0.40 * PQI + 0.60 * VDI
    Used exclusively as an informational benchmark / theoretical capacity indicator.
    """
    if not player_scores_map:
        return 0.0
    scores = [s for s in player_scores_map.values() if s > 0]
    if not scores:
        return 0.0
    scores.sort(reverse=True)
    pqi = sum(w * s for w, s in zip(_PQI_WEIGHTS, scores[:PQI_TOP_K])) / _W_FULL_PQI
    vdi = sum(w * s for w, s in zip(_VDI_WEIGHTS, scores[:VDI_TOP_K])) / _W_FULL_VDI
    return round(0.40 * pqi + 0.60 * vdi, 4)


def calculate_blended_skill_capability(pqi: float, vdi: float) -> float:
    """Informational skill standard benchmark: 0.40 * PQI + 0.60 * VDI."""
    return round(0.40 * pqi + 0.60 * vdi, 4)


def calculate_projected_track_score(r_target: int, omega_k: float) -> float:
    """Calculate Final Projected Track Score (S_{proj}):
    S_{proj}(i, k) = omega_k * 100.0 * (1 / (1 + 0.6 * ln(R_{target}))) * (1.25 if R_{target} == 1 else 1.00)
    """
    return calculate_smooth_track_score(r_target, omega_k)


def format_target_objective(r_target: int) -> str:
    """Format Target Objective display string:
    - R == 1: 🥇 Rank 1 (WR)
    - R == 2: 🥈 Rank 2 (Podium)
    - R == 3: 🥉 Rank 3 (Podium)
    - R in [4, 5]: 🎯 Top 5 (Rank {R})
    - R <= 10: 🏁 Top 10 (Rank {R})
    - R > 10: 🏁 Rank {R}
    """
    if r_target == 1:
        return "🥇 Rank 1 (WR)"
    elif r_target == 2:
        return "🥈 Rank 2 (Podium)"
    elif r_target == 3:
        return "🥉 Rank 3 (Podium)"
    elif r_target <= 5:
        return f"🎯 Top 5 (Rank {r_target})"
    elif r_target <= 10:
        return f"🏁 Top 10 (Rank {r_target})"
    else:
        return f"🏁 Rank {r_target}"


def calculate_player_baseline(
    player_scores_map: Dict[str, float],
    player_ranks_map: Dict[str, int],
    all_tracks_dict: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Compute player's demonstrated global standing prior for unplayed tracks.
    Returns:
    - median_rank: Median finishing rank across driven tracks (bounded >= 2)
    - median_intensity: Median normalized score intensity (S / omega) across driven tracks
    - driven_count: Total number of driven tracks
    """
    driven_ranks = [r for r in player_ranks_map.values() if r is not None and r > 0]
    intensities = []
    for tr_name, score in player_scores_map.items():
        if score > 0:
            w = all_tracks_dict.get(tr_name, {}).get("dynamic_weight", 1.0)
            intensities.append(score / max(1e-6, w))

    if not driven_ranks:
        return {
            "median_rank": 500,
            "median_intensity": 20.0,
            "driven_count": 0
        }

    med_rank = int(round(float(np.median(driven_ranks))))
    med_intensity = float(np.median(intensities)) if intensities else 20.0

    return {
        "median_rank": max(2, med_rank),
        "median_intensity": max(5.0, med_intensity),
        "driven_count": len(driven_ranks)
    }


def calculate_cross_track_consistency(
    player_scores_map: Dict[str, float],
    all_tracks_dict: Dict[str, Dict[str, Any]]
) -> float:
    """Compute player's cross-track placement dispersion via Coefficient of Variation (CV)
    of score intensities (S_j / omega_j).
    Lower CV indicates tightly clustered competitive placements (high consistency).
    """
    intensities = []
    for tr_name, score in player_scores_map.items():
        if score > 0:
            w = all_tracks_dict.get(tr_name, {}).get("dynamic_weight", 1.0)
            intensities.append(score / max(1e-6, w))

    if len(intensities) < 2:
        return 1.0  # High default dispersion for sparse data

    mean_val = float(np.mean(intensities))
    std_val = float(np.std(intensities))
    if mean_val <= 1e-6:
        return 1.0
    return round(std_val / mean_val, 4)


def determine_confidence_tier(
    is_unplayed: bool,
    consistency_cv: float,
    driven_count: int
) -> Tuple[str, float]:
    """Determine qualitative evidence confidence tier and fixed conservatism factor.
    Note: These are heuristic conservatism adjustments, NOT calibrated probabilities.
    - High: 0.90 factor
    - Medium: 0.60 factor
    - Low: 0.30 factor
    """
    if not is_unplayed:
        # Played track: Direct empirical track-specific evidence exists
        if driven_count >= 3 and consistency_cv <= 0.45:
            return "High", CONFIDENCE_FACTOR_HIGH
        return "Medium", CONFIDENCE_FACTOR_MEDIUM

    # Unplayed track: Prior depends on cross-track consistency and breadth
    if driven_count >= 8 and consistency_cv <= 0.25:
        return "High", CONFIDENCE_FACTOR_HIGH
    elif driven_count >= 4 and consistency_cv <= 0.50:
        return "Medium", CONFIDENCE_FACTOR_MEDIUM
    else:
        return "Low", CONFIDENCE_FACTOR_LOW


def calculate_effort(
    baseline_rank: int,
    target_rank: int,
    omega_k: float,
    is_unplayed: bool
) -> float:
    """Calculate effort cost:
    Effort = Base Entry Cost + (Player-relative rank advancement * Bounded SoF Adjustment) + Universal Frontier Penalty

    1. Player-relative rank advancement: ln(max(1.0, baseline_rank / target_rank))
    2. Bounded SoF Adjustment: 1.0 + 0.40 * (omega_k - 1.0), clamped to [0.75, 1.35]
    3. Universal Frontier Penalty: 1.20 / sqrt(target_rank)
    """
    start_rank = max(1, baseline_rank)
    tgt_rank = max(1, target_rank)

    # 1. Player rank advancement ratio
    advancement_ratio = max(1.0, float(start_rank) / float(tgt_rank))
    advancement_term = math.log(advancement_ratio)

    # 2. Bounded track Strength-of-Field environmental modifier
    sof_modifier = max(0.75, min(1.35, 1.0 + 0.40 * (omega_k - 1.0)))

    # 3. Universal frontier penalty near leaderboard front
    frontier_penalty = FRONTIER_PENALTY_COEFF / math.sqrt(tgt_rank)

    # 4. Entry base cost
    entry_cost = UNPLAYED_ENTRY_EFFORT if is_unplayed else UPGRADE_ENTRY_EFFORT

    effort = entry_cost + (advancement_term * sof_modifier) + frontier_penalty
    return round(max(0.50, effort), 4)


def generate_candidate_target_ladder(
    track_name: str,
    curr_rank: Optional[int],
    baseline_rank: int,
    omega_k: float,
    s6_cutoff: float = 0.0,
    s15_cutoff: float = 0.0
) -> List[int]:
    """Generate a dense candidate ladder of potential target ranks for track k.
    Includes:
    - Milestone ranks (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300, 500, 1000)
    - Cutoff-crossing target ranks for Top 6 (PQI) and Top 15 (VDI) windows
    - Player-relative advancement steps (e.g. 0.85x, 0.70x, 0.50x, 0.35x, 0.20x, 0.10x)
    """
    candidates: Set[int] = set()

    # 1. Milestone & Frontier Targets
    milestones = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 17, 20, 23, 25, 30, 35, 40, 50, 75, 100, 150, 200, 300, 500, 1000]
    for m in milestones:
        candidates.add(m)

    # 2. Cutoff-Crossing Targets
    for cutoff in [s6_cutoff, s15_cutoff]:
        if cutoff > 0:
            # Invert track score formula to find exact rank required to exceed cutoff
            target_score_needed = cutoff + 0.1
            ratio = (100.0 * omega_k) / max(1e-6, target_score_needed)
            if ratio <= 1.0:
                r_cut = 1
            else:
                exp_val = (ratio - 1.0) / 0.60
                r_cut = max(1, int(math.floor(math.exp(exp_val))))
            candidates.add(r_cut)
            if r_cut > 1:
                candidates.add(r_cut - 1)
            candidates.add(r_cut + 1)

    # 3. Relative Advancement Targets
    start_r = curr_rank if (curr_rank is not None and curr_rank > 0) else baseline_rank
    if start_r > 1:
        fractions = [0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.05]
        for f in fractions:
            step_r = max(1, int(round(start_r * f)))
            candidates.add(step_r)

    # 4. Filter candidates:
    # If played, target rank must be strictly better than current rank
    # Target rank must be >= 1
    valid_ranks = []
    for r in candidates:
        if r < 1:
            continue
        if curr_rank is not None and curr_rank > 0 and r >= curr_rank:
            continue
        valid_ranks.append(r)

    valid_ranks.sort()
    return valid_ranks


def simulate_exact_gsi_gain(
    base_scores: List[float],
    curr_score: float,
    s_proj: float,
    mu_pqi: float,
    sigma_pqi: float,
    mu_vdi: float,
    sigma_vdi: float,
    current_gsi: float,
    is_unplayed: bool
) -> Tuple[float, float, float, float]:
    """Perform exact simulated portfolio rescoring and compute exact resulting Delta_GSI."""
    if is_unplayed:
        sim_scores = sorted(base_scores + [s_proj], reverse=True)
    else:
        # Replace current track score with target score
        replaced = False
        sim_scores = []
        for s in base_scores:
            if not replaced and abs(s - curr_score) < 1e-6:
                sim_scores.append(s_proj)
                replaced = True
            else:
                sim_scores.append(s)
        if not replaced:
            sim_scores.append(s_proj)
        sim_scores.sort(reverse=True)

    top6 = sim_scores[:PQI_TOP_K]
    top15 = sim_scores[:VDI_TOP_K]

    sim_pqi = sum(w * s for w, s in zip(_PQI_WEIGHTS, top6)) / _W_FULL_PQI
    sim_vdi = sum(w * s for w, s in zip(_VDI_WEIGHTS, top15)) / _W_FULL_VDI

    z_p_sim = (sim_pqi - mu_pqi) / sigma_pqi
    z_v_sim = (sim_vdi - mu_vdi) / sigma_vdi
    sim_gsi = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_p_sim + GSI_WEIGHT_VDI * z_v_sim)
    delta_gsi = max(0.0, sim_gsi - current_gsi)

    return delta_gsi, sim_gsi, sim_pqi, sim_vdi


def calculate_roi_score(conf_adj_gain: float, effort: float) -> float:
    """Compute ROI Score:
    ROI = Confidence-Adjusted GSI Gain / Effort
    """
    if conf_adj_gain <= 0.0:
        return 0.0
    safe_effort = max(0.50, effort)
    return round(conf_adj_gain / safe_effort, 4)


def filter_pareto_dominated_targets(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out Pareto-dominated targets on the same track.
    Target A is dominated by Target B if:
      conf_adj_gain(B) >= conf_adj_gain(A) and effort(B) <= effort(A)
      with at least one strict inequality.
    """
    if not candidates:
        return []

    non_dominated = []
    for cand_a in candidates:
        is_dominated = False
        gain_a = cand_a["conf_adj_gain"]
        effort_a = cand_a["effort_cost"]

        for cand_b in candidates:
            if cand_b is cand_a:
                continue
            gain_b = cand_b["conf_adj_gain"]
            effort_b = cand_b["effort_cost"]

            if (gain_b >= gain_a and effort_b <= effort_a) and (gain_b > gain_a or effort_b < effort_a):
                is_dominated = True
                break

        if not is_dominated:
            non_dominated.append(cand_a)

    return non_dominated


def classify_recommendation_tier(
    roi: float,
    effort: float,
    delta_gsi: float,
    target_rank: int,
    conf_tier: str
) -> str:
    """Classify target into one of four strategic recommendation classes:
    1. Quick Wins: Low effort + attractive return.
    2. Worth Grinding: Moderate effort + strong GSI return.
    3. Stretch Goals: High effort / frontier targets with meaningful theoretical upside.
    4. Grind Traps: Substantial theoretical gain, but poor ROI due to steep effort / low confidence.
    """
    if delta_gsi >= 0.8 and roi < 0.22 and (effort >= 4.0 or conf_tier == "Low"):
        return "Grind Trap"

    if effort <= 2.2 and roi >= 0.35 and delta_gsi >= 0.25:
        return "Quick Win"

    if (effort > 4.2 or target_rank <= 3) and delta_gsi >= 0.8:
        return "Stretch Goal"

    if roi >= 0.20 and delta_gsi >= 0.30:
        return "Worth Grinding"

    if effort <= 2.5:
        return "Quick Win"

    return "Worth Grinding"


def generate_plain_language_reason(
    target_info: Dict[str, Any],
    s6_cutoff: float,
    s15_cutoff: float,
    num_scores: int
) -> str:
    """Generate concise, actionable, computed explanation for the target recommendation."""
    is_unplayed = target_info["is_unplayed"]
    t_score = target_info["target_score"]
    delta_gsi = target_info["delta_gsi"]
    tier = target_info["recommendation_tier"]
    conf = target_info["confidence_tier"]
    effort = target_info["effort_cost"]
    t_rank = target_info["target_rank"]
    weight = target_info["weight"]

    if tier == "Grind Trap":
        return f"High theoretical upside (+{delta_gsi:.1f} ΔGSI), but requires extreme advancement (Effort: {effort:.2f}) with {conf.lower()} baseline confidence."

    if is_unplayed:
        if num_scores < 15:
            return f"Unplayed track that immediately fills an empty depth slot in your 15-track VDI window (+{delta_gsi:.1f} ΔGSI)."
        elif t_score > s6_cutoff and s6_cutoff > 0:
            return f"Unplayed track that exceeds your Top 6 cutoff ({s6_cutoff:.1f} pts), simultaneously boosting both PQI and VDI windows."
        elif t_score > s15_cutoff and s15_cutoff > 0:
            return f"Unplayed track that replaces your #15 depth floor ({s15_cutoff:.1f} pts) with an attractive {conf.lower()}-confidence return."
        else:
            return f"Solid unplayed entry opportunity on a {weight:.2f}× weight track with {conf.lower()} baseline confidence."

    # Upgrading an existing track
    if t_score > s6_cutoff and s6_cutoff > 0:
        return f"Promotes this track into your Top 6 peak window (exceeding {s6_cutoff:.1f} pts) for significant mechanical ceiling expansion."
    elif t_score > s15_cutoff and s15_cutoff > 0:
        return f"Upgrades your #15 sustained depth cutoff (+{delta_gsi:.1f} ΔGSI) with direct empirical track evidence."
    elif t_rank <= 3:
        return f"Frontier podium target ({format_target_objective(t_rank)}) on a {weight:.2f}× weight track delivering substantial ceiling elevation."
    elif effort <= 2.0:
        return f"Low-effort incremental upgrade near your demonstrated placement with high return per unit investment."
    else:
        return f"Strategic upgrade offering +{delta_gsi:.1f} ΔGSI with proven track familiarity."


def evaluate_player_strategy(
    player_scores_map: Dict[str, float],
    player_ranks_map: Dict[str, int],
    all_tracks_dict: Dict[str, Dict[str, Any]],
    current_pqi: float,
    current_vdi: float,
    current_gsi: float,
    mu_pqi: float,
    sigma_pqi: float,
    mu_vdi: float,
    sigma_vdi: float,
    top_n: int = 3,
    custom_i_star: Optional[float] = None
) -> List[Dict[str, Any]]:
    """Evaluate candidate targets across all tracks using the redesigned 4-pillar architecture:
    1. Player Baseline & Cross-Track Consistency Prior
    2. Candidate Target Ladder Generation per Track
    3. Exact Simulated GSI Reward & Marginal Portfolio Impact
    4. Player-Relative Effort & Universal Frontier Penalty
    5. Confidence-Adjusted Gain & ROI Optimization
    6. Pareto Dominance Filtering & Recommendation Tiering
    """
    base_scores = list(player_scores_map.values())
    base_scores_sorted = sorted(base_scores, reverse=True)
    num_scores = len(base_scores_sorted)
    s6_cut = base_scores_sorted[5] if num_scores >= 6 else 0.0
    s15_cut = base_scores_sorted[14] if num_scores >= 15 else 0.0

    # 1. Establish player baseline and consistency
    baseline_stats = calculate_player_baseline(player_scores_map, player_ranks_map, all_tracks_dict)
    consistency_cv = calculate_cross_track_consistency(player_scores_map, all_tracks_dict)
    driven_count = baseline_stats["driven_count"]
    global_baseline_rank = baseline_stats["median_rank"]

    # Evaluate candidate ladders across all tracks
    all_track_recommendations: List[Dict[str, Any]] = []

    for tr_name, tr_meta in all_tracks_dict.items():
        omega_k = tr_meta.get("dynamic_weight", 1.0)
        domain_k = tr_meta.get("domain", "Fullspeed")
        subgenre_k = tr_meta.get("subgenre", "FS")
        is_main_k = tr_meta.get("is_main", False)

        curr_score = player_scores_map.get(tr_name, 0.0)
        curr_rank = player_ranks_map.get(tr_name, None)
        is_unplayed = (curr_rank is None or curr_score <= 0.0)

        # Baseline starting rank for this track
        baseline_r = curr_rank if not is_unplayed else global_baseline_rank
        conf_tier, conf_factor = determine_confidence_tier(is_unplayed, consistency_cv, driven_count)

        # Generate candidate target ladder
        ladder_ranks = generate_candidate_target_ladder(
            track_name=tr_name,
            curr_rank=curr_rank,
            baseline_rank=global_baseline_rank,
            omega_k=omega_k,
            s6_cutoff=s6_cut,
            s15_cutoff=s15_cut
        )

        track_candidates = []
        for r_target in ladder_ranks:
            s_proj = calculate_projected_track_score(r_target, omega_k)
            if s_proj <= curr_score:
                continue

            # If unplayed and player has >= 15 scores, s_proj must exceed s15_cut to impact GSI
            if is_unplayed and num_scores >= 15 and s_proj <= s15_cut:
                continue

            delta_gsi, sim_gsi, sim_pqi, sim_vdi = simulate_exact_gsi_gain(
                base_scores=base_scores,
                curr_score=curr_score,
                s_proj=s_proj,
                mu_pqi=mu_pqi,
                sigma_pqi=sigma_pqi,
                mu_vdi=mu_vdi,
                sigma_vdi=sigma_vdi,
                current_gsi=current_gsi,
                is_unplayed=is_unplayed
            )

            if delta_gsi <= 0.0001:
                continue

            effort_cost = calculate_effort(
                baseline_rank=baseline_r,
                target_rank=r_target,
                omega_k=omega_k,
                is_unplayed=is_unplayed
            )

            conf_adj_gain = round(delta_gsi * conf_factor, 4)
            roi_score = calculate_roi_score(conf_adj_gain, effort_cost)

            rec_tier = classify_recommendation_tier(
                roi=roi_score,
                effort=effort_cost,
                delta_gsi=delta_gsi,
                target_rank=r_target,
                conf_tier=conf_tier
            )

            cand_obj = {
                "track": tr_name,
                "is_main": is_main_k,
                "category": "Campaign" if is_main_k else "Community",
                "domain": domain_k,
                "subgenre": subgenre_k,
                "style": subgenre_k,
                "weight": round(omega_k, 4),
                "curr_rank": curr_rank,
                "curr_score": round(curr_score, 4),
                "is_unplayed": is_unplayed,
                "target_rank": r_target,
                "target_objective": format_target_objective(r_target),
                "target_score": round(s_proj, 4),
                "effort_cost": round(effort_cost, 4),
                "delta_gsi": round(delta_gsi, 4),
                "confidence_tier": conf_tier,
                "confidence_factor": conf_factor,
                "conf_adj_gain": conf_adj_gain,
                "projected_gsi": round(sim_gsi, 2),
                "roi_score": roi_score,
                "recommendation_tier": rec_tier,
                "breaks_pqi": s_proj > s6_cut,
                "breaks_vdi": s_proj > s15_cut
            }
            cand_obj["reason"] = generate_plain_language_reason(cand_obj, s6_cut, s15_cut, num_scores)
            track_candidates.append(cand_obj)

        if not track_candidates:
            continue

        # Filter Pareto-dominated opportunities on this track
        non_dominated = filter_pareto_dominated_targets(track_candidates)
        if not non_dominated:
            continue

        # Find best ROI sweet spot on this track
        best_track_roi_target = max(non_dominated, key=lambda x: (x["roi_score"], x["conf_adj_gain"], -x["effort_cost"]))
        all_track_recommendations.append(best_track_roi_target)

    # Sort across all candidate tracks by ROI Score descending
    all_track_recommendations.sort(key=lambda x: (x["roi_score"], x["conf_adj_gain"], x["delta_gsi"], x["weight"]), reverse=True)

    if top_n and top_n > 0:
        return all_track_recommendations[:top_n]
    return all_track_recommendations


evaluate_candidate_tracks_roi = evaluate_player_strategy


def load_community_tracks(csv_path: Optional[str] = None) -> Dict[str, str]:
    """Load community track names and track IDs from CSV."""
    if csv_path is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, "CTs TrackId - Feuille 1.csv")
        if not os.path.exists(csv_path):
            parent_dir = os.path.dirname(base_dir)
            csv_path = os.path.join(parent_dir, "CTs TrackId - Feuille 1.csv")

    tracks = {}
    if not os.path.exists(csv_path):
        print(f"Warning: Community tracks CSV not found at '{csv_path}'")
        return tracks

    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = normalize_track_name(row.get("Name", "").strip())
            track_id = row.get("trackId", "").strip()
            if name and track_id:
                tracks[name] = track_id
    return tracks


def load_track_styles(csv_path: Optional[str] = None) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load track subgenre and domain classifications from TrackTypes - Sheet1.csv.

    Returns:
        Tuple[domain_map, subgenre_map]
    """
    if csv_path is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, "TrackTypes - Sheet1.csv")
        if not os.path.exists(csv_path):
            parent_dir = os.path.dirname(base_dir)
            csv_path = os.path.join(parent_dir, "TrackTypes - Sheet1.csv")

    domain_map: Dict[str, str] = {}
    subgenre_map: Dict[str, str] = {}

    if not os.path.exists(csv_path):
        print(f"Warning: TrackTypes CSV not found at '{csv_path}'")
        return domain_map, subgenre_map

    main_alias = {
        "S1": "Summer 1", "S2": "Summer 2", "S3": "Summer 3", "S4": "Summer 4",
        "S5": "Summer 5", "S6": "Summer 6", "S7": "Summer 7",
        "W1": "Winter 1", "W2": "Winter 2", "W3": "Winter 3", "W4": "Winter 4", "W5": "Winter 5",
        "D1": "Desert 1", "D2": "Desert 2", "D3": "Desert 3", "D4": "Desert 4", "D5": "Desert 5"
    }

    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                # Main tracks column A & B
                if len(row) >= 2 and row[0].strip():
                    m_code = row[0].strip()
                    tname = main_alias.get(m_code, m_code)
                    raw_style = row[1].strip()
                    dom, subg = map_track_to_domain_and_subgenre(tname, raw_style)
                    domain_map[tname] = dom
                    subgenre_map[tname] = subg

                # Community tracks column C & D
                if len(row) >= 4 and row[2].strip():
                    c_name = normalize_track_name(row[2].strip())
                    raw_style = row[3].strip()
                    dom, subg = map_track_to_domain_and_subgenre(c_name, raw_style)
                    domain_map[c_name] = dom
                    subgenre_map[c_name] = subg
    except Exception as e:
        print(f"Warning: Failed reading track styles from '{csv_path}': {e}")

    # Track alias fallbacks
    aliases = {
        "The Eldritch Estate": ("Fullspeed", "FS"),
        "Eldritch Estate": ("Fullspeed", "FS"),
        "Eldritch Eatate": ("Fullspeed", "FS"),
        "Planet97": ("Technical", "Speedfun"),
        "Planet 97": ("Technical", "Speedfun"),
        "Launch Control": ("Fullspeed", "FS"),
        "Launch Controll": ("Fullspeed", "FS"),
        "Lauch Controll": ("Fullspeed", "FS"),
        "Lauch Control": ("Fullspeed", "FS"),
        "Apostle": ("Fullspeed", "FS"),
        "Flying Dreams": ("Technical", "Speedfun"),
        "Lu Muvimento": ("Fullspeed", "FS"),
        "Lu Muvimiento": ("Fullspeed", "FS"),
        "lu muvimiento": ("Fullspeed", "FS"),
        "lu muvimento": ("Fullspeed", "FS"),
    }
    for a_name, (a_dom, a_subg) in aliases.items():
        if a_name not in domain_map:
            domain_map[a_name] = a_dom
            subgenre_map[a_name] = a_subg

    return domain_map, subgenre_map


class TrackRegistry:
    """Registry maintaining metadata, categories, domains, subgenres, player counts, and dynamic weights for all 78 tracks."""

    def __init__(self, comm_csv_path: Optional[str] = None, style_csv_path: Optional[str] = None):
        self.main_tracks: Dict[str, str] = dict(MAIN_TRACKS)
        self.community_tracks: Dict[str, str] = load_community_tracks(comm_csv_path)
        self.all_tracks: Dict[str, str] = {**self.main_tracks, **self.community_tracks}
        self.track_domains, self.track_subgenres = load_track_styles(style_csv_path)
        self.track_styles: Dict[str, str] = self.track_domains  # Compatibility alias
        self.track_totals: Dict[str, int] = {}
        self.track_weights: Dict[str, float] = {}

    def is_main(self, track_name: str) -> bool:
        return track_name in self.main_tracks

    def get_domain(self, track_name: str) -> str:
        return self.track_domains.get(track_name, "Fullspeed")

    def get_subgenre(self, track_name: str) -> str:
        return self.track_subgenres.get(track_name, "FS")

    def get_style(self, track_name: str) -> str:
        return self.get_subgenre(track_name)

    def get_domain_totals(self) -> Dict[str, int]:
        counts = {d: 0 for d in DISCIPLINE_DOMAINS}
        for tname in self.all_tracks.keys():
            d = self.get_domain(tname)
            counts[d] = counts.get(d, 0) + 1
        return counts

    def get_subgenre_totals(self) -> Dict[str, int]:
        counts = {sg: 0 for sg in SUBGENRES}
        for tname in self.all_tracks.keys():
            sg = self.get_subgenre(tname)
            counts[sg] = counts.get(sg, 0) + 1
        return counts

    def get_style_totals(self) -> Dict[str, int]:
        return self.get_domain_totals()

    def set_track_totals(self, totals: Dict[str, int]):
        self.track_totals.update(totals)
        for tname, tot in totals.items():
            w = calculate_dynamic_track_weight(tot)
            self.track_weights[tname] = w

    def get_total(self, track_name: str) -> int:
        return self.track_totals.get(track_name, 0)

    def get_weight(self, track_name: str) -> float:
        return self.track_weights.get(track_name, 1.0)


# =====================================================================
# Rate Limiting & Async Leaderboard Ingestion
# =====================================================================

class TokenBucket:
    """Thread-safe Token Bucket for async API rate limiting."""

    def __init__(self, rate: float = 40.0, capacity: float = 15.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_update = time.monotonic()
            else:
                self.tokens -= 1.0


def process_raw_leaderboard(
    entries: List[Dict[str, Any]],
    alt_mappings: Optional[Dict[str, str]] = None,
    blacklisted_players: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """Clean, filter [TAS] bots and blacklisted players, consolidate alt accounts per track (keeping the fastest time), and re-index dense ranks."""
    if alt_mappings is None:
        alt_mappings = ALT_MAPPINGS
    if blacklisted_players is None:
        blacklisted_players = BLACKLISTED_PLAYERS

    valid_entries: List[Dict[str, Any]] = []

    for entry in entries:
        nickname = entry.get("nickname", "").strip()
        if not nickname:
            continue

        if nickname.lower().startswith("[tas]"):
            continue

        user_id = entry.get("userId", "").strip()

        # Check raw nickname & userId against blacklist early
        if is_player_blacklisted(nickname=nickname, user_id=user_id, blacklisted_players=blacklisted_players):
            continue

        frames = entry.get("frames", 0)
        time_sec = frames / 60.0

        canonical_key, canonical_nick = resolve_player_identity(nickname, user_id, alt_mappings=alt_mappings)

        # Check canonical identity against blacklist (e.g. if an alt is mapped to a blacklisted player)
        if is_player_blacklisted(
            nickname=nickname,
            user_id=user_id,
            canonical_key=canonical_key,
            canonical_nick=canonical_nick,
            blacklisted_players=blacklisted_players
        ):
            continue

        valid_entries.append({
            "canonicalKey": canonical_key,
            "canonicalNickname": canonical_nick,
            "userId": user_id,
            "nickname": nickname,
            "frames": frames,
            "time_sec": time_sec,
            "raw_entry": entry
        })

    # Sort all entries on track by time_sec ascending (fastest first)
    valid_entries.sort(key=lambda x: x["time_sec"])

    # Deduplicate by canonicalKey so each unique human competitor occupies at most 1 slot (their fastest time)
    cleaned: List[Dict[str, Any]] = []
    seen_canonical: Set[str] = set()

    for ve in valid_entries:
        ck = ve["canonicalKey"]
        if ck in seen_canonical:
            continue
        seen_canonical.add(ck)
        cleaned.append(ve)

    # Re-index dense ranks (1, 2, 3...)
    for idx, e in enumerate(cleaned, start=1):
        e["rank"] = idx

    return cleaned


async def fetch_leaderboard_page(
    track_name: str,
    track_id: str,
    amount: int,
    limiter: TokenBucket,
    sem: asyncio.Semaphore,
    max_retries: int = 4
) -> Tuple[str, List[Dict[str, Any]], int]:
    """Fetch track leaderboard up to `amount` entries using pagination with exponential backoff."""
    all_entries = []
    total_participants = 0
    page_size = 500

    for skip in range(0, amount, page_size):
        chunk_amount = min(page_size, amount - skip)
        params = {
            "version": API_VERSION,
            "trackId": track_id,
            "skip": str(skip),
            "amount": str(chunk_amount),
            "onlyVerified": "false"
        }
        if USER_TOKEN_HASH:
            params["userTokenHash"] = USER_TOKEN_HASH
        url = f"{BASE_URL}?{urlencode(params)}"

        chunk_entries = None
        for attempt in range(1, max_retries + 1):
            await sem.acquire()
            try:
                await limiter.acquire()
                timeout = aiohttp.ClientTimeout(total=25)
                async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            if isinstance(data, dict):
                                chunk_entries = data.get("entries", [])
                                total_participants = data.get("total", total_participants or len(chunk_entries))
                                break
                            elif isinstance(data, list):
                                chunk_entries = data
                                total_participants = max(total_participants, len(data))
                                break
                        elif response.status == 429:
                            backoff = (2 ** attempt) * 0.5
                            print(f"[{track_name}] 429 Rate limited on skip={skip}. Backing off {backoff:.1f}s...")
                            await asyncio.sleep(backoff)
                        else:
                            print(f"[{track_name}] HTTP {response.status} on skip={skip} (Attempt {attempt}/{max_retries})")
                            await asyncio.sleep(1.0)
            except Exception as ex:
                if attempt == max_retries:
                    print(f"[{track_name}] Error fetching skip={skip}: {ex}")
                await asyncio.sleep(1.0 * attempt)
            finally:
                sem.release()

        if chunk_entries:
            all_entries.extend(chunk_entries)
            if len(chunk_entries) < chunk_amount:
                break
        else:
            break

    return track_name, all_entries, total_participants


async def fetch_all_leaderboards(
    tracks: Dict[str, str],
    amount: int = 1000,
    rate_limit: float = 30.0,
    max_concurrency: int = 8
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    """Fetch all track leaderboards and total participant counts concurrently with rate limiting."""
    limiter = TokenBucket(rate=rate_limit, capacity=12.0)
    sem = asyncio.Semaphore(max_concurrency)

    tasks = [
        fetch_leaderboard_page(tname, tid, amount, limiter, sem)
        for tname, tid in tracks.items()
    ]
    results = await asyncio.gather(*tasks)
    leaderboards = {track_name: entries for track_name, entries, _ in results}
    totals = {track_name: total for track_name, _, total in results}
    return leaderboards, totals


def get_default_cache_path() -> str:
    """Return default cache filepath in the workspace."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(base_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "leaderboards_cache.json")


def normalize_track_name(name: str) -> str:
    s = name.strip()
    if s.lower() in ("lu muvimiento", "lu muvimento", "lumuvimiento", "lumuvimento"):
        return "Lu Muvimento"
    aliases = {
        "Lauch Controll": "Launch Control",
        "Launch Controll": "Launch Control",
        "Lauch Control": "Launch Control",
        "The Eldritch Eatate": "The Eldritch Estate",
        "Eldritch Eatate": "The Eldritch Estate",
        "Planet97": "Planet 97",
    }
    return aliases.get(s, s)


def load_cached_leaderboards(cache_path: str) -> Optional[Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, int]]]:
    """Load cached raw leaderboards and track totals from disk if present."""
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_leaderboards = data.get("leaderboards")
                raw_totals = data.get("track_totals", {})
                if raw_leaderboards:
                    leaderboards = {normalize_track_name(k): v for k, v in raw_leaderboards.items()}
                    totals = {normalize_track_name(k): v for k, v in raw_totals.items()}
                    return leaderboards, totals
        except Exception as e:
            print(f"Warning: Failed reading cache '{cache_path}': {e}")
    return None


def save_cached_leaderboards(
    cache_path: str,
    leaderboards: Dict[str, List[Dict[str, Any]]],
    track_totals: Dict[str, int]
):
    """Save raw leaderboards and track totals to disk cache."""
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        payload = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "track_count": len(leaderboards),
            "leaderboards": leaderboards,
            "track_totals": track_totals
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Failed saving cache '{cache_path}': {e}")


# =====================================================================
# Engine 1: Peak Quality Index (PQI - Top-6 Mechanical Ceiling)
# =====================================================================

class PeakQualityIndexEngine:
    """Computes closed-form Player Peak Quality Index (PQI) based on Top-6 full-window normalized mechanical ceiling."""

    def __init__(
        self,
        top_k: int = PQI_TOP_K,
        gamma: float = PQI_GAMMA
    ):
        self.top_k = top_k
        self.gamma = gamma
        self.w_full = sum(self.gamma ** r for r in range(self.top_k))

    def calculate_track_score(self, rank: int, weight: float) -> float:
        """S_{i,k} = omega_k * 100.0 * R(Rank) * (1.25 if Rank==1 else 1.00)"""
        return calculate_smooth_track_score(rank, weight)

    def aggregate_pqi(self, all_track_scores: List[float]) -> Tuple[float, float, List[float]]:
        """Compute Full-Window PQI (Top-6 ceiling) and Raw Intensity."""
        if not all_track_scores:
            return 0.0, 0.0, []

        sorted_scores = sorted(all_track_scores, reverse=True)
        top_scores = sorted_scores[:self.top_k]
        m = len(top_scores)

        weights = [self.gamma ** r for r in range(m)]
        weighted_sum = sum(w * s for w, s in zip(weights, top_scores))
        sum_weights = sum(weights)

        raw_intensity = (weighted_sum / sum_weights) if sum_weights > 0 else 0.0
        pqi = (weighted_sum / self.w_full) if self.w_full > 0 else 0.0

        return pqi, raw_intensity, top_scores


# =====================================================================
# Engine 2: Versatility & Depth Index (VDI - Top-15 Sustained Quality)
# =====================================================================

class VersatilityDepthIndexEngine:
    """Computes closed-form Player Versatility & Depth Index (VDI) based on Top-15 full-window normalized sustained quality."""

    def __init__(
        self,
        top_k: int = VDI_TOP_K,
        gamma: float = VDI_GAMMA
    ):
        self.top_k = top_k
        self.gamma = gamma
        self.w_full = sum(self.gamma ** r for r in range(self.top_k))

    def aggregate_vdi(self, all_track_scores: List[float]) -> Tuple[float, float, List[float]]:
        """Compute Full-Window VDI (Top-15 depth) and Raw Intensity."""
        if not all_track_scores:
            return 0.0, 0.0, []

        sorted_scores = sorted(all_track_scores, reverse=True)
        top_scores = sorted_scores[:self.top_k]
        m = len(top_scores)

        weights = [self.gamma ** r for r in range(m)]
        weighted_sum = sum(w * s for w, s in zip(weights, top_scores))
        sum_weights = sum(weights)

        raw_intensity = (weighted_sum / sum_weights) if sum_weights > 0 else 0.0
        vdi = (weighted_sum / self.w_full) if self.w_full > 0 else 0.0

        return vdi, raw_intensity, top_scores


# =====================================================================
# Bridge Player Analytics & Player Taxonomy
# =====================================================================

def classify_player(
    main_tracks_count: int,
    comm_tracks_count: int,
    main_score: float,
    comm_score: float
) -> Tuple[str, float]:
    """Classify player into Main Specialist, Community Specialist, or All Rounder."""
    total_score = main_score + comm_score
    domain_bias = (main_score / total_score) if total_score > 0 else 0.5

    if domain_bias >= 0.70:
        category = "Main Specialist"
    elif (1.0 - domain_bias) >= 0.70:
        category = "Community Specialist"
    else:
        category = "All Rounder"

    return category, round(domain_bias, 4)


# =====================================================================
# Master Pipeline & Orchestrator (v10.2 Pure Leaderboard Pipeline)
# =====================================================================

class PowerRankingSystem:
    """Master orchestrator for v10.2 Pure Leaderboard Architecture:

    Synthesizes Peak Mechanical Ceiling (Top 6 PQI, 70%) and Sustained Versatility (Top 15 VDI, 30%).
    """

    def __init__(
        self,
        comm_csv_path: Optional[str] = None,
        top_k_pqi: int = PQI_TOP_K,
        gamma_pqi: float = PQI_GAMMA,
        top_k_vdi: int = VDI_TOP_K,
        gamma_vdi: float = VDI_GAMMA,
        active_min_tracks: int = ACTIVE_MIN_TRACKS_DEFAULT,
        alt_mappings: Optional[Dict[str, str]] = None,
        blacklisted_players: Optional[Set[str]] = None
    ):
        self.registry = TrackRegistry(comm_csv_path)
        self.engine_pqi = PeakQualityIndexEngine(top_k=top_k_pqi, gamma=gamma_pqi)
        self.engine_vdi = VersatilityDepthIndexEngine(top_k=top_k_vdi, gamma=gamma_vdi)
        self.active_min_tracks = active_min_tracks
        self.alt_mappings = alt_mappings or ALT_MAPPINGS
        self.blacklisted_players = blacklisted_players if blacklisted_players is not None else BLACKLISTED_PLAYERS

    async def ingest_leaderboards(
        self,
        amount: int = 1000,
        use_cache: bool = False,
        cache_path: Optional[str] = None
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
        """Fetch or load cached leaderboards and total player counts for all 78 tracks."""
        if cache_path is None:
            cache_path = get_default_cache_path()

        if use_cache:
            cached = load_cached_leaderboards(cache_path)
            if cached:
                leaderboards, totals = cached
                if len(leaderboards) >= len(self.registry.all_tracks):
                    print(f"Loaded {len(leaderboards)} track leaderboards from cache ('{cache_path}')")
                    self.registry.set_track_totals(totals)
                    return leaderboards, totals
                else:
                    print(f"Cache incomplete ({len(leaderboards)}/{len(self.registry.all_tracks)} tracks). Falling back to live scrape...")

        print(f"Scraping live leaderboards for {len(self.registry.all_tracks)} tracks (amount={amount})...")
        t0 = time.monotonic()
        try:
            raw_leaderboards, totals = await fetch_all_leaderboards(
                self.registry.all_tracks,
                amount=amount,
                rate_limit=50.0,
                max_concurrency=12
            )
            elapsed = time.monotonic() - t0
            total_entries = sum(len(v) for v in raw_leaderboards.values())

            # Fallback to cache if live scrape fetched 0 entries (e.g. offline / network down)
            if total_entries == 0 and os.path.exists(cache_path):
                print(f"Warning: Live scrape returned 0 entries. Falling back to cache ('{cache_path}')...")
                cached = load_cached_leaderboards(cache_path)
                if cached:
                    leaderboards, totals = cached
                    self.registry.set_track_totals(totals)
                    return leaderboards, totals

            print(f"Successfully scraped {len(raw_leaderboards)} tracks in {elapsed:.2f}s.")
            self.registry.set_track_totals(totals)
            save_cached_leaderboards(cache_path, raw_leaderboards, totals)
            return raw_leaderboards, totals
        except Exception as e:
            if os.path.exists(cache_path):
                print(f"Warning: Live scrape failed ({e}). Falling back to cached leaderboards ('{cache_path}')...")
                cached = load_cached_leaderboards(cache_path)
                if cached:
                    leaderboards, totals = cached
                    self.registry.set_track_totals(totals)
                    return leaderboards, totals
            raise

    def compute_all_rankings(
        self,
        raw_leaderboards: Dict[str, List[Dict[str, Any]]],
        track_totals: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """Execute v10.0 Pure Leaderboard Architecture Pipeline."""
        t_start = time.monotonic()

        if track_totals:
            self.registry.set_track_totals(track_totals)

        # Step 1: Clean leaderboards, consolidate alts per track, and extract canonical player metadata
        cleaned_tracks: Dict[str, List[Dict[str, Any]]] = {}
        all_players_meta: Dict[str, Dict[str, Any]] = {}

        for track_name, entries in raw_leaderboards.items():
            cleaned = process_raw_leaderboard(
                entries,
                alt_mappings=self.alt_mappings,
                blacklisted_players=self.blacklisted_players
            )
            cleaned_tracks[track_name] = cleaned

            for entry in cleaned:
                canonical_key = entry["canonicalKey"]
                canonical_nick = entry["canonicalNickname"]
                user_id = entry["userId"]

                if canonical_key not in all_players_meta:
                    all_players_meta[canonical_key] = {
                        "userId": user_id,
                        "canonical_nickname": canonical_nick,
                        "track_records": {}
                    }
                all_players_meta[canonical_key]["track_records"][track_name] = entry

        player_keys = sorted(all_players_meta.keys())
        n_players = len(player_keys)

        print(f"Extracted {n_players} unique competitors across {len(cleaned_tracks)} tracks.")

        # Identify established competitors based on total driven tracks (>= active_min_tracks)
        established_keys = {
            k for k in player_keys
            if len(all_players_meta[k]["track_records"]) >= self.active_min_tracks
        }
        active_mask = np.array([k in established_keys for k in player_keys], dtype=bool)

        # Track Statistics Summary
        # Track Statistics Summary
        domain_totals_map = self.registry.get_domain_totals()
        subgenre_totals_map = self.registry.get_subgenre_totals()
        track_stats: Dict[str, Dict[str, Any]] = {}
        for track_name, entries in cleaned_tracks.items():
            tot = self.registry.get_total(track_name)
            w_k = self.registry.get_weight(track_name)
            dom_k = self.registry.get_domain(track_name)
            subg_k = self.registry.get_subgenre(track_name)

            track_stats[track_name] = {
                "is_main": self.registry.is_main(track_name),
                "domain": dom_k,
                "subgenre": subg_k,
                "style": subg_k,  # Compatibility alias
                "total_players": tot,
                "dynamic_weight": w_k,
                "scraped_entries": len(entries)
            }

        # -------------------------------------------------------------
        # ENGINE 1 (PQI), ENGINE 2 (VDI) & 2-DOMAIN DISCIPLINE ENGINE (v10.2)
        # -------------------------------------------------------------
        engine_player_results = {}

        for key in player_keys:
            meta = all_players_meta[key]
            all_recs = meta["track_records"]

            all_scores_map = {}
            main_scores_raw = []
            comm_scores_raw = []
            breakdown = {}

            domain_scores_map = {d: [] for d in DISCIPLINE_DOMAINS}
            domain_wrs_map = {d: 0 for d in DISCIPLINE_DOMAINS}
            domain_t3_map = {d: 0 for d in DISCIPLINE_DOMAINS}
            domain_t5_map = {d: 0 for d in DISCIPLINE_DOMAINS}
            domain_t10_map = {d: 0 for d in DISCIPLINE_DOMAINS}

            wr_main_count = 0
            wr_comm_count = 0
            top3_count = 0
            top5_count = 0
            top10_count = 0
            main_count = 0
            comm_count = 0

            for tr_name, rec in all_recs.items():
                rank = rec["rank"]
                w = self.registry.get_weight(tr_name)
                dom = self.registry.get_domain(tr_name)
                subg = self.registry.get_subgenre(tr_name)
                base_score = self.engine_pqi.calculate_track_score(rank, w)
                all_scores_map[tr_name] = base_score

                is_main = self.registry.is_main(tr_name)
                if is_main:
                    main_count += 1
                    main_scores_raw.append(base_score)
                    if rank == 1:
                        wr_main_count += 1
                else:
                    comm_count += 1
                    comm_scores_raw.append(base_score)
                    if rank == 1:
                        wr_comm_count += 1

                if rank <= 3:
                    top3_count += 1
                if rank <= 5:
                    top5_count += 1
                if rank <= 10:
                    top10_count += 1

                # Domain Stats
                domain_scores_map[dom].append(base_score)
                if rank == 1:
                    domain_wrs_map[dom] += 1
                if rank <= 3:
                    domain_t3_map[dom] += 1
                if rank <= 5:
                    domain_t5_map[dom] += 1
                if rank <= 10:
                    domain_t10_map[dom] += 1

                breakdown[tr_name] = {
                    "rank": rank,
                    "time_sec": rec["time_sec"],
                    "weight": w,
                    "domain": dom,
                    "subgenre": subg,
                    "style": subg,
                    "base_score": round(base_score, 4)
                }

            scores_list = list(all_scores_map.values())
            pqi, raw_pqi, top_scores_pqi = self.engine_pqi.aggregate_pqi(scores_list)
            vdi, raw_vdi, top_scores_vdi = self.engine_vdi.aggregate_vdi(scores_list)
            total_count = main_count + comm_count

            score_main_raw = sum(main_scores_raw)
            score_comm_raw = sum(comm_scores_raw)
            category, domain_bias = classify_player(main_count, comm_count, score_main_raw, score_comm_raw)

            # 2-Domain Discipline Rating & Depth Computation (v10.2 Dual-Axis Mastery)
            fs_scores = domain_scores_map["Fullspeed"]
            tech_scores = domain_scores_map["Technical"]

            pqi_fs, raw_fs, top_scores_pqi_fs = self.engine_pqi.aggregate_pqi(fs_scores)
            vdi_fs, raw_vdi_fs, top_scores_vdi_fs = self.engine_vdi.aggregate_vdi(fs_scores)

            pqi_tech, raw_tech, top_scores_pqi_tech = self.engine_pqi.aggregate_pqi(tech_scores)
            vdi_tech, raw_vdi_tech, top_scores_vdi_tech = self.engine_vdi.aggregate_vdi(tech_scores)

            rating_fs = pqi_fs
            rating_tech = pqi_tech
            n_eff_fs = min(DISCIPLINE_TOP_K, len(fs_scores))
            n_eff_tech = min(DISCIPLINE_TOP_K, len(tech_scores))

            discipline_bias = calculate_discipline_bias(rating_fs, rating_tech)
            archetype = determine_discipline_archetype(
                discipline_bias,
                len(fs_scores),
                len(tech_scores),
                total_count
            )

            engine_player_results[key] = {
                "pqi": round(pqi, 4),
                "raw_pqi": round(raw_pqi, 4),
                "top_scores_pqi": [round(s, 2) for s in top_scores_pqi],
                "vdi": round(vdi, 4),
                "raw_vdi": round(raw_vdi, 4),
                "top_scores_vdi": [round(s, 2) for s in top_scores_vdi],
                "main_tracks_count": main_count,
                "comm_tracks_count": comm_count,
                "total_tracks_count": total_count,
                "wr_main_count": wr_main_count,
                "wr_comm_count": wr_comm_count,
                "wr_total_count": wr_main_count + wr_comm_count,
                "top3_count": top3_count,
                "top5_count": top5_count,
                "top10_count": top10_count,
                "domain_bias": domain_bias,
                "classification": category,
                "breakdown": breakdown,
                "rating_fs": rating_fs,
                "pqi_fs": round(pqi_fs, 4),
                "raw_fs": raw_fs,
                "vdi_fs": round(vdi_fs, 4),
                "raw_vdi_fs": raw_vdi_fs,
                "n_eff_fs": n_eff_fs,
                "count_fs": len(fs_scores),
                "wr_fs": domain_wrs_map["Fullspeed"],
                "t3_fs": domain_t3_map["Fullspeed"],
                "t5_fs": domain_t5_map["Fullspeed"],
                "t10_fs": domain_t10_map["Fullspeed"],
                "rating_tech": rating_tech,
                "pqi_tech": round(pqi_tech, 4),
                "raw_tech": raw_tech,
                "vdi_tech": round(vdi_tech, 4),
                "raw_vdi_tech": raw_vdi_tech,
                "n_eff_tech": n_eff_tech,
                "count_tech": len(tech_scores),
                "wr_tech": domain_wrs_map["Technical"],
                "t3_tech": domain_t3_map["Technical"],
                "t5_tech": domain_t5_map["Technical"],
                "t10_tech": domain_t10_map["Technical"],
                "discipline_bias": discipline_bias,
                "archetype": archetype
            }

        # -------------------------------------------------------------
        # ENGINE 3: Global Skill Index (GSI Composite Synthesis) & Discipline GSIs
        # -------------------------------------------------------------
        # 1. Global Standardization
        active_pqis = [
            engine_player_results[k]["pqi"]
            for idx, k in enumerate(player_keys)
            if active_mask[idx]
        ]
        active_vdis = [
            engine_player_results[k]["vdi"]
            for idx, k in enumerate(player_keys)
            if active_mask[idx]
        ]

        mu_pqi = float(np.mean(active_pqis)) if len(active_pqis) > 0 else 0.0
        sigma_pqi = float(np.std(active_pqis)) if len(active_pqis) > 0 else 1.0
        if sigma_pqi < 1e-8:
            sigma_pqi = 1.0

        mu_vdi = float(np.mean(active_vdis)) if len(active_vdis) > 0 else 0.0
        sigma_vdi = float(np.std(active_vdis)) if len(active_vdis) > 0 else 1.0
        if sigma_vdi < 1e-8:
            sigma_vdi = 1.0

        # 2. Fullspeed Discipline Standardization (across competitors active in Fullspeed)
        active_fs_keys = [
            k for k in player_keys
            if engine_player_results[k]["count_fs"] >= self.active_min_tracks
        ]
        active_fs_pqis = [engine_player_results[k]["pqi_fs"] for k in active_fs_keys]
        active_fs_vdis = [engine_player_results[k]["vdi_fs"] for k in active_fs_keys]

        mu_pqi_fs = float(np.mean(active_fs_pqis)) if len(active_fs_pqis) > 0 else 0.0
        sigma_pqi_fs = float(np.std(active_fs_pqis)) if len(active_fs_pqis) > 0 else 1.0
        if sigma_pqi_fs < 1e-8:
            sigma_pqi_fs = 1.0

        mu_vdi_fs = float(np.mean(active_fs_vdis)) if len(active_fs_vdis) > 0 else 0.0
        sigma_vdi_fs = float(np.std(active_fs_vdis)) if len(active_fs_vdis) > 0 else 1.0
        if sigma_vdi_fs < 1e-8:
            sigma_vdi_fs = 1.0

        # 3. Technical Discipline Standardization (across competitors active in Technical)
        active_tech_keys = [
            k for k in player_keys
            if engine_player_results[k]["count_tech"] >= self.active_min_tracks
        ]
        active_tech_pqis = [engine_player_results[k]["pqi_tech"] for k in active_tech_keys]
        active_tech_vdis = [engine_player_results[k]["vdi_tech"] for k in active_tech_keys]

        mu_pqi_tech = float(np.mean(active_tech_pqis)) if len(active_tech_pqis) > 0 else 0.0
        sigma_pqi_tech = float(np.std(active_tech_pqis)) if len(active_tech_pqis) > 0 else 1.0
        if sigma_pqi_tech < 1e-8:
            sigma_pqi_tech = 1.0

        mu_vdi_tech = float(np.mean(active_tech_vdis)) if len(active_tech_vdis) > 0 else 0.0
        sigma_vdi_tech = float(np.std(active_tech_vdis)) if len(active_tech_vdis) > 0 else 1.0
        if sigma_vdi_tech < 1e-8:
            sigma_vdi_tech = 1.0

        # Compute Discipline GSIs for all players
        player_fs_gsi_map: Dict[str, Tuple[float, float, float]] = {}
        player_tech_gsi_map: Dict[str, Tuple[float, float, float]] = {}

        for key in player_keys:
            res = engine_player_results[key]

            # Fullspeed
            if res["count_fs"] > 0:
                z_p_fs = (res["pqi_fs"] - mu_pqi_fs) / sigma_pqi_fs
                z_v_fs = (res["vdi_fs"] - mu_vdi_fs) / sigma_vdi_fs
                g_fs = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_p_fs + GSI_WEIGHT_VDI * z_v_fs)
                player_fs_gsi_map[key] = (g_fs, z_p_fs, z_v_fs)
            else:
                player_fs_gsi_map[key] = (0.0, 0.0, 0.0)

            # Technical
            if res["count_tech"] > 0:
                z_p_tech = (res["pqi_tech"] - mu_pqi_tech) / sigma_pqi_tech
                z_v_tech = (res["vdi_tech"] - mu_vdi_tech) / sigma_vdi_tech
                g_tech = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_p_tech + GSI_WEIGHT_VDI * z_v_tech)
                player_tech_gsi_map[key] = (g_tech, z_p_tech, z_v_tech)
            else:
                player_tech_gsi_map[key] = (0.0, 0.0, 0.0)

        # -------------------------------------------------------------
        # GLOBAL DISCIPLINE LEADERBOARD RANKINGS (Ranked by Discipline GSI)
        # -------------------------------------------------------------
        global_fs_players = [
            (k, player_fs_gsi_map[k][0], engine_player_results[k]["pqi_fs"])
            for k in player_keys
            if engine_player_results[k]["count_fs"] > 0
        ]
        global_fs_players.sort(key=lambda x: (x[1], x[2]), reverse=True)
        global_fs_ranks = {k: rk for rk, (k, _, _) in enumerate(global_fs_players, start=1)}

        global_tech_players = [
            (k, player_tech_gsi_map[k][0], engine_player_results[k]["pqi_tech"])
            for k in player_keys
            if engine_player_results[k]["count_tech"] > 0
        ]
        global_tech_players.sort(key=lambda x: (x[1], x[2]), reverse=True)
        global_tech_ranks = {k: rk for rk, (k, _, _) in enumerate(global_tech_players, start=1)}

        combined_players = []
        for idx, key in enumerate(player_keys):
            meta = all_players_meta[key]
            res = engine_player_results[key]
            is_active = bool(active_mask[idx])

            pqi_val = res["pqi"]
            vdi_val = res["vdi"]

            z_pqi = (pqi_val - mu_pqi) / sigma_pqi
            z_vdi = (vdi_val - mu_vdi) / sigma_vdi

            gsi = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_pqi + GSI_WEIGHT_VDI * z_vdi)

            # Build 2-Domain Discipline Profile
            fs_cnt = res["count_fs"]
            tech_cnt = res["count_tech"]
            tot_fs = domain_totals_map.get("Fullspeed", 37)
            tot_tech = domain_totals_map.get("Technical", 41)

            fs_gsi, z_pqi_fs, z_vdi_fs = player_fs_gsi_map[key]
            tech_gsi, z_pqi_tech, z_vdi_tech = player_tech_gsi_map[key]

            discipline_profile = {
                "primary_discipline": res["archetype"],
                "archetype": res["archetype"],
                "bias_ratio": res["discipline_bias"],
                "fullspeed_pct": round(res["discipline_bias"] * 100, 1),
                "technical_pct": round((1.0 - res["discipline_bias"]) * 100, 1),
                "fullspeed": {
                    "gsi": round(fs_gsi, 2),
                    "pqi": res["pqi_fs"],
                    "vdi": res["vdi_fs"],
                    "z_pqi": round(z_pqi_fs, 4),
                    "z_vdi": round(z_vdi_fs, 4),
                    "rating": res["pqi_fs"],  # Backward compatibility alias
                    "raw_score": res["raw_fs"],
                    "raw_vdi": res["raw_vdi_fs"],
                    "global_rank": global_fs_ranks.get(key, 0),
                    "tracks_driven": fs_cnt,
                    "total_tracks": tot_fs,
                    "coverage_pct": round((fs_cnt / tot_fs * 100.0), 1) if tot_fs > 0 else 0.0,
                    "wr_count": res["wr_fs"],
                    "top3_count": res["t3_fs"],
                    "top5_count": res["t5_fs"],
                    "top10_count": res["t10_fs"]
                },
                "technical": {
                    "gsi": round(tech_gsi, 2),
                    "pqi": res["pqi_tech"],
                    "vdi": res["vdi_tech"],
                    "z_pqi": round(z_pqi_tech, 4),
                    "z_vdi": round(z_vdi_tech, 4),
                    "rating": res["pqi_tech"],  # Backward compatibility alias
                    "raw_score": res["raw_tech"],
                    "raw_vdi": res["raw_vdi_tech"],
                    "global_rank": global_tech_ranks.get(key, 0),
                    "tracks_driven": tech_cnt,
                    "total_tracks": tot_tech,
                    "coverage_pct": round((tech_cnt / tot_tech * 100.0), 1) if tot_tech > 0 else 0.0,
                    "wr_count": res["wr_tech"],
                    "top3_count": res["t3_tech"],
                    "top5_count": res["t5_tech"],
                    "top10_count": res["t10_tech"]
                },
                # Compatibility structure
                "styles": {
                    "Fullspeed": {
                        "style": "Fullspeed",
                        "gsi": round(fs_gsi, 2),
                        "pqi": res["pqi_fs"],
                        "vdi": res["vdi_fs"],
                        "style_pqi": res["pqi_fs"],
                        "global_rank": global_fs_ranks.get(key, 0),
                        "tracks_driven": fs_cnt,
                        "total_tracks": tot_fs,
                        "coverage_pct": round((fs_cnt / tot_fs * 100.0), 1) if tot_fs > 0 else 0.0,
                        "wr_count": res["wr_fs"],
                        "top3_count": res["t3_fs"],
                        "top5_count": res["t5_fs"],
                        "top10_count": res["t10_fs"],
                        "strength_pct": round(res["discipline_bias"] * 100, 1)
                    },
                    "Technical": {
                        "style": "Technical",
                        "gsi": round(tech_gsi, 2),
                        "pqi": res["pqi_tech"],
                        "vdi": res["vdi_tech"],
                        "style_pqi": res["pqi_tech"],
                        "global_rank": global_tech_ranks.get(key, 0),
                        "tracks_driven": tech_cnt,
                        "total_tracks": tot_tech,
                        "coverage_pct": round((tech_cnt / tot_tech * 100.0), 1) if tot_tech > 0 else 0.0,
                        "wr_count": res["wr_tech"],
                        "top3_count": res["t3_tech"],
                        "top5_count": res["t5_tech"],
                        "top10_count": res["t10_tech"],
                        "strength_pct": round((1.0 - res["discipline_bias"]) * 100, 1)
                    }
                }
            }

            combined_players.append({
                "username": meta["canonical_nickname"],
                "userId": meta["userId"],
                "gsi": round(gsi, 2),
                "z_pqi": round(z_pqi, 4),
                "z_vdi": round(z_vdi, 4),
                "discipline_profile": discipline_profile,
                "engine1": {
                    "pqi": res["pqi"],
                    "raw_pqi": res["raw_pqi"],
                    "top_scores": res["top_scores_pqi"],
                    "wr_main_count": res["wr_main_count"],
                    "wr_comm_count": res["wr_comm_count"],
                    "wr_total_count": res["wr_total_count"],
                    "top3_count": res["top3_count"],
                    "top5_count": res["top5_count"],
                    "top10_count": res["top10_count"],
                    "main_tracks_count": res["main_tracks_count"],
                    "comm_tracks_count": res["comm_tracks_count"],
                    "total_tracks_count": res["total_tracks_count"],
                    "classification": res["classification"],
                    "domain_bias": res["domain_bias"],
                    "breakdown": res["breakdown"]
                },
                "engine2": {
                    "vdi": res["vdi"],
                    "raw_vdi": res["raw_vdi"],
                    "top_scores": res["top_scores_vdi"],
                    "is_active": is_active
                },
                "classification": res["classification"],
                "domain_bias": res["domain_bias"]
            })

        # Primary sort by GSI descending
        combined_players.sort(key=lambda x: x["gsi"], reverse=True)
        for rank_idx, p in enumerate(combined_players, start=1):
            p["gsi_rank"] = rank_idx
            p["rank"] = rank_idx

        # Compute individual rankings for PQI and VDI
        pqi_sorted = sorted(combined_players, key=lambda x: x["engine1"]["pqi"], reverse=True)
        for p_rank, p in enumerate(pqi_sorted, start=1):
            p["pqi_rank"] = p_rank

        vdi_sorted = sorted(combined_players, key=lambda x: x["engine2"]["vdi"], reverse=True)
        for v_rank, p in enumerate(vdi_sorted, start=1):
            p["vdi_rank"] = v_rank

        # Compute v10.6 Highest-ROI Strategic Targets for players (Pre-computed for Top 25 players for reports)
        for idx, p in enumerate(combined_players):
            p_scores_map = {tr: rec["base_score"] for tr, rec in p["engine1"]["breakdown"].items()}
            p_ranks_map = {tr: rec["rank"] for tr, rec in p["engine1"]["breakdown"].items()}
            p_pqi = p["engine1"]["pqi"]
            p_vdi = p["engine2"]["vdi"]
            p_gsi = p["gsi"]

            p_i_star_eff = calculate_normalized_skill_intensity(p_scores_map, track_stats)
            p["i_star_eff"] = p_i_star_eff
            p["s_star_eff"] = p_i_star_eff

            if idx < 25:
                p["strategic_targets"] = evaluate_candidate_tracks_roi(
                    player_scores_map=p_scores_map,
                    player_ranks_map=p_ranks_map,
                    all_tracks_dict=track_stats,
                    current_pqi=p_pqi,
                    current_vdi=p_vdi,
                    current_gsi=p_gsi,
                    mu_pqi=mu_pqi,
                    sigma_pqi=sigma_pqi,
                    mu_vdi=mu_vdi,
                    sigma_vdi=sigma_vdi,
                    top_n=3
                )
            else:
                p["strategic_targets"] = []

        total_elapsed = time.monotonic() - t_start
        print(f"Complete v10.2 Pure Leaderboard computation finished in {total_elapsed:.2f}s.")

        return {
            "metadata": {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "total_tracks": len(cleaned_tracks),
                "main_tracks_count": len(self.registry.main_tracks),
                "community_tracks_count": len(self.registry.community_tracks),
                "total_unique_players": n_players,
                "active_players_count": int(np.sum(active_mask)),
                "active_min_tracks_threshold": self.active_min_tracks,
                "pqi_top_k": self.engine_pqi.top_k,
                "pqi_gamma": self.engine_pqi.gamma,
                "vdi_top_k": self.engine_vdi.top_k,
                "vdi_gamma": self.engine_vdi.gamma,
                "discipline_top_k": DISCIPLINE_TOP_K,
                "discipline_gamma": DISCIPLINE_GAMMA,
                "wr_crown_multiplier": WR_CROWN_MULTIPLIER,
                "dynamic_weight_formula": "clamp(1.0 + 0.18 * log10(N_k / 100,000), 0.65, 1.85)",
                "pqi_formula": "[sum_{r=1}^{min(6, m)} (0.85)^(r-1) * S_{(r)}] / [sum_{r=1}^6 (0.85)^(r-1)]",
                "vdi_formula": "[sum_{r=1}^{min(15, m)} (0.90)^(r-1) * S_{(r)}] / [sum_{r=1}^15 (0.90)^(r-1)]",
                "gsi_formula": "1000 + 200 * (0.70 * Z_pqi + 0.30 * Z_vdi)",
                "discipline_totals": domain_totals_map,
                "subgenre_totals": subgenre_totals_map,
                "track_stats": track_stats
            },
            "players": combined_players
        }


# =====================================================================
# Terminal & Markdown Display Formatters
# =====================================================================

def print_terminal_tables(report: Dict[str, Any], top_n: int = 50):
    """Print rich terminal summary tables for Top Players and Bridge Anchors."""
    players = report["players"]
    meta = report["metadata"]

    print("\n" + "=" * 125)
    print("                POLYTRACK GLOBAL PLAYER POWER RANKING SYSTEM (v10.0 Pure Leaderboard)")
    print(f"       78 Tracks ({meta['main_tracks_count']} Main + {meta['community_tracks_count']} Community) | {meta['total_unique_players']} Unique Competitors")
    print("       Ranked by Global Skill Index (GSI): 70% Peak Ceiling (PQI Top 6) + 30% Sustained Depth (VDI Top 15)")
    print("=" * 125)
    print(f"| {'Rank':<5} | {'Username':<22} | {'GSI Score':<11} | {'PQI (Ceil)':<11} | {'VDI (Depth)':<12} | {'WRs (M/C)':<10} | {'Top 5s':<8} | {'Tracks':<8} | {'Classification':<18} |")
    print("|-------|------------------------|-------------|-------------|--------------|------------|----------|----------|--------------------|")

    for p in players[:top_n]:
        e1 = p["engine1"]
        e2 = p["engine2"]
        wrs_str = f"{e1['wr_main_count']}/{e1['wr_comm_count']}"
        tracks_str = f"{e1['main_tracks_count']}+{e1['comm_tracks_count']}"
        print(
            f"| {p['gsi_rank']:<5} "
            f"| {ascii_safe(p['username']):<22} "
            f"| {p['gsi']:<11.1f} "
            f"| {e1['pqi']:<11.2f} "
            f"| {e2['vdi']:<12.2f} "
            f"| {wrs_str:<10} "
            f"| {e1['top5_count']:<8} "
            f"| {tracks_str:<8} "
            f"| {p['classification']:<18} |"
        )
    print("=" * 125)

    # All Rounder Competitor Spotlight Table
    all_rounder_players = [p for p in players if p["classification"] == "All Rounder"]
    if all_rounder_players:
        print("\n" + "=" * 105)
        print("                  CROSS-DOMAIN ALL ROUNDERS SPOTLIGHT (Balanced Competitors)")
        print("=" * 105)
        print(f"| {'GSI Rank':<9} | {'Username':<22} | {'GSI Score':<11} | {'PQI (Ceil)':<11} | {'VDI (Depth)':<12} | {'Tracks (M/C)':<13} | {'WRs Total':<10} |")
        print("|-----------|------------------------|-------------|-------------|--------------|---------------|------------|")
        for gp in all_rounder_players[:25]:
            e1 = gp["engine1"]
            e2 = gp["engine2"]
            tracks_str = f"{e1['main_tracks_count']}/{e1['comm_tracks_count']}"
            print(
                f"| {gp['gsi_rank']:<9} "
                f"| {ascii_safe(gp['username']):<22} "
                f"| {gp['gsi']:<11.1f} "
                f"| {e1['pqi']:<11.2f} "
                f"| {e2['vdi']:<12.2f} "
                f"| {tracks_str:<13} "
                f"| {e1['wr_total_count']:<10} |"
            )
        print("=" * 105)


def generate_markdown_report(report: Dict[str, Any], output_path: str):
    """Generate a comprehensive Markdown report with tables, methodologies, and highlights."""
    meta = report["metadata"]
    players = report["players"]

    lines = []
    lines.append("# PolyTrack Global Player Power Ranking Report\n")
    lines.append(f"**Generated:** {meta['generated_at']}  ")
    lines.append(f"**Ecosystem Coverage:** {meta['total_tracks']} Tracks ({meta['main_tracks_count']} Main Tracks, {meta['community_tracks_count']} Community Tracks)  ")
    lines.append(f"**Total Analyzed Competitors:** {meta['total_unique_players']} players ({meta['active_players_count']} established competitors)\n")

    lines.append("## 1. System Architecture & Algorithmic Summary\n")
    lines.append("This leaderboard measures true mechanical peak skill and sustained competitive excellence across PolyTrack using Pure Leaderboard Evaluation:")
    lines.append("1. **Dynamic Strength-of-Field (SoF) Multipliers:** $\\omega_k = \\text{clamp}\\left(1.0 + 0.18 \\cdot \\log_{10}\\left(\\frac{N_k}{100,000}\\right), 0.65, 1.85\\right)$.")
    lines.append("2. **Smooth Logarithmic Decay & WR Crown Multiplier (1.25x):** $S_{i,k} = \\omega_k \\cdot 100.0 \\cdot \\frac{1}{1 + 0.6 \\ln(\\text{Rank})} \\cdot \\mathbb{I}_{\\text{WR}}(1.25)$.")
    lines.append("3. **Engine 1 (Peak Quality Index - PQI):** Evaluates each competitor's **Top 6 best tracks** (Full-window mechanical ceiling with zero-padding for unplayed slots).")
    lines.append("4. **Engine 2 (Versatility & Depth Index - VDI):** Evaluates each competitor's **Top 15 best tracks** (Full-window sustained depth and versatility with zero-padding for unplayed slots).")
    lines.append("5. **Engine 3 (Global Skill Index - GSI Composite):** Synthesizes Peak Ceiling ($70\\%$) and Sustained Versatility ($30\\%$): $\\text{GSI} = 1000 + 200 \\cdot (0.70 \\cdot Z_{\\text{PQI}} + 0.30 \\cdot Z_{\\text{VDI}})$.\n")

    lines.append("## 2. Global Power Rankings (Top 100 by GSI)\n")
    lines.append("| Rank | Username | Global Skill Index (GSI) | Peak Quality Index (PQI) | Versatility Depth Index (VDI) | WRs (Main/Comm) | Top 5s | Tracks Ranked | Classification |")
    lines.append("|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---|")

    for p in players[:100]:
        e1 = p["engine1"]
        e2 = p["engine2"]
        wrs = f"{e1['wr_main_count']} / {e1['wr_comm_count']}"
        tracks = f"{e1['main_tracks_count']} + {e1['comm_tracks_count']}"
        lines.append(
            f"| **{p['gsi_rank']}** | **{p['username']}** | **{p['gsi']:.1f}** | {e1['pqi']:.2f} | {e2['vdi']:.2f} | {wrs} | {e1['top5_count']} | {tracks} | `{p['classification']}` |"
        )

    lines.append("\n## 3. Cross-Domain All Rounder Players\n")
    lines.append("All Rounder players compete actively across both Main and Community tracks, bridging calibration across domains.\n")
    lines.append("| GSI Rank | Username | GSI Score | Peak Quality Index (PQI) | Versatility Depth Index (VDI) | Main Tracks | Comm Tracks | Total WRs |")
    lines.append("|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|")

    all_rounders = [p for p in players if p["classification"] == "All Rounder"]
    for gp in all_rounders[:30]:
        e1 = gp["engine1"]
        e2 = gp["engine2"]
        lines.append(
            f"| {gp['gsi_rank']} | **{gp['username']}** | {gp['gsi']:.1f} | {e1['pqi']:.2f} | {e2['vdi']:.2f} | {e1['main_tracks_count']} / 17 | {e1['comm_tracks_count']} / 61 | {e1['wr_total_count']} |"
        )

    lines.append("\n## 4. Top Peak Quality Titans (Top 6 Mechanical Ceiling PQI)\n")
    lines.append("| PQI Rank | Username | Peak Quality Index (PQI) | Raw Intensity | Total WRs | Main WRs | Comm WRs | GSI Score |")
    lines.append("|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|")
    pqi_specialists = sorted(players, key=lambda x: x["engine1"]["pqi"], reverse=True)
    for ps in pqi_specialists[:20]:
        e1 = ps["engine1"]
        lines.append(
            f"| {ps['pqi_rank']} | **{ps['username']}** | {e1['pqi']:.2f} | {e1['raw_pqi']:.2f} | {e1['wr_total_count']} | {e1['wr_main_count']} | {e1['wr_comm_count']} | {ps['gsi']:.1f} |"
        )

    lines.append("\n## 5. Top Versatility Titans (Top 15 Sustained Depth VDI)\n")
    lines.append("| VDI Rank | Username | Versatility Depth (VDI) | Raw Intensity | Total WRs | Main WRs | Comm WRs | GSI Score |")
    lines.append("|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|")
    vdi_specialists = sorted(players, key=lambda x: x["engine2"]["vdi"], reverse=True)
    for vs in vdi_specialists[:20]:
        e1 = vs["engine1"]
        e2 = vs["engine2"]
        lines.append(
            f"| {vs['vdi_rank']} | **{vs['username']}** | {e2['vdi']:.2f} | {e2['raw_vdi']:.2f} | {e1['wr_total_count']} | {e1['wr_main_count']} | {e1['wr_comm_count']} | {vs['gsi']:.1f} |"
        )

    lines.append("\n## 6. 2-Domain Macro-Discipline Leaderboards (v10.2 Dual-Axis Mastery)\n")
    lines.append("Evaluation of top global drivers by **Discipline GSI** synthesized from peak ceiling (PQI Top 6) and sustained depth (VDI Top 15) evaluated strictly on tracks from each discipline.\n")

    for dom in DISCIPLINE_DOMAINS:
        lines.append(f"### {dom} Discipline Leaderboard (Top 20)\n")
        lines.append(f"| Rank in {dom} | Username | {dom} GSI | PQI (Ceil) | VDI (Depth) | Track Coverage | World Records | Top 5s | Archetype | Global GSI |")
        lines.append("|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

        dom_key = dom.lower()
        sorted_dom = sorted(
            [p for p in players if p.get("discipline_profile", {}).get(dom_key, {}).get("tracks_driven", 0) > 0],
            key=lambda x: (x["discipline_profile"][dom_key].get("gsi", 0), x["discipline_profile"][dom_key].get("pqi", 0)),
            reverse=True
        )

        for sp in sorted_dom[:20]:
            sd = sp["discipline_profile"][dom_key]
            cov = f"{sd['tracks_driven']} / {sd['total_tracks']} ({sd['coverage_pct']}%)"
            lines.append(
                f"| **#{sd['global_rank']}** | **{sp['username']}** | **{sd.get('gsi', 0):.1f}** | {sd.get('pqi', 0):.2f} | {sd.get('vdi', 0):.2f} | {cov} | {sd['wr_count']} | {sd['top5_count']} | `{sp['discipline_profile']['archetype']}` | {sp['gsi']:.1f} |"
            )
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated comprehensive Markdown report: '{output_path}'")


def generate_secondary_exports(
    raw_leaderboards: Dict[str, List[Dict[str, Any]]],
    report: Dict[str, Any],
    scraped_json_path: Optional[str] = "all_scraped_data.json",
    top20_condensed_path: Optional[str] = "top20_condensed.csv",
    top20_md_path: Optional[str] = "top20_track_breakdown.md",
    html_path: Optional[str] = "methodology.html",
    index_html_path: Optional[str] = None,
    alt_mappings: Optional[Dict[str, str]] = None,
    blacklisted_players: Optional[Set[str]] = None
):
    """Generate secondary exports:
    1. Complete scraped dataset for all 78 tracks in JSON.
    2. Ultra-condensed minimal CSV for Top 20 players (sorted by GSI): 1 row per player.
    3. Formatted Markdown breakdown for Top 20 players.
    4. Auto-update interactive methodology.html with latest rankings dataset.
    """
    meta = report["metadata"]
    track_stats = meta.get("track_stats", {})
    players = report["players"]
    top20_players = players[:20]

    # Structure 1: Ultra-Condensed Top 20 Player Individual Data (1 Row Per Player, Minimal File Size)
    if top20_condensed_path:
        csv_lines = ["player,track_players,rank..."]
        for p in top20_players:
            p_name = p["username"].replace("\n", " ").strip()
            if "," in p_name:
                p_name = f'"{p_name}"'

            e1 = p["engine1"]
            breakdown = e1.get("breakdown", {})

            sorted_tracks = sorted(breakdown.items(), key=lambda x: x[1].get("rank", 999))
            row_items = [p_name]
            for tr_name, rec in sorted_tracks:
                tot_players = track_stats.get(tr_name, {}).get("total_players", 0)
                rank_val = rec.get("rank", 0)
                row_items.append(str(tot_players))
                row_items.append(str(rank_val))

            csv_lines.append(",".join(row_items))

        with open(top20_condensed_path, "w", encoding="utf-8") as f:
            f.write("\n".join(csv_lines) + "\n")
        print(f"Saved ultra-condensed Top 20 track data to '{top20_condensed_path}' (Lines: {len(csv_lines)})")

    # Structure 2: Complete Scraped Dataset for All 78 Tracks
    if scraped_json_path:
        all_scraped_data = {}
        for tr_name, entries in raw_leaderboards.items():
            t_stat = track_stats.get(tr_name, {})
            cleaned_entries = process_raw_leaderboard(
                entries,
                alt_mappings=alt_mappings,
                blacklisted_players=blacklisted_players
            )
            all_scraped_data[tr_name] = {
                "track_name": tr_name,
                "is_main": t_stat.get("is_main", False),
                "domain": t_stat.get("domain", "Fullspeed"),
                "subgenre": t_stat.get("subgenre", "FS"),
                "style": t_stat.get("subgenre", "FS"),
                "track_total_players": t_stat.get("total_players", 0),
                "dynamic_weight": t_stat.get("dynamic_weight", 1.0),
                "scraped_count": len(cleaned_entries),
                "entries": [
                    {
                        "rank": e["rank"],
                        "nickname": e.get("canonicalNickname", e["nickname"]),
                        "userId": e["userId"],
                        "time_seconds": e["time_sec"]
                    }
                    for e in cleaned_entries
                ]
            }

        scraped_payload = {
            "metadata": {
                "generated_at": meta["generated_at"],
                "total_tracks": meta["total_tracks"],
                "total_unique_competitors": meta["total_unique_players"],
                "active_competitors": meta["active_players_count"],
                "description": "Complete scraped leaderboard entries across all 78 PolyTrack tracks."
            },
            "tracks": all_scraped_data
        }

        with open(scraped_json_path, "w", encoding="utf-8") as f:
            json.dump(scraped_payload, f, indent=2, ensure_ascii=False)
        print(f"Saved complete scraped dataset to '{scraped_json_path}'")

        # Top 20 combined release
        top20_payload = {
            "metadata": {
                "generated_at": meta["generated_at"],
                "total_tracks": meta["total_tracks"],
                "total_unique_competitors": meta["total_unique_players"],
                "active_competitors": meta["active_players_count"],
                "description": "Comprehensive release of all scraped leaderboard entries and individual track rankings for the Top 20 Global Power Ranked players with 2-domain discipline profiles."
            },
            "top_20_power_ranking_players": top20_players,
            "all_scraped_tracks": all_scraped_data
        }
        top20_combined_path = resolve_target_path("scraped_data_and_top20_rankings.json")
        with open(top20_combined_path, "w", encoding="utf-8") as f:
            json.dump(top20_payload, f, indent=2, ensure_ascii=False)
        print(f"Saved Top 20 rankings & scraped data to '{top20_combined_path}'")

    # Structure 3: Formatted Markdown Breakdown for Top 20
    if top20_md_path:
        md_lines = []
        md_lines.append("# Top 20 Global Players: Individual Track Rankings & Player Counts\n")
        md_lines.append(f"**Generated:** {meta['generated_at']}  ")
        md_lines.append("This document contains the exact leaderboard finish, time, points, and total track player count ($N_k$) for every track played by the Top 20 players on the Global Power Rankings (sorted by GSI).\n")

        for p in top20_players:
            e1 = p["engine1"]
            e2 = p["engine2"]
            dp = p.get("discipline_profile", {})
            breakdown = e1.get("breakdown", {})
            sorted_tracks = sorted(breakdown.items(), key=lambda x: x[1].get("rank", 999))
            fs_d = dp.get("fullspeed", {})
            tech_d = dp.get("technical", {})

            md_lines.append(f"## #{p['gsi_rank']} {p['username']}")
            md_lines.append(f"- **Global Skill Index (GSI):** **{p['gsi']:.1f}** (Rank #{p['gsi_rank']})")
            md_lines.append(f"- **Primary Archetype:** `{dp.get('archetype', 'Competitor')}` (Discipline Balance: {dp.get('fullspeed_pct', 50)}% Fullspeed | {dp.get('technical_pct', 50)}% Technical)")
            md_lines.append(f"- **Fullspeed Discipline:** **{fs_d.get('gsi', 0):.1f} GSI** (Rank #{fs_d.get('global_rank', 'N/A')}, PQI: {fs_d.get('pqi', 0):.2f}, VDI: {fs_d.get('vdi', 0):.2f}) | **Technical Discipline:** **{tech_d.get('gsi', 0):.1f} GSI** (Rank #{tech_d.get('global_rank', 'N/A')}, PQI: {tech_d.get('pqi', 0):.2f}, VDI: {tech_d.get('vdi', 0):.2f})")
            md_lines.append(f"- **Peak Ceiling (PQI Top 6):** {e1['pqi']:.2f} (Rank #{p['pqi_rank']}) | **Sustained Depth (VDI Top 15):** {e2['vdi']:.2f} (Rank #{p['vdi_rank']})")
            md_lines.append(f"- **World Records:** {e1['wr_total_count']} ({e1['wr_main_count']} Main, {e1['wr_comm_count']} Comm) | **Classification:** `{p['classification']}`")
            md_lines.append(f"- **Total Tracks Driven:** {len(sorted_tracks)} / {meta['total_tracks']}")
            md_lines.append("")
            md_lines.append("| Rank on Track | Time (s) | Track Player Count ($N_k$) | Dynamic Weight ($\\omega_k$) | Points Earned | Track Category & Subgenre (Name) |")
            md_lines.append("|:---:|:---:|:---:|:---:|:---:|:---|")

            for tr_name, rec in sorted_tracks:
                t_stat = track_stats.get(tr_name, {})
                tot_players = t_stat.get("total_players", 0)
                cat = "Main Track" if t_stat.get("is_main", False) else "Community Track"
                tr_subg = rec.get("subgenre", t_stat.get("subgenre", "FS"))
                tr_dom = rec.get("domain", t_stat.get("domain", "Fullspeed"))
                md_lines.append(
                    f"| **#{rec['rank']}** | {rec['time_sec']:.3f}s | {tot_players:,} | {rec['weight']:.4f} | {rec['base_score']:.2f} | {cat} `[{tr_subg}]` ({tr_name}) |"
                )
            md_lines.append("\n---\n")

        with open(top20_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"Saved Top 20 track rankings breakdown to '{top20_md_path}'")

    # Structure 4: Auto-update methodology.html
    if html_path:
        update_methodology_html(report, html_path=html_path, index_path=index_html_path)


def resolve_target_path(filepath: Optional[str]) -> Optional[str]:
    """Resolve file paths so that default relative filenames save inside the power_rankings directory."""
    if not filepath:
        return filepath
    if os.path.isabs(filepath):
        return filepath
    if os.path.dirname(filepath):
        return filepath
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, filepath)


def update_methodology_html(report: Dict[str, Any], html_path: str = "methodology.html", index_path: Optional[str] = None) -> bool:
    """Update embedded player dataset and dynamic summary counters in methodology.html."""
    resolved_path = resolve_target_path(html_path)
    if resolved_path and os.path.exists(resolved_path):
        html_path = resolved_path
    elif not os.path.exists(html_path):
        # Try relative to workspace root
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        alt_path = os.path.join(base_dir, html_path)
        if os.path.exists(alt_path):
            html_path = alt_path
        else:
            print(f"Warning: HTML file '{html_path}' not found. Skipping HTML update.")
            return False

    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        players = report["players"]
        meta = report.get("metadata", {})
        track_stats = meta.get("track_stats", {})
        total_players = len(players)
        if total_players == 0:
            return False

        champ = players[0]
        wr_holders = sum(1 for p in players if p["engine1"]["wr_total_count"] > 0)

        # Classification counts
        class_counts = {}
        for p in players:
            c = p.get("classification", "Generalist")
            class_counts[c] = class_counts.get(c, 0) + 1

        # Track mappings
        track_subgenres_dict = {
            tname: tdata.get("subgenre", "FS")
            for tname, tdata in track_stats.items()
        }
        track_domains_dict = {
            tname: tdata.get("domain", "Fullspeed")
            for tname, tdata in track_stats.items()
        }
        track_styles_dict = track_subgenres_dict  # Compatibility alias
        track_styles_json = json.dumps(track_styles_dict, separators=(',', ':'), ensure_ascii=False)
        track_domains_json = json.dumps(track_domains_dict, separators=(',', ':'), ensure_ascii=False)

        # Track Weights Dataset for all 78 tracks, ordered by weight descending
        track_weights_list = []
        for tr_name, tdata in track_stats.items():
            w_k = tdata.get("dynamic_weight", 1.0)
            tot_p = tdata.get("total_players", 0)
            is_m = tdata.get("is_main", False)
            dom_k = tdata.get("domain", "Fullspeed")
            subg_k = tdata.get("subgenre", "FS")
            wr_score = round(calculate_smooth_track_score(1, w_k), 1)
            track_weights_list.append({
                "t": tr_name,
                "m": is_m,
                "d": dom_k,
                "y": subg_k,
                "p": tot_p,
                "w": round(w_k, 4),
                "wr": wr_score,
                "s": tdata.get("scraped_entries", 0)
            })

        track_weights_list.sort(key=lambda x: (x["w"], x["p"]), reverse=True)
        for idx, trk in enumerate(track_weights_list, 1):
            trk["r"] = idx
        track_weights_json = json.dumps(track_weights_list, separators=(',', ':'), ensure_ascii=False)

        # Build compact minified JSON for methodology.html
        minified_players = []
        for p in players:
            e1 = p["engine1"]
            e2 = p["engine2"]
            dp = p.get("discipline_profile", {})
            breakdown = e1.get("breakdown", {})

            # All driven tracks sorted by base_score descending
            sorted_trks = sorted(
                breakdown.items(),
                key=lambda x: x[1].get("base_score", 0),
                reverse=True
            )
            trk_list = [
                {
                    "t": tname,
                    "r": tdata["rank"],
                    "s": round(tdata["base_score"], 1),
                    "w": round(tdata["weight"], 3),
                    "y": tdata.get("subgenre", track_subgenres_dict.get(tname, "FS")),
                    "d": tdata.get("domain", track_domains_dict.get(tname, "Fullspeed"))
                }
                for tname, tdata in sorted_trks
            ]

            # 2-Domain profile summary: [GSI, PQI, VDI, Rank, Driven, Total, WRs, Top5s]
            fs_info = dp.get("fullspeed", {})
            tech_info = dp.get("technical", {})

            minified_players.append({
                "r": p["gsi_rank"],
                "u": p["username"],
                "g": round(p["gsi"], 1),
                "p": round(e1["pqi"], 2),
                "v": round(e2["vdi"], 2),
                "zp": round(p["z_pqi"], 2),
                "zv": round(p["z_vdi"], 2),
                "wm": e1["wr_main_count"],
                "wc": e1["wr_comm_count"],
                "wt": e1["wr_total_count"],
                "t3": e1["top3_count"],
                "t5": e1["top5_count"],
                "t10": e1["top10_count"],
                "tm": e1["main_tracks_count"],
                "tc": e1["comm_tracks_count"],
                "tt": e1["total_tracks_count"],
                "c": p["classification"],
                "db": round(p["domain_bias"] * 100, 1),
                "dp": {
                    "a": dp.get("archetype", "Player"),
                    "b": dp.get("bias_ratio", 0.5),
                    "f": [
                        round(fs_info.get("gsi", 0.0), 1),
                        round(fs_info.get("pqi", 0.0), 2),
                        round(fs_info.get("vdi", 0.0), 2),
                        fs_info.get("global_rank", 0),
                        fs_info.get("tracks_driven", 0),
                        fs_info.get("total_tracks", 36),
                        fs_info.get("wr_count", 0),
                        fs_info.get("top5_count", 0)
                    ],
                    "t": [
                        round(tech_info.get("gsi", 0.0), 1),
                        round(tech_info.get("pqi", 0.0), 2),
                        round(tech_info.get("vdi", 0.0), 2),
                        tech_info.get("global_rank", 0),
                        tech_info.get("tracks_driven", 0),
                        tech_info.get("total_tracks", 42),
                        tech_info.get("wr_count", 0),
                        tech_info.get("top5_count", 0)
                    ]
                },
                "trk": trk_list
            })

        players_json = json.dumps(minified_players, separators=(',', ':'), ensure_ascii=False)

        # 0. Update or inject TRACK_DOMAINS, TRACK_SUBGENRES, TRACK_STYLES, TRACK_WEIGHTS_DATA
        if "const TRACK_DOMAINS =" in html:
            html = re.sub(
                r'const TRACK_DOMAINS = \{.*?\};',
                lambda m: f'const TRACK_DOMAINS = {track_domains_json};',
                html,
                flags=re.DOTALL
            )
        if "const TRACK_SUBGENRES =" in html:
            html = re.sub(
                r'const TRACK_SUBGENRES = \{.*?\};',
                lambda m: f'const TRACK_SUBGENRES = {track_styles_json};',
                html,
                flags=re.DOTALL
            )
        if "const TRACK_STYLES =" in html:
            html = re.sub(
                r'const TRACK_STYLES = \{.*?\};',
                lambda m: f'const TRACK_STYLES = {track_styles_json};',
                html,
                flags=re.DOTALL
            )
        if "const TRACK_WEIGHTS_DATA =" in html:
            html = re.sub(
                r'const TRACK_WEIGHTS_DATA = \[.*?\];',
                lambda m: f'const TRACK_WEIGHTS_DATA = {track_weights_json};',
                html,
                flags=re.DOTALL
            )

        # 1. Update PLAYERS array and comment (use lambda to prevent backslash interpretation)
        html = re.sub(
            r'// Embedded Player Dataset \([\d,]+ (?:Competitors|Players)\)\s+const PLAYERS = \[.*?\];',
            lambda m: f'// Embedded Player Dataset ({total_players:,} Players)\n    const PLAYERS = {players_json};',
            html,
            flags=re.DOTALL
        )

        # 2. Update tab counter
        html = re.sub(
            r'(<button class="tab-btn active" id="tab-btn-rankings".*?<span class="tab-counter">)[\d,]+(</span>)',
            rf'\g<1>{total_players:,}\g<2>',
            html,
            flags=re.DOTALL
        )

        # 3. Update badge-purple in Tab 1
        html = re.sub(
            r'<span class="badge badge-purple">[\d,]+ (?:Competitors|Players)</span>',
            f'<span class="badge badge-purple">{total_players:,} Players</span>',
            html
        )

        # 4. Update subtitle
        html = re.sub(
            r'across [\d,]+ ranked (?:drivers|players)\.',
            f'across {total_players:,} ranked players.',
            html
        )

        # 5. Update Champion Stat Card
        champ_name = champ["username"]
        champ_sub = f"GSI {champ['gsi']:.1f} • {champ['engine1']['wr_total_count']} World Record{'s' if champ['engine1']['wr_total_count'] != 1 else ''}"
        html = re.sub(
            r'(<div class="stat-card stat-gold">\s*<div class="stat-label">👑 World #1 Champion</div>\s*<div class="stat-val">).*?(</div>\s*<div class="stat-sub">).*?(</div>\s*</div>)',
            rf'\g<1>{champ_name}\g<2>{champ_sub}\g<3>',
            html,
            flags=re.DOTALL
        )

        # 6. Update Total Ranked Players Card
        html = re.sub(
            r'(<div class="stat-card stat-cyan">\s*<div class="stat-label">👥 Total Ranked (?:Competitors|Players)</div>\s*<div class="stat-val">)[\d,]+(</div>)',
            rf'\g<1>{total_players:,}\g<2>',
            html,
            flags=re.DOTALL
        )

        # 7. Update WR Holders Card
        html = re.sub(
            r'(<div class="stat-card stat-green">\s*<div class="stat-label">🥇 World Record Holders</div>\s*<div class="stat-val">)[\d,]+ (?:Drivers|Players)(</div>)',
            rf'\g<1>{wr_holders:,} Players\g<2>',
            html,
            flags=re.DOTALL
        )

        # 8. Update Classification Filter Options
        filter_html = f'''<select id="class-filter" class="filter-select" onchange="handleClassFilter(this.value)" title="Filter by player classification">
                    <option value="ALL" title="All ranked players">All Classifications ({total_players:,})</option>
                    <option value="Main Specialist" title="Earns ≥70% of points on official campaign tracks">Main Specialist ({class_counts.get("Main Specialist", 0):,})</option>
                    <option value="Community Specialist" title="Earns ≥70% of points on community tracks">Community Specialist ({class_counts.get("Community Specialist", 0):,})</option>
                    <option value="All Rounder" title="Balanced points across both campaign and community tracks (neither ≥70%)">All Rounder ({class_counts.get("All Rounder", 0):,})</option>
                </select>'''
        html = re.sub(r'<select id="class-filter".*?</select>', filter_html, html, flags=re.DOTALL)

        # 9. Update Sort Option & Page Size All Option & Results summary
        html = re.sub(r'<option value="rank_asc">Sort: Rank \(1 → [\d,]+\)</option>', f'<option value="rank_asc">Sort: Rank (1 → {total_players:,})</option>', html)
        html = re.sub(r'<option value="ALL">All \([\d,]+\)</option>', f'<option value="ALL">All ({total_players:,})</option>', html)
        html = re.sub(r'of <strong>[\d,]+</strong> (?:competitors|players)', f'of <strong>{total_players:,}</strong> players', html)

        # 10. Update Last Updated Timestamp & Badges
        meta = report.get("metadata", {})
        gen_timestamp = meta.get("generated_at", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
        gen_date = gen_timestamp.split(" ")[0] if " " in gen_timestamp else gen_timestamp

        html = re.sub(
            r'<span class="badge badge-orange" id="badge-last-updated">.*?</span>',
            f'<span class="badge badge-orange" id="badge-last-updated">Last updated: {gen_date}</span>',
            html
        )
        html = re.sub(
            r'<span id="last-updated-text">.*?</span>',
            f'<span id="last-updated-text">{gen_timestamp}</span>',
            html
        )
        html = re.sub(
            r'<span id="footer-last-updated">.*?</span>',
            f'<span id="footer-last-updated">{gen_timestamp}</span>',
            html
        )

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Also sync to candidate index.html paths and root methodology.html
        candidate_indices = []
        if index_path:
            candidate_indices.append(index_path)
        else:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidate_indices.append(os.path.join(root_dir, "index.html"))
            script_dir = os.path.dirname(os.path.abspath(__file__))
            candidate_indices.append(os.path.join(script_dir, "index.html"))

        seen_indices = set()
        for idx_p in candidate_indices:
            norm_idx = os.path.normpath(os.path.abspath(idx_p))
            if norm_idx in seen_indices:
                continue
            seen_indices.add(norm_idx)
            if os.path.exists(idx_p) or index_path:
                if norm_idx != os.path.normpath(os.path.abspath(html_path)):
                    try:
                        os.makedirs(os.path.dirname(norm_idx), exist_ok=True)
                        with open(norm_idx, "w", encoding="utf-8") as f:
                            f.write(html)
                        print(f"Synchronized index.html UI: '{norm_idx}'")
                    except Exception as e_idx:
                        print(f"Note: Could not write index.html '{norm_idx}': {e_idx}")

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_mth_path = os.path.join(root_dir, "methodology.html")
        if os.path.exists(root_mth_path) and os.path.normpath(os.path.abspath(root_mth_path)) != os.path.normpath(os.path.abspath(html_path)):
            try:
                with open(root_mth_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Synchronized root methodology.html UI: '{root_mth_path}'")
            except Exception as e_mth:
                print(f"Note: Could not write root methodology.html: {e_mth}")

        return True
    except Exception as e:
        print(f"Warning: Failed updating methodology HTML '{html_path}': {e}")
        return False


# =====================================================================
# CLI Entrypoint
# =====================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="PolyTrack Global Player Power Ranking System (v10.0 Pure Leaderboard Architecture)")
    parser.add_argument("--fetch", action="store_true", help="Fetch fresh live leaderboards from API (enabled by default)")
    parser.add_argument("--cache", "--use-cache", dest="use_cache", action="store_true", help="Use local disk cache instead of fetching fresh live leaderboards from API")
    parser.add_argument("--no-cache", action="store_true", help="Do not use disk cache")
    parser.add_argument("--scrape-amount", type=int, default=1000, help="Number of entries to scrape per track (default: 1000)")
    parser.add_argument("--top-k-pqi", type=int, default=PQI_TOP_K, help="Engine 1 number of top tracks for PQI (default: 6)")
    parser.add_argument("--gamma-pqi", type=float, default=PQI_GAMMA, help="Engine 1 decay factor (default: 0.85)")
    parser.add_argument("--top-k-vdi", type=int, default=VDI_TOP_K, help="Engine 2 number of top tracks for VDI (default: 15)")
    parser.add_argument("--gamma-vdi", type=float, default=VDI_GAMMA, help="Engine 2 decay factor (default: 0.90)")
    parser.add_argument("--min-tracks", type=int, default=ACTIVE_MIN_TRACKS_DEFAULT, help="Minimum tracks for established competitor status (default: 5)")
    parser.add_argument("--top-n", type=int, default=50, help="Number of top players to print in terminal (default: 50)")
    parser.add_argument("--output-json", type=str, default="global_power_rankings.json", help="Primary rankings JSON filepath")
    parser.add_argument("--output-md", type=str, default="global_power_rankings.md", help="Primary rankings Markdown filepath")
    parser.add_argument("--scraped-json", type=str, default="all_scraped_data.json", help="Secondary JSON filepath containing ALL scraped track data")
    parser.add_argument("--top20-condensed", type=str, default="top20_condensed.csv", help="Ultra-condensed minimal CSV for Top 20 player individual data")
    parser.add_argument("--top20-md", type=str, default="top20_track_breakdown.md", help="Secondary Markdown report for Top 20 track breakdowns")
    parser.add_argument("--html", type=str, default="methodology.html", help="Path to methodology.html to update with latest rankings dataset (default: methodology.html)")
    parser.add_argument("--index-html", type=str, default=None, help="Explicit path to index.html if hosted in a custom web root directory (e.g. /var/www/html/index.html)")
    parser.add_argument("--web-only", action="store_true", help="Web-optimized run: update index.html/methodology.html and summaries without writing large raw JSON files")
    parser.add_argument("--no-html", action="store_true", help="Do not update methodology.html")
    parser.add_argument("--player", type=str, default=None, help="Inspect a specific player profile by username")
    parser.add_argument("--blacklist-player", action="append", default=[], help="Additional player username or userId to blacklist")
    return parser.parse_args()


async def async_main():
    args = parse_args()
    bl = set(BLACKLISTED_PLAYERS)
    if args.blacklist_player:
        bl.update(args.blacklist_player)

    system = PowerRankingSystem(
        top_k_pqi=args.top_k_pqi,
        gamma_pqi=args.gamma_pqi,
        top_k_vdi=args.top_k_vdi,
        gamma_vdi=args.gamma_vdi,
        active_min_tracks=args.min_tracks,
        blacklisted_players=bl
    )

    use_cache = bool(args.use_cache and not args.fetch and not args.no_cache)
    raw_leaderboards, track_totals = await system.ingest_leaderboards(
        amount=args.scrape_amount,
        use_cache=use_cache
    )

    report = system.compute_all_rankings(raw_leaderboards, track_totals=track_totals)

    # Terminal output
    print_terminal_tables(report, top_n=args.top_n)

    # Inspect single player if requested
    if args.player:
        target = normalize_identity_key(args.player)
        matched = [p for p in report["players"] if normalize_identity_key(p["username"]) == target]
        if matched:
            p = matched[0]
            e1 = p["engine1"]
            e2 = p["engine2"]
            print("\n" + "=" * 65)
            print(f"PLAYER PROFILE: {p['username']}")
            print("=" * 65)
            print(f"Global Skill Index (GSI): {p['gsi']:.1f} (Rank #{p['gsi_rank']})")
            print(f"Peak Ceiling (PQI): {e1['pqi']:.2f} (Rank #{p['pqi_rank']}) | Sustained Depth (VDI): {e2['vdi']:.2f} (Rank #{p['vdi_rank']})")
            print(f"World Records: {e1['wr_total_count']} ({e1['wr_main_count']} Main, {e1['wr_comm_count']} Comm)")
            print(f"Classification: {p['classification']} | Tracks Ranked: {e1['total_tracks_count']}")
            print(f"Top 3s: {e1['top3_count']} | Top 5s: {e1['top5_count']} | Top 10s: {e1['top10_count']}")
            print("=" * 65)
        else:
            print(f"\nPlayer '{args.player}' not found in current leaderboards.")

    output_json_path = None if args.web_only else resolve_target_path(args.output_json)
    output_md_path = resolve_target_path(args.output_md)
    scraped_json_path = None if args.web_only else resolve_target_path(args.scraped_json)
    top20_condensed_path = resolve_target_path(args.top20_condensed)
    top20_md_path = resolve_target_path(args.top20_md)
    html_target = None if args.no_html else resolve_target_path(args.html)
    index_target = args.index_html

    # Save Primary JSON report
    if output_json_path:
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nSaved full rankings JSON to '{output_json_path}'")

    # Save Primary Markdown report
    if output_md_path:
        generate_markdown_report(report, output_md_path)

    # Save Secondary Exports (All Scraped Data, Condensed Top 20 Data, and update methodology.html)
    generate_secondary_exports(
        raw_leaderboards,
        report,
        scraped_json_path=scraped_json_path,
        top20_condensed_path=top20_condensed_path,
        top20_md_path=top20_md_path,
        html_path=html_target,
        index_html_path=index_target,
        alt_mappings=system.alt_mappings,
        blacklisted_players=system.blacklisted_players
    )


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")


if __name__ == "__main__":
    main()
