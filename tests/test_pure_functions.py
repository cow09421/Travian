"""Unit tests for pure (side-effect-free) functions across the codebase."""
import pytest
from typing import Any
from raider.farm_list import FarmTarget, FarmListManager
from agent.state_summarizer import compress_state_for_llm


def make_mock_state(**overrides) -> dict:
    """Helper to build a minimal GameState-like dict for testing."""
    base = {
        "timestamp": "2026-01-01T00:00:00",
        "village_name": "Test",
        "resources": {"wood": 500, "clay": 500, "iron": 500, "crop": 500,
                      "wood_rate": 10, "clay_rate": 10, "iron_rate": 10, "crop_rate": 10,
                      "warehouse_cap": 800, "granary_cap": 800},
        "buildings": {"Main Building": 3, "Cranny": 1},
        "buildings_with_slots": {"Rally Point": {"gid": 39, "level": 1, "slot": 1},
                                 "Barracks": {"gid": 19, "level": 1, "slot": 2}},
        "buildings_by_gid": {39: "Rally Point", 19: "Barracks"},
        "resource_fields": {"wood_cutters": [{"slot": 1, "level": 2}],
                            "clay_pits": [{"slot": 2, "level": 1}],
                            "iron_mines": [{"slot": 3, "level": 1}],
                            "croplands": [{"slot": 4, "level": 3}]},
        "resource_fields_by_slot": {1: {"slot": 1, "level": 2, "field_type": "wood_cutters"},
                                    2: {"slot": 2, "level": 1, "field_type": "clay_pits"},
                                    3: {"slot": 3, "level": 1, "field_type": "iron_mines"},
                                    4: {"slot": 4, "level": 3, "field_type": "croplands"}},
        "empty_building_slots": [],
        "coord_x": 0, "coord_y": 0,
        "build_queue": [],
        "build_queue_full": False,
        "troop_queue": [],
        "troops": {"home": {}},
        "map": {},
        "next_free_slot": None,
        "has_plus": False,
        "hero": {"hero_health": 100, "hero_status": "home"},
        "quests": {"total_reward_ready": 0},
        "diplomatic_intel": {},
        "protection_hours_remaining": 0.0,
        "population": 50,
    }
    base.update(overrides)
    return base


class TestFindBuildingSlot:
    def test_finds_by_gid(self):
        from scheduler.loop import _find_building_slot
        state = make_mock_state()
        assert _find_building_slot(state, 19) == 2  # Barracks at slot 2

    def test_returns_none_for_unknown_gid(self):
        from scheduler.loop import _find_building_slot
        state = make_mock_state()
        assert _find_building_slot(state, 999) is None


class TestFarmTarget:
    def test_worth_raiding_low_population(self):
        t = FarmTarget(coord_x=1, coord_y=1, village_name="A", owner="", population=30)
        assert t.worth_raiding is True

    def test_not_worth_when_inactive(self):
        t = FarmTarget(coord_x=1, coord_y=1, village_name="A", owner="", population=30, is_active=False)
        assert t.worth_raiding is False

    def test_not_worth_heavy_defense(self):
        t = FarmTarget(coord_x=1, coord_y=1, village_name="A", owner="", population=100,
                       defense_level="heavy", avg_loot=500)
        assert t.worth_raiding is False

    def test_ready_to_raid_no_history(self):
        t = FarmTarget(coord_x=1, coord_y=1, village_name="A", owner="", population=100)
        assert t.ready_to_raid is True


class TestFilterValidActions:
    def test_skip_build_when_queue_full(self):
        from scheduler.action_dispatcher import filter_valid_actions
        state = make_mock_state(build_queue_full=True, build_queue=[{"name": "something", "seconds_left": 60}])
        actions = [{"name": "upgrade_building", "arguments": {"building_name": "Warehouse"}}]
        result = filter_valid_actions(actions, state)
        assert len(result) == 0

    def test_skip_train_when_queue_busy(self):
        from scheduler.action_dispatcher import filter_valid_actions
        state = make_mock_state(troop_queue=[{"troop": "Legionnaire", "count": 5, "seconds_left": 300}])
        actions = [{"name": "train_troops", "arguments": {"troop_type": "legionnaire", "count": 10}}]
        result = filter_valid_actions(actions, state)
        assert len(result) == 0


class TestCompressStateForLLM:
    def test_excludes_raw_html_fields(self):
        state = make_mock_state(population=100)
        compressed = compress_state_for_llm(state)
        # Should NOT contain large raw fields
        assert "map" not in compressed
        # Should contain key raiding fields
        assert "total_troops_home" in compressed
        assert "has_barracks" in compressed
        assert "has_rally_point" in compressed
        assert compressed["population"] == 100

    def test_total_troops_home_count(self):
        state = make_mock_state()
        state["troops"] = {"home": {"legionnaire": 10, "praetorian": 5}}
        compressed = compress_state_for_llm(state)
        assert compressed["total_troops_home"] == 15


class TestSmartSleep:
    def test_short_sleep_when_near_cap(self):
        from scheduler.sleep_manager import smart_sleep
        state = make_mock_state(resources={"wood": 750, "clay": 500, "iron": 500, "crop": 500,
                                            "warehouse_cap": 800, "granary_cap": 800})
        assert smart_sleep(state, 0) == 20

    def test_long_sleep_when_idle(self):
        from scheduler.sleep_manager import smart_sleep
        state = make_mock_state()
        assert smart_sleep(state, 0) == 60


class TestFarmListManager:
    def test_score_target_lower_pop_higher_score(self):
        flm = FarmListManager()
        tile_near = {"type": "village", "x": 0, "y": 5, "population": 30, "owner": "other", "name": "V1"}
        tile_far = {"type": "village", "x": 0, "y": 15, "population": 500, "owner": "other", "name": "V2"}
        score1 = flm._score_target(tile_near, 5)
        score2 = flm._score_target(tile_far, 15)
        assert score1 > score2


class TestCheckPrerequisites:
    def test_no_prereqs_returns_true(self):
        from agent.knowledge_base import check_prerequisites
        ok, msg = check_prerequisites("Cranny", {})
        assert ok is True
        assert msg == ""

    def test_unmet_prereq_returns_false(self):
        from agent.knowledge_base import check_prerequisites
        ok, msg = check_prerequisites("Barracks", {"Main Building": 0})
        assert ok is False
        assert "Main Building" in msg