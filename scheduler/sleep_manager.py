"""
scheduler/sleep_manager.py

Smart sleep scheduling based on build queue and resource levels.
"""
from parser.state_builder import GameState

def smart_sleep(
    state: GameState,
    consecutive_waits: int,
    min_sleep: int = 5,
    max_sleep: int = 60,
) -> int:
    bq = state.get("build_queue", [])
    tq = state.get("troop_queue", [])
    res = state.get("resources", {})
    warehouse_cap = res.get("warehouse_cap", 800)
    granary_cap = res.get("granary_cap", 800)

    if bq:
        seconds_left = bq[0].get("seconds_left", 60)
        return min(seconds_left + 5, 120)

    near_cap = any(
        res.get(r, 0) > cap * 0.85
        for r, cap in [("wood", warehouse_cap), ("clay", warehouse_cap),
                       ("iron", warehouse_cap), ("crop", granary_cap)]
    )
    if near_cap:
        return 20

    has_home_troops = bool(state.get("troops", {}).get("home"))
    if has_home_troops:
        return 30

    return max_sleep