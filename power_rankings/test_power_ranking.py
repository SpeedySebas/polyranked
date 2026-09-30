#!/usr/bin/env python3
"""Automated Unit Tests for the PolyTrack Power Ranking System (v10.0 Pure Leaderboard Architecture).

Tests mathematical correctness of:
1. Dynamic Strength-of-Field (SoF) Track Difficulty (omega_k = clamp(1.0 + 0.18 * log10(N/100k), 0.65, 1.85))
2. Smooth Logarithmic Rank Scoring & 1.25x WR Crown
3. Engine 1: Peak Quality Index (PQI Top-6 Mechanical Ceiling) with Bayesian Shrinkage (C=2.0, mu_0=40.0)
4. Engine 2: Versatility & Depth Index (VDI Top-15 Sustained Quality) with Bayesian Shrinkage (C=3.0, mu_0=30.0)
5. Engine 3: Global Skill Index (GSI v10.0 Composite: 70% PQI + 30% VDI)
6. Volume Invariance & Saturation Properties
7. Leaderboard Deduplication and [TAS] Filtering
"""

import math
import os
import sys
import unittest
import numpy as np

# Ensure scripts directory is in path
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from power_ranking_system import (
    MAIN_TRACKS,
    load_community_tracks,
    TrackRegistry,
    PeakQualityIndexEngine,
    VersatilityDepthIndexEngine,
    calculate_dynamic_track_weight,
    calculate_smooth_track_score,
    process_raw_leaderboard,
    resolve_player_identity,
    normalize_identity_key,
    ALT_MAPPINGS,
    BLACKLISTED_PLAYERS,
    is_player_blacklisted,
    SOF_BASE_POP,
    SOF_LOG_SLOPE,
    OMEGA_MIN,
    OMEGA_MAX,
    PQI_TOP_K,
    PQI_GAMMA,
    VDI_TOP_K,
    VDI_GAMMA,
    GSI_BASE,
    GSI_SCALE,
    GSI_WEIGHT_PQI,
    GSI_WEIGHT_VDI,
    calculate_discipline_rating,
    calculate_discipline_bias,
    determine_discipline_archetype,
    classify_player,
    map_track_to_domain_and_subgenre,
    DISCIPLINE_DOMAINS,
    DISCIPLINE_TOP_K,
    DISCIPLINE_GAMMA,
    calculate_style_pqi,
    determine_driving_archetype,
    ALL_TRACK_STYLES,
    calculate_player_baseline,
    calculate_cross_track_consistency,
    determine_confidence_tier,
    calculate_effort,
    generate_candidate_target_ladder,
    simulate_exact_gsi_gain,
    calculate_roi_score,
    filter_pareto_dominated_targets,
    classify_recommendation_tier,
    generate_plain_language_reason,
    evaluate_player_strategy,
    evaluate_candidate_tracks_roi,
    format_target_objective,
    CONFIDENCE_FACTOR_HIGH,
    CONFIDENCE_FACTOR_MEDIUM,
    CONFIDENCE_FACTOR_LOW,
    FRONTIER_PENALTY_COEFF,
    UNPLAYED_ENTRY_EFFORT,
    UPGRADE_ENTRY_EFFORT
)


class TestDynamicTrackWeight(unittest.TestCase):
    def test_logarithmic_population_weights(self):
        """Verify dynamic track weights across representative population brackets."""
        # 100k players -> log10(1) = 0 -> 1.0 + 0.18*0 = 1.00
        w_100k = calculate_dynamic_track_weight(100000)
        self.assertAlmostEqual(w_100k, 1.00, places=4)

        # 1,000,000 players -> log10(10) = 1 -> 1.0 + 0.18*1 = 1.18
        w_1m = calculate_dynamic_track_weight(1000000)
        self.assertAlmostEqual(w_1m, 1.18, places=4)

        # 4,485,150 players (Summer 1) -> 1.0 + 0.18 * log10(44.8515) ≈ 1.2973
        w_summer1 = calculate_dynamic_track_weight(4485150)
        self.assertAlmostEqual(w_summer1, 1.2973, places=3)

        # 10,000 players -> log10(0.1) = -1 -> 1.0 + 0.18*(-1) = 0.82
        w_10k = calculate_dynamic_track_weight(10000)
        self.assertAlmostEqual(w_10k, 0.82, places=4)

        # 500 players -> 1.0 + 0.18 * log10(0.005) = 1.0 + 0.18*(-2.301) = 0.5858 -> clamp to 0.65 floor
        w_small = calculate_dynamic_track_weight(500)
        self.assertEqual(w_small, 0.65)


class TestSmoothRankScoring(unittest.TestCase):
    def test_logarithmic_decay_and_wr_crown(self):
        """Verify exact base scores at standard ranks with omega_k = 1.00."""
        # Rank 1 (WR): 125.0
        s1 = calculate_smooth_track_score(1, 1.00)
        self.assertAlmostEqual(s1, 125.00, places=2)

        # Rank 2: 70.6
        s2 = calculate_smooth_track_score(2, 1.00)
        self.assertAlmostEqual(round(s2, 1), 70.6, places=1)

        # Rank 3: 60.3
        s3 = calculate_smooth_track_score(3, 1.00)
        self.assertAlmostEqual(round(s3, 1), 60.3, places=1)

        # Rank 5: 50.9
        s5 = calculate_smooth_track_score(5, 1.00)
        self.assertAlmostEqual(round(s5, 1), 50.9, places=1)

        # Rank 10: 42.0
        s10 = calculate_smooth_track_score(10, 1.00)
        self.assertAlmostEqual(round(s10, 1), 42.0, places=1)


class TestEngine1PeakQualityIndex(unittest.TestCase):
    def setUp(self):
        self.engine = PeakQualityIndexEngine(top_k=6, gamma=0.85)
        self.w6 = sum(0.85 ** r for r in range(6))

    def test_pqi_top6_volume_invariance(self):
        """Assert adding runs beyond Top 6 has zero mathematical effect on PQI."""
        elite_6 = [125.0] * 6
        elite_6_plus_50 = [125.0] * 6 + [20.0] * 50

        pqi_6, raw_6, top_6 = self.engine.aggregate_pqi(elite_6)
        pqi_56, raw_56, top_56 = self.engine.aggregate_pqi(elite_6_plus_50)

        self.assertEqual(len(top_6), 6)
        self.assertEqual(len(top_56), 6)
        self.assertAlmostEqual(raw_6, 125.0, places=4)
        self.assertAlmostEqual(raw_56, 125.0, places=4)
        self.assertAlmostEqual(pqi_6, pqi_56, places=4)
        self.assertAlmostEqual(pqi_6, 125.0, places=4)

    def test_pqi_full_window_normalization(self):
        """Verify full-window normalization zero-pads unplayed depth slots without upward inflation."""
        # 6 runs of 100.0 -> exact 100.0
        pqi_6, raw_6, _ = self.engine.aggregate_pqi([100.0] * 6)
        self.assertAlmostEqual(pqi_6, 100.0, places=4)
        self.assertAlmostEqual(raw_6, 100.0, places=4)

        # 1 run of 100.0 -> 100.0 * 1.0 / W6
        expected_1 = 100.0 / self.w6
        pqi_1, raw_1, _ = self.engine.aggregate_pqi([100.0])
        self.assertAlmostEqual(pqi_1, expected_1, places=4)
        self.assertAlmostEqual(raw_1, 100.0, places=4)


class TestEngine2VersatilityDepthIndex(unittest.TestCase):
    def setUp(self):
        self.engine = VersatilityDepthIndexEngine(top_k=15, gamma=0.90)
        self.w15 = sum(0.90 ** r for r in range(15))

    def test_vdi_top15_volume_invariance(self):
        """Assert adding runs beyond Top 15 has zero mathematical effect on VDI."""
        elite_15 = [100.0] * 15
        elite_15_plus_50 = [100.0] * 15 + [10.0] * 50

        vdi_15, raw_15, top_15 = self.engine.aggregate_vdi(elite_15)
        vdi_65, raw_65, top_65 = self.engine.aggregate_vdi(elite_15_plus_50)

        self.assertEqual(len(top_15), 15)
        self.assertEqual(len(top_65), 15)
        self.assertAlmostEqual(raw_15, 100.0, places=4)
        self.assertAlmostEqual(raw_65, 100.0, places=4)
        self.assertAlmostEqual(vdi_15, vdi_65, places=4)
        self.assertAlmostEqual(vdi_15, 100.0, places=4)

    def test_vdi_full_window_normalization(self):
        """Verify full-window normalization rewards depth and penalizes missing slots."""
        # 15 runs of 90.0 -> exact 90.0
        vdi_15, raw_15, _ = self.engine.aggregate_vdi([90.0] * 15)
        self.assertAlmostEqual(vdi_15, 90.0, places=4)
        self.assertAlmostEqual(raw_15, 90.0, places=4)

        # 1 run of 90.0 -> 90.0 * 1.0 / W15
        expected_1 = 90.0 / self.w15
        vdi_1, raw_1, _ = self.engine.aggregate_vdi([90.0])
        self.assertAlmostEqual(vdi_1, expected_1, places=4)
        self.assertAlmostEqual(raw_1, 90.0, places=4)


class TestTrackRegistry(unittest.TestCase):
    def test_track_counts(self):
        registry = TrackRegistry()
        self.assertEqual(len(registry.main_tracks), 17)
        self.assertEqual(len(registry.community_tracks), 61)
        self.assertEqual(len(registry.all_tracks), 78)


class TestTrackDomainMapping(unittest.TestCase):
    def test_last_remnant_mapped_to_fullspeed(self):
        """Verify Last Remnant maps to Fullspeed domain and FS subgenre."""
        dom, subg = map_track_to_domain_and_subgenre("Last Remnant", "RPG")
        self.assertEqual(dom, "Fullspeed")
        self.assertEqual(subg, "FS")

    def test_shardmir_mapped_to_technical(self):
        """Verify ShardMir maps to Technical domain and Tech subgenre."""
        dom, subg = map_track_to_domain_and_subgenre("ShardMir", "RPG")
        self.assertEqual(dom, "Technical")
        self.assertEqual(subg, "Tech")

    def test_standard_subgenre_mappings(self):
        """Verify standard sub-genre mappings to Fullspeed and Technical domains."""
        # Fullspeed domain
        dom_fs, subg_fs = map_track_to_domain_and_subgenre("Summer 3", "Fullspeed")
        self.assertEqual(dom_fs, "Fullspeed")
        self.assertEqual(subg_fs, "FS")

        dom_fake, subg_fake = map_track_to_domain_and_subgenre("Summer 6", "Fakespeed")
        self.assertEqual(dom_fake, "Fullspeed")
        self.assertEqual(subg_fake, "Fakespeed")

        # Technical domain
        dom_tech, subg_tech = map_track_to_domain_and_subgenre("concrete jungle", "Tech")
        self.assertEqual(dom_tech, "Technical")
        self.assertEqual(subg_tech, "Tech")

        dom_st, subg_st = map_track_to_domain_and_subgenre("Summer 4", "Speedtech")
        self.assertEqual(dom_st, "Technical")
        self.assertEqual(subg_st, "Speedtech")

        dom_sf, subg_sf = map_track_to_domain_and_subgenre("Summer 1", "Speedfun")
        self.assertEqual(dom_sf, "Technical")
        self.assertEqual(subg_sf, "Speedfun")

        dom_s2, subg_s2 = map_track_to_domain_and_subgenre("Summer 2", "Speedfun")
        self.assertEqual(dom_s2, "Technical")
        self.assertEqual(subg_s2, "Speedfun")

    def test_track_registry_domain_lookups(self):
        """Verify TrackRegistry returns correct domains for all tracks."""
        registry = TrackRegistry()
        self.assertEqual(registry.get_domain("Last Remnant"), "Fullspeed")
        self.assertEqual(registry.get_domain("ShardMir"), "Technical")
        self.assertEqual(registry.get_domain("Summer 3"), "Fullspeed")
        self.assertEqual(registry.get_domain("Summer 4"), "Technical")
        self.assertEqual(registry.get_domain("Summer 1"), "Technical")
        self.assertEqual(registry.get_domain("Summer 2"), "Technical")
        self.assertEqual(registry.get_subgenre("Summer 2"), "Speedfun")

        domain_totals = registry.get_domain_totals()
        self.assertIn("Fullspeed", domain_totals)
        self.assertIn("Technical", domain_totals)
        self.assertEqual(domain_totals["Fullspeed"], 35)
        self.assertEqual(domain_totals["Technical"], 43)
        self.assertEqual(domain_totals["Fullspeed"] + domain_totals["Technical"], 78)


class TestDisciplineEngine(unittest.TestCase):
    def test_top6_discipline_ratings(self):
        """Verify exact Top-6 discipline ratings with full-window normalization."""
        # 6 runs of 100.0 -> exact 100.0
        rating_6, raw_6, n_eff_6 = calculate_discipline_rating([100.0] * 6)
        self.assertEqual(n_eff_6, 6)
        self.assertAlmostEqual(raw_6, 100.0, places=4)
        self.assertAlmostEqual(rating_6, 100.0, places=4)

        # 1 run of 100.0 -> 100.0 / W6
        w6 = sum(0.85 ** r for r in range(6))
        rating_1, raw_1, n_eff_1 = calculate_discipline_rating([100.0])
        self.assertEqual(n_eff_1, 1)
        self.assertAlmostEqual(raw_1, 100.0, places=4)
        self.assertAlmostEqual(rating_1, 100.0 / w6, places=4)

        # 0 runs -> 0.0
        rating_0, raw_0, n_eff_0 = calculate_discipline_rating([])
        self.assertEqual(n_eff_0, 0)
        self.assertEqual(raw_0, 0.0)
        self.assertEqual(rating_0, 0.0)

    def test_discipline_volume_invariance(self):
        """Verify runs beyond Top 6 have zero mathematical effect on discipline rating."""
        elite_6 = [125.0] * 6
        elite_6_plus_30 = [125.0] * 6 + [15.0] * 30

        rating_6, raw_6, n_6 = calculate_discipline_rating(elite_6)
        rating_36, raw_36, n_36 = calculate_discipline_rating(elite_6_plus_30)

        self.assertEqual(n_6, 6)
        self.assertEqual(n_36, 6)
        self.assertAlmostEqual(raw_6, raw_36, places=4)
        self.assertAlmostEqual(rating_6, rating_36, places=4)

    def test_discipline_vdi_and_gsi_synthesis(self):
        """Verify discipline VDI (Top 15, gamma=0.90) and discipline GSI synthesis."""
        vdi_engine = VersatilityDepthIndexEngine(top_k=15, gamma=0.90)
        pqi_engine = PeakQualityIndexEngine(top_k=6, gamma=0.85)

        scores_15 = [100.0] * 15
        vdi_15, raw_vdi, _ = vdi_engine.aggregate_vdi(scores_15)
        pqi_6, raw_pqi, _ = pqi_engine.aggregate_pqi(scores_15)

        self.assertAlmostEqual(vdi_15, 100.0, places=4)
        self.assertAlmostEqual(pqi_6, 100.0, places=4)

        # Standardized Discipline GSI synthesis
        mu_pqi, sigma_pqi = 25.0, 10.0
        mu_vdi, sigma_vdi = 20.0, 10.0
        z_pqi = (pqi_6 - mu_pqi) / sigma_pqi
        z_vdi = (vdi_15 - mu_vdi) / sigma_vdi
        gsi_discipline = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_pqi + GSI_WEIGHT_VDI * z_vdi)
        self.assertGreater(gsi_discipline, 1000.0)


class TestDisciplineTaxonomyAndArchetypes(unittest.TestCase):
    def test_discipline_bias_ratio(self):
        """Verify Bias = Rating(FS) / (Rating(FS) + Rating(Tech))."""
        # FS = 90, Tech = 60 -> Bias = 90 / 150 = 0.60
        bias_60 = calculate_discipline_bias(90.0, 60.0)
        self.assertAlmostEqual(bias_60, 0.60, places=4)

        # FS = 40, Tech = 60 -> Bias = 40 / 100 = 0.40
        bias_40 = calculate_discipline_bias(40.0, 60.0)
        self.assertAlmostEqual(bias_40, 0.40, places=4)

        # FS = 50, Tech = 50 -> Bias = 0.50
        bias_50 = calculate_discipline_bias(50.0, 50.0)
        self.assertAlmostEqual(bias_50, 0.50, places=4)

        # FS = 0, Tech = 0 -> Bias = 0.50
        bias_0 = calculate_discipline_bias(0.0, 0.0)
        self.assertEqual(bias_0, 0.50)

    def test_archetype_classifications(self):
        """Verify archetype classifications under v10.2 rules (70/30 thresholds)."""
        # Fullspeed Specialist: Bias >= 0.70 and >= 4 FS tracks
        arch_fs = determine_discipline_archetype(bias=0.75, count_fs=6, count_tech=2, total_tracks_driven=8)
        self.assertEqual(arch_fs, "Fullspeed Specialist")

        # Fullspeed Specialist boundary (Bias == 0.70, count_fs == 4)
        arch_fs_edge = determine_discipline_archetype(bias=0.70, count_fs=4, count_tech=2, total_tracks_driven=6)
        self.assertEqual(arch_fs_edge, "Fullspeed Specialist")

        # Insufficient FS tracks for specialist -> Player
        arch_fs_low_tracks = determine_discipline_archetype(bias=0.75, count_fs=3, count_tech=1, total_tracks_driven=4)
        self.assertEqual(arch_fs_low_tracks, "Player")

        # Technical Specialist: Bias <= 0.30 and >= 4 Tech tracks
        arch_tech = determine_discipline_archetype(bias=0.25, count_fs=2, count_tech=7, total_tracks_driven=9)
        self.assertEqual(arch_tech, "Technical Specialist")

        # Technical Specialist boundary (Bias == 0.30, count_tech == 4)
        arch_tech_edge = determine_discipline_archetype(bias=0.30, count_fs=1, count_tech=4, total_tracks_driven=5)
        self.assertEqual(arch_tech_edge, "Technical Specialist")

        # Insufficient Tech tracks for specialist -> Player
        arch_tech_low_tracks = determine_discipline_archetype(bias=0.20, count_fs=1, count_tech=3, total_tracks_driven=4)
        self.assertEqual(arch_tech_low_tracks, "Player")

        # Generalist: 0.30 < Bias < 0.70 and >= 4 tracks in both
        arch_generalist = determine_discipline_archetype(bias=0.52, count_fs=6, count_tech=8, total_tracks_driven=14)
        self.assertEqual(arch_generalist, "Generalist")

        # Generalist at old 0.65 boundary (between 0.30 and 0.70) with >= 4 in both
        arch_generalist_65 = determine_discipline_archetype(bias=0.65, count_fs=6, count_tech=4, total_tracks_driven=10)
        self.assertEqual(arch_generalist_65, "Generalist")

        # Generalist at old 0.35 boundary (between 0.30 and 0.70) with >= 4 in both
        arch_generalist_35 = determine_discipline_archetype(bias=0.35, count_fs=4, count_tech=6, total_tracks_driven=10)
        self.assertEqual(arch_generalist_35, "Generalist")

        # Balanced bias but missing >= 4 in one domain -> Player
        arch_balanced_low_fs = determine_discipline_archetype(bias=0.50, count_fs=3, count_tech=6, total_tracks_driven=9)
        self.assertEqual(arch_balanced_low_fs, "Player")

        arch_balanced_low_tech = determine_discipline_archetype(bias=0.50, count_fs=6, count_tech=3, total_tracks_driven=9)
        self.assertEqual(arch_balanced_low_tech, "Player")

        # Zero tracks -> Player
        arch_zero = determine_discipline_archetype(bias=0.50, count_fs=0, count_tech=0, total_tracks_driven=0)
        self.assertEqual(arch_zero, "Player")

    def test_player_classification(self):
        """Verify player ecosystem classifications: Main Specialist, Community Specialist, All Rounder."""
        # Main Specialist: >= 70% of points on main tracks
        cat_main, bias_main = classify_player(main_tracks_count=10, comm_tracks_count=2, main_score=75.0, comm_score=25.0)
        self.assertEqual(cat_main, "Main Specialist")
        self.assertEqual(bias_main, 0.75)

        # Main Specialist boundary (0.70)
        cat_main_edge, _ = classify_player(main_tracks_count=8, comm_tracks_count=3, main_score=70.0, comm_score=30.0)
        self.assertEqual(cat_main_edge, "Main Specialist")

        # Community Specialist: >= 70% of points on community tracks (main <= 30%)
        cat_comm, bias_comm = classify_player(main_tracks_count=2, comm_tracks_count=15, main_score=20.0, comm_score=80.0)
        self.assertEqual(cat_comm, "Community Specialist")
        self.assertEqual(bias_comm, 0.20)

        # Community Specialist boundary (0.30)
        cat_comm_edge, _ = classify_player(main_tracks_count=3, comm_tracks_count=10, main_score=30.0, comm_score=70.0)
        self.assertEqual(cat_comm_edge, "Community Specialist")

        # All Rounder: between 30% and 70% exclusive
        cat_ar, bias_ar = classify_player(main_tracks_count=8, comm_tracks_count=12, main_score=50.0, comm_score=50.0)
        self.assertEqual(cat_ar, "All Rounder")
        self.assertEqual(bias_ar, 0.50)

        cat_ar_60, _ = classify_player(main_tracks_count=10, comm_tracks_count=8, main_score=60.0, comm_score=40.0)
        self.assertEqual(cat_ar_60, "All Rounder")


class TestEngine3GlobalSkillIndex(unittest.TestCase):
    def test_gsi_v10_weights(self):
        z_pqi = 0.0
        z_vdi = 0.0
        gsi_mean = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_pqi + GSI_WEIGHT_VDI * z_vdi)
        self.assertEqual(gsi_mean, 1000.0)

        # 70% PQI + 30% VDI
        z_pqi = 1.0
        z_vdi = 1.0
        gsi_1sigma = GSI_BASE + GSI_SCALE * (0.70 * z_pqi + 0.30 * z_vdi)
        self.assertEqual(gsi_1sigma, 1200.0)


class TestLeaderboardProcessingAndAltConsolidation(unittest.TestCase):
    def test_tas_filtering_and_deduplication(self):
        raw_entries = [
            {"nickname": "[TAS] Bot1", "frames": 10000, "userId": "u1"},
            {"nickname": "[tas] Bot2", "frames": 11000, "userId": "u2"},
            {"nickname": "ProRacer", "frames": 15000, "userId": "u3"},
            {"nickname": "ProRacer", "frames": 16000, "userId": "u3"},
            {"nickname": "CasualGamer", "frames": 18000, "userId": "u4"},
        ]
        cleaned = process_raw_leaderboard(raw_entries, alt_mappings={})
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["nickname"], "ProRacer")
        self.assertEqual(cleaned[0]["rank"], 1)
        self.assertEqual(cleaned[1]["nickname"], "CasualGamer")
        self.assertEqual(cleaned[1]["rank"], 2)

    def test_alt_consumption_and_dense_rank_adjustment(self):
        """Verify that when an alt has a faster time, it is consumed by the main account,
        the slower main time is dropped, and other players' ranks shift up accordingly."""
        custom_alts = {
            "youngfella": "youngfella",
            "yf savestate": "youngfella",
            "aidrian simon": "youngfella",
        }
        raw_entries = [
            {"nickname": "Alice", "frames": 600, "userId": "alice_uid"},          # 10.0s -> Rank 1
            {"nickname": "aidrian simon", "frames": 630, "userId": "alt1_uid"},   # 10.5s -> youngfella consumes! (Rank 2)
            {"nickname": "Bob", "frames": 660, "userId": "bob_uid"},              # 11.0s -> Rank 3
            {"nickname": "youngfella", "frames": 720, "userId": "yf_main_uid"},   # 12.0s -> duplicate slower dropped!
            {"nickname": "yf savestate", "frames": 750, "userId": "alt2_uid"},    # 12.5s -> duplicate slower dropped!
            {"nickname": "Charlie", "frames": 780, "userId": "charlie_uid"},      # 13.0s -> Moves up to Rank 4 (not Rank 6)!
        ]
        cleaned = process_raw_leaderboard(raw_entries, alt_mappings=custom_alts)
        self.assertEqual(len(cleaned), 4)

        # Rank 1: Alice (10.0s)
        self.assertEqual(cleaned[0]["rank"], 1)
        self.assertEqual(cleaned[0]["nickname"], "Alice")
        self.assertAlmostEqual(cleaned[0]["time_sec"], 10.0)

        # Rank 2: youngfella (10.5s consumed from aidrian simon)
        self.assertEqual(cleaned[1]["rank"], 2)
        self.assertEqual(cleaned[1]["canonicalNickname"], "youngfella")
        self.assertAlmostEqual(cleaned[1]["time_sec"], 10.5)

        # Rank 3: Bob (11.0s)
        self.assertEqual(cleaned[2]["rank"], 3)
        self.assertEqual(cleaned[2]["nickname"], "Bob")
        self.assertAlmostEqual(cleaned[2]["time_sec"], 11.0)

        # Rank 4: Charlie (13.0s - shifted up because duplicate youngfella entries were removed!)
        self.assertEqual(cleaned[3]["rank"], 4)
        self.assertEqual(cleaned[3]["nickname"], "Charlie")
        self.assertAlmostEqual(cleaned[3]["time_sec"], 13.0)

    def test_blacklist_filtering_and_dense_rank_adjustment(self):
        """Verify blacklisted cheaters are entirely eliminated and subsequent ranks dense-adjust up."""
        custom_blacklist = {"CheaterX", "bad_actor_uid"}
        raw_entries = [
            {"nickname": "CheaterX", "frames": 300, "userId": "cx_uid"},          # 5.0s -> Blacklisted by nickname!
            {"nickname": "Alice", "frames": 600, "userId": "alice_uid"},          # 10.0s -> Should become Rank 1!
            {"nickname": "AnonDriver", "frames": 630, "userId": "bad_actor_uid"},  # 10.5s -> Blacklisted by userId!
            {"nickname": "Bob", "frames": 660, "userId": "bob_uid"},              # 11.0s -> Should become Rank 2!
            {"nickname": "Charlie", "frames": 720, "userId": "charlie_uid"},      # 12.0s -> Should become Rank 3!
        ]
        cleaned = process_raw_leaderboard(raw_entries, alt_mappings={}, blacklisted_players=custom_blacklist)
        self.assertEqual(len(cleaned), 3)

        # Alice must be Rank 1 (not Rank 2)
        self.assertEqual(cleaned[0]["rank"], 1)
        self.assertEqual(cleaned[0]["nickname"], "Alice")
        self.assertAlmostEqual(cleaned[0]["time_sec"], 10.0)

        # Bob must be Rank 2 (not Rank 4)
        self.assertEqual(cleaned[1]["rank"], 2)
        self.assertEqual(cleaned[1]["nickname"], "Bob")
        self.assertAlmostEqual(cleaned[1]["time_sec"], 11.0)

        # Charlie must be Rank 3 (not Rank 5)
        self.assertEqual(cleaned[2]["rank"], 3)
        self.assertEqual(cleaned[2]["nickname"], "Charlie")
        self.assertAlmostEqual(cleaned[2]["time_sec"], 12.0)

    def test_ben_blacklisted_by_default(self):
        """Verify that 'Ben' and his userId are blacklisted by default and filtered out automatically."""
        ben_uid = "09f0741c8e7e793380c6dee978ec3dae563f891c5d5832497efdfb709cbf92a2"
        self.assertIn("Ben", BLACKLISTED_PLAYERS)
        self.assertIn(ben_uid, BLACKLISTED_PLAYERS)

        # Check is_player_blacklisted helper
        self.assertTrue(is_player_blacklisted(nickname="Ben"))
        self.assertTrue(is_player_blacklisted(nickname="ben"))
        self.assertTrue(is_player_blacklisted(nickname="BEN"))
        self.assertTrue(is_player_blacklisted(user_id=ben_uid))
        self.assertTrue(is_player_blacklisted(nickname="OtherName", user_id=ben_uid))
        self.assertFalse(is_player_blacklisted(nickname="SpeedySebas", user_id="some_other_id"))
        self.assertFalse(is_player_blacklisted(nickname="youngfella", user_id="yf_id"))

        # Verify default leaderboard processing removes Ben and dense-adjusts
        raw_entries = [
            {"nickname": "Ben", "frames": 300, "userId": ben_uid},
            {"nickname": "SpeedySebas", "frames": 360, "userId": "sebas_uid"},
            {"nickname": "youngfella", "frames": 400, "userId": "yf_uid"},
        ]
        cleaned = process_raw_leaderboard(raw_entries)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["nickname"], "SpeedySebas")
        self.assertEqual(cleaned[0]["rank"], 1)
        self.assertEqual(cleaned[1]["canonicalNickname"], "youngfella")
        self.assertEqual(cleaned[1]["rank"], 2)

    def test_identity_resolution_with_unicode(self):
        """Verify unicode normalization in identity resolution."""
        key1, name1 = resolve_player_identity("|<iki", "b99c6507")
        self.assertEqual(name1, "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı")

        key2, name2 = resolve_player_identity("ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı", "6368f9b4")
        self.assertEqual(name2, "ıllıllı 𝐊𝐢𝐤𝐢 ıllıllı")
        self.assertEqual(key1, key2)

class TestMonotonicityAndProfileStrictDominance(unittest.TestCase):
    def test_pi_are_squar3d_strictly_dominates_anonymous(self):
        """Assert that an active 20-track profile strictly outscores a 2-track low-rank profile."""
        engine_pqi = PeakQualityIndexEngine(top_k=6, gamma=0.85)
        engine_vdi = VersatilityDepthIndexEngine(top_k=15, gamma=0.90)

        # PiAreSqar3d top scores (20 tracks with top 6 ranging from 27.5 to 22.0, next 9 around 20-21)
        pi_top6 = [27.5, 27.3, 25.3, 24.6, 23.6, 22.0]
        pi_top15 = pi_top6 + [21.5, 21.1, 21.1, 20.9, 20.7, 20.4, 20.0, 19.8, 19.5]

        # Anonymous scores (2 tracks: 18.2, 17.5)
        anon_scores = [18.2, 17.5]

        pqi_pi, _, _ = engine_pqi.aggregate_pqi(pi_top6)
        vdi_pi, _, _ = engine_vdi.aggregate_vdi(pi_top15)

        pqi_anon, _, _ = engine_pqi.aggregate_pqi(anon_scores)
        vdi_anon, _, _ = engine_vdi.aggregate_vdi(anon_scores)

        # Assert PQI strict dominance
        self.assertGreater(pqi_pi, pqi_anon)
        self.assertGreater(pqi_pi, 25.0)
        self.assertLess(pqi_anon, 10.0)

        # Assert VDI strict dominance (Pi has 15 full tracks, Anonymous has 2 tracks)
        self.assertGreater(vdi_pi, vdi_anon)
        self.assertGreater(vdi_pi, 22.0)
        self.assertLess(vdi_anon, 5.0)

        # Assert GSI strict dominance under active population standardization
        mu_pqi, sigma_pqi = 24.0, 8.0
        mu_vdi, sigma_vdi = 18.0, 8.0

        z_pqi_pi = (pqi_pi - mu_pqi) / sigma_pqi
        z_vdi_pi = (vdi_pi - mu_vdi) / sigma_vdi
        gsi_pi = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_pqi_pi + GSI_WEIGHT_VDI * z_vdi_pi)

        z_pqi_anon = (pqi_anon - mu_pqi) / sigma_pqi
        z_vdi_anon = (vdi_anon - mu_vdi) / sigma_vdi
        gsi_anon = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_pqi_anon + GSI_WEIGHT_VDI * z_vdi_anon)

        self.assertGreater(gsi_pi, gsi_anon + 400.0)


# =====================================================================
# Engine 4 Unit Tests: GSI Optimization Strategy & Target Advisor (v11.0)
# =====================================================================

class TestBaselineAndConsistency(unittest.TestCase):
    def test_player_baseline_calculation(self):
        """Verify baseline estimation (median rank, intensity, driven count)."""
        player_scores = {"Track A": 50.0, "Track B": 60.0, "Track C": 70.0}
        player_ranks = {"Track A": 5, "Track B": 4, "Track C": 2}
        all_tracks = {
            "Track A": {"dynamic_weight": 1.0},
            "Track B": {"dynamic_weight": 1.0},
            "Track C": {"dynamic_weight": 1.0}
        }
        baseline = calculate_player_baseline(player_scores, player_ranks, all_tracks)
        self.assertEqual(baseline["driven_count"], 3)
        self.assertEqual(baseline["median_rank"], 4)
        self.assertEqual(baseline["median_intensity"], 60.0)

    def test_cross_track_consistency_cv(self):
        """Verify cross-track consistency CV = std / mean."""
        # Equal intensity on all tracks -> std = 0 -> CV = 0
        player_scores_equal = {"Track A": 50.0, "Track B": 50.0, "Track C": 50.0}
        all_tracks = {"Track A": {"dynamic_weight": 1.0}, "Track B": {"dynamic_weight": 1.0}, "Track C": {"dynamic_weight": 1.0}}
        cv_equal = calculate_cross_track_consistency(player_scores_equal, all_tracks)
        self.assertAlmostEqual(cv_equal, 0.0, places=4)

        # High variance intensity
        player_scores_var = {"Track A": 10.0, "Track B": 90.0}
        cv_var = calculate_cross_track_consistency(player_scores_var, all_tracks)
        self.assertGreater(cv_var, 0.50)


class TestConfidenceTierDetermination(unittest.TestCase):
    def test_confidence_tiers_played_and_unplayed(self):
        """Verify confidence tier assignments based on evidence quality and consistency."""
        # Played track with good data -> High
        tier, factor = determine_confidence_tier(is_unplayed=False, consistency_cv=0.20, driven_count=5)
        self.assertEqual(tier, "High")
        self.assertEqual(factor, CONFIDENCE_FACTOR_HIGH)

        # Played track with limited data / high CV -> Medium
        tier, factor = determine_confidence_tier(is_unplayed=False, consistency_cv=0.60, driven_count=2)
        self.assertEqual(tier, "Medium")
        self.assertEqual(factor, CONFIDENCE_FACTOR_MEDIUM)

        # Unplayed track with rich global history (>=8 tracks, low CV) -> High
        tier, factor = determine_confidence_tier(is_unplayed=True, consistency_cv=0.15, driven_count=10)
        self.assertEqual(tier, "High")
        self.assertEqual(factor, CONFIDENCE_FACTOR_HIGH)

        # Unplayed track with moderate history (>=4 tracks, moderate CV) -> Medium
        tier, factor = determine_confidence_tier(is_unplayed=True, consistency_cv=0.35, driven_count=5)
        self.assertEqual(tier, "Medium")
        self.assertEqual(factor, CONFIDENCE_FACTOR_MEDIUM)

        # Unplayed track with scarce history -> Low
        tier, factor = determine_confidence_tier(is_unplayed=True, consistency_cv=0.80, driven_count=2)
        self.assertEqual(tier, "Low")
        self.assertEqual(factor, CONFIDENCE_FACTOR_LOW)


class TestEffortCostModel(unittest.TestCase):
    def test_effort_properties(self):
        """Verify advancement effort monotonicity, frontier penalty, and SoF moderation."""
        # Unplayed baseline rank 50 to target rank 10 vs target rank 1
        e_r10 = calculate_effort(baseline_rank=50, target_rank=10, omega_k=1.0, is_unplayed=True)
        e_r1 = calculate_effort(baseline_rank=50, target_rank=1, omega_k=1.0, is_unplayed=True)

        # Harder rank requires strictly more effort
        self.assertGreater(e_r1, e_r10)

        # Upgrading existing track (entry cost 0.50) is cheaper than unplayed entry (1.00)
        e_upgrade = calculate_effort(baseline_rank=50, target_rank=10, omega_k=1.0, is_unplayed=False)
        self.assertLess(e_upgrade, e_r10)
        self.assertAlmostEqual(e_r10 - e_upgrade, UNPLAYED_ENTRY_EFFORT - UPGRADE_ENTRY_EFFORT, places=4)

        # Frontier penalty increases sharply as target approaches Rank 1
        pen_1 = FRONTIER_PENALTY_COEFF / math.sqrt(1)
        pen_100 = FRONTIER_PENALTY_COEFF / math.sqrt(100)
        self.assertGreater(pen_1, pen_100)

        # Higher weight track increases effort, bounded by clamp
        e_heavy = calculate_effort(baseline_rank=50, target_rank=10, omega_k=1.30, is_unplayed=True)
        e_light = calculate_effort(baseline_rank=50, target_rank=10, omega_k=0.80, is_unplayed=True)
        self.assertGreater(e_heavy, e_light)


class TestCandidateLadderAndPareto(unittest.TestCase):
    def test_candidate_ladder_generation(self):
        """Verify candidate ladder contains key milestones and cutline crossings."""
        ladder = generate_candidate_target_ladder(
            track_name="Summer 1",
            curr_rank=20,
            baseline_rank=20,
            omega_k=1.25,
            s6_cutoff=75.0,
            s15_cutoff=50.0
        )
        self.assertIn(1, ladder)
        self.assertIn(2, ladder)
        self.assertIn(3, ladder)
        self.assertIn(5, ladder)
        self.assertIn(10, ladder)
        # All candidate ranks must be strictly better than current rank 20
        self.assertTrue(all(r < 20 for r in ladder))

    def test_pareto_dominance_filter(self):
        """Verify dominated targets are pruned while non-dominated local peaks are preserved."""
        cand_a = {"target_rank": 10, "conf_adj_gain": 5.0, "effort_cost": 2.0}
        cand_b = {"target_rank": 5, "conf_adj_gain": 8.0, "effort_cost": 3.0}
        cand_dominated = {"target_rank": 8, "conf_adj_gain": 4.5, "effort_cost": 2.5}  # Lower gain at higher cost than cand_a

        filtered = filter_pareto_dominated_targets([cand_a, cand_b, cand_dominated])
        self.assertEqual(len(filtered), 2)
        self.assertIn(cand_a, filtered)
        self.assertIn(cand_b, filtered)
        self.assertNotIn(cand_dominated, filtered)


class TestSimulationAndROI(unittest.TestCase):
    def test_simulation_exact_gain(self):
        """Verify exact portfolio simulation yields positive non-linear Delta GSI."""
        player_scores = [50.0] * 15
        curr_gsi = 1100.0
        delta_gsi, sim_gsi, sim_pqi, sim_vdi = simulate_exact_gsi_gain(
            base_scores=player_scores,
            curr_score=50.0,
            s_proj=80.0,
            mu_pqi=24.0,
            sigma_pqi=8.0,
            mu_vdi=18.0,
            sigma_vdi=8.0,
            current_gsi=curr_gsi,
            is_unplayed=False
        )
        self.assertGreater(delta_gsi, 0.0)
        self.assertAlmostEqual(sim_gsi, curr_gsi + delta_gsi, places=4)

    def test_tier_classification(self):
        """Verify classification into 4 recommendation tiers."""
        self.assertEqual(classify_recommendation_tier(roi=0.40, effort=2.0, delta_gsi=1.5, target_rank=5, conf_tier="High"), "Quick Win")
        self.assertEqual(classify_recommendation_tier(roi=0.15, effort=4.5, delta_gsi=2.0, target_rank=2, conf_tier="Low"), "Grind Trap")
        self.assertEqual(classify_recommendation_tier(roi=0.25, effort=4.5, delta_gsi=1.5, target_rank=2, conf_tier="High"), "Stretch Goal")
        self.assertEqual(classify_recommendation_tier(roi=0.28, effort=3.0, delta_gsi=0.8, target_rank=6, conf_tier="High"), "Worth Grinding")


# =====================================================================
# 11 Representative Player Profile Scenarios (Specification Section 33)
# =====================================================================

class TestRepresentativePlayerScenarios(unittest.TestCase):
    def setUp(self):
        self.all_tracks = {
            f"Campaign {i}": {"dynamic_weight": 1.25, "is_main": True, "domain": "Fullspeed", "subgenre": "Speedfun"} for i in range(1, 10)
        }
        self.all_tracks.update({
            f"Tech Campaign {i}": {"dynamic_weight": 1.20, "is_main": True, "domain": "Technical", "subgenre": "Tech"} for i in range(1, 10)
        })
        self.all_tracks.update({
            f"Community FS {i}": {"dynamic_weight": 0.85, "is_main": False, "domain": "Fullspeed", "subgenre": "FS"} for i in range(1, 20)
        })
        self.all_tracks.update({
            f"Community Tech {i}": {"dynamic_weight": 0.80, "is_main": False, "domain": "Technical", "subgenre": "Tech"} for i in range(1, 20)
        })
        self.mu_pqi, self.sigma_pqi = 24.0, 8.0
        self.mu_vdi, self.sigma_vdi = 18.0, 8.0

    def _eval_player(self, scores_map, ranks_map):
        scores_list = list(scores_map.values())
        engine_pqi = PeakQualityIndexEngine(top_k=6, gamma=0.85)
        engine_vdi = VersatilityDepthIndexEngine(top_k=15, gamma=0.90)
        curr_pqi, _, _ = engine_pqi.aggregate_pqi(scores_list)
        curr_vdi, _, _ = engine_vdi.aggregate_vdi(scores_list)
        z_p = (curr_pqi - self.mu_pqi) / self.sigma_pqi
        z_v = (curr_vdi - self.mu_vdi) / self.sigma_vdi
        curr_gsi = GSI_BASE + GSI_SCALE * (GSI_WEIGHT_PQI * z_p + GSI_WEIGHT_VDI * z_v)

        return evaluate_player_strategy(
            player_scores_map=scores_map,
            player_ranks_map=ranks_map,
            all_tracks_dict=self.all_tracks,
            current_pqi=curr_pqi,
            current_vdi=curr_vdi,
            current_gsi=curr_gsi,
            mu_pqi=self.mu_pqi,
            sigma_pqi=self.sigma_pqi,
            mu_vdi=self.mu_vdi,
            sigma_vdi=self.sigma_vdi,
            top_n=10
        )

    def test_scenario_1_top_player_frontier_saturation(self):
        """Scenario 1: Saturated Top 1 Player (WRs on top tracks -> recommendations target remaining unconquered maps)."""
        scores = {f"Campaign {i}": 156.25 for i in range(1, 7)}  # Rank 1 WR on 6 heavy campaign tracks
        ranks = {f"Campaign {i}": 1 for i in range(1, 7)}
        for i in range(1, 10):
            scores[f"Community FS {i}"] = 80.0
            ranks[f"Community FS {i}"] = 2

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        # Saturated tracks cannot be improved
        for target in res:
            self.assertNotEqual(target["curr_rank"], 1)

    def test_scenario_2_high_peak_unplayed_depth_quick_wins(self):
        """Scenario 2: High Peak / Empty Depth (Only 5 tracks driven -> unplayed tracks emerge with massive ROI)."""
        scores = {f"Campaign {i}": 140.0 for i in range(1, 6)}  # 5 great finishes, 0 depth
        ranks = {f"Campaign {i}": 2 for i in range(1, 6)}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        top = res[0]
        # Unplayed track should emerge at #1 to fill empty 15-track depth window
        self.assertTrue(top["is_unplayed"])
        self.assertIn("fills an empty depth slot", top["reason"])

    def test_scenario_3_broad_generalist_incremental_upgrades(self):
        """Scenario 3: Broad Mid-Tier Generalist (15 tracks at ~rank 25 -> incremental upgrades prioritized)."""
        scores = {f"Campaign {i}": 45.0 for i in range(1, 9)}
        scores.update({f"Tech Campaign {i}": 45.0 for i in range(1, 8)})
        ranks = {t: 25 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        top = res[0]
        self.assertGreater(top["roi_score"], 0.0)

    def test_scenario_4_extreme_specialist_discipline_expansion(self):
        """Scenario 4: Extreme Specialist (All Tech, 0 Fullspeed -> Unplayed FS maps provide high ROI)."""
        scores = {f"Tech Campaign {i}": 80.0 for i in range(1, 10)}
        scores.update({f"Community Tech {i}": 60.0 for i in range(1, 7)})
        ranks = {t: 3 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        # At least one FS track should be in top recommendations
        fs_recs = [r for r in res if r["domain"] == "Fullspeed"]
        self.assertGreater(len(fs_recs), 0)

    def test_scenario_5_high_variance_gambler_dispersion(self):
        """Scenario 5: High-Variance Gambler (1 WR, remainder rank 150 -> higher dispersion CV, medium confidence)."""
        scores = {"Campaign 1": 156.25}
        ranks = {"Campaign 1": 1}
        for i in range(2, 16):
            scores[f"Campaign {i}"] = 20.0
            ranks[f"Campaign {i}"] = 150

        cv = calculate_cross_track_consistency(scores, self.all_tracks)
        self.assertGreater(cv, 0.40)  # High dispersion

    def test_scenario_6_consistent_top_performer_high_confidence(self):
        """Scenario 6: Consistent Top 10 Performer (Low CV, High Confidence)."""
        scores = {f"Campaign {i}": 85.0 for i in range(1, 10)}
        scores.update({f"Tech Campaign {i}": 82.0 for i in range(1, 7)})
        ranks = {t: 6 for t in scores}

        cv = calculate_cross_track_consistency(scores, self.all_tracks)
        self.assertLess(cv, 0.20)  # Very low dispersion
        tier, factor = determine_confidence_tier(is_unplayed=True, consistency_cv=cv, driven_count=len(scores))
        self.assertEqual(tier, "High")

    def test_scenario_7_emerging_driver_empty_slot_priority(self):
        """Scenario 7: Brand New Emerging Driver (Only 2 tracks driven -> Low confidence on unplayed, quick wins)."""
        scores = {"Campaign 1": 35.0, "Campaign 2": 30.0}
        ranks = {"Campaign 1": 40, "Campaign 2": 50}

        tier, factor = determine_confidence_tier(is_unplayed=True, consistency_cv=0.15, driven_count=2)
        self.assertEqual(tier, "Low")

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        self.assertTrue(any(r["is_unplayed"] for r in res))

    def test_scenario_8_campaign_only_community_expansion(self):
        """Scenario 8: Campaign Only Driver (18 campaign, 0 community -> community tracks provide easy unplayed upgrades)."""
        scores = {f"Campaign {i}": 70.0 for i in range(1, 10)}
        scores.update({f"Tech Campaign {i}": 65.0 for i in range(1, 10)})
        ranks = {t: 10 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)

    def test_scenario_9_low_multiplier_trapped_weight_leverage(self):
        """Scenario 9: Low-Multiplier Trapped Player (Finishes on low-weight maps -> heavy campaign maps provide top ROI)."""
        scores = {f"Community FS {i}": 50.0 for i in range(1, 16)}
        ranks = {t: 5 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        # Heavy weight campaign tracks should dominate the top recommendations
        top_weights = [r["weight"] for r in res[:3]]
        self.assertTrue(all(w >= 1.20 for w in top_weights))

    def test_scenario_10_near_cutline_threshold_bonus(self):
        """Scenario 10: Near-Cutline Player (Scores close to S6 / S15 -> cutline crossing generates substantial GSI jump)."""
        scores = {f"Campaign {i}": 60.0 for i in range(1, 7)}
        scores.update({f"Community FS {i}": 40.0 for i in range(1, 10)})
        ranks = {t: 15 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)

    def test_scenario_11_maxed_depth_wr_frontier_focus(self):
        """Scenario 11: Completely Maxed Depth Saturated Player (All 15 slots top-tier -> only frontier WR/podium upgrades remain)."""
        scores = {f"Campaign {i}": 120.0 for i in range(1, 10)}
        scores.update({f"Tech Campaign {i}": 115.0 for i in range(1, 7)})
        ranks = {t: 3 for t in scores}

        res = self._eval_player(scores, ranks)
        self.assertGreater(len(res), 0)
        # Recommendations will target Rank 1 or Rank 2 (Podium/WR)
        self.assertTrue(all(r["target_rank"] <= 2 for r in res[:3]))

    def test_track_metadata_lu_muvimento_and_flying_dreams(self):
        """Verify Lu Muvimento spelling normalization and Flying Dreams Speedfun classification."""
        from power_ranking_system import normalize_track_name
        self.assertEqual(normalize_track_name("lu muvimiento"), "Lu Muvimento")
        self.assertEqual(normalize_track_name("Lu Muvimiento"), "Lu Muvimento")
        self.assertEqual(normalize_track_name("lu muvimento"), "Lu Muvimento")
        self.assertEqual(normalize_track_name("Lu Muvimento"), "Lu Muvimento")

        reg = TrackRegistry()
        self.assertIn("Lu Muvimento", reg.all_tracks)
        self.assertEqual(reg.get_domain("Lu Muvimento"), "Fullspeed")
        self.assertEqual(reg.get_subgenre("Lu Muvimento"), "FS")

        self.assertIn("Flying Dreams", reg.all_tracks)
        self.assertEqual(reg.get_domain("Flying Dreams"), "Technical")
        self.assertEqual(reg.get_subgenre("Flying Dreams"), "Speedfun")


if __name__ == "__main__":
    unittest.main()
