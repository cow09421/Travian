"""
shared/troop_data.py
Travian Legends 兵種資料唯一事實來源。
index = 訓練表單 input[name='t{index}']（1-based）
building_gid = 訓練建築 GID (19=Barracks, 20=Stable, 21=Workshop)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TroopInfo:
    canonical_name: str
    index: int
    building_gid: int
    aliases: tuple[str, ...]
    attack: int = 0
    def_infantry: int = 0
    def_cavalry: int = 0
    speed: int = 0
    carry: int = 0
    crop_per_hour: int = 1
    training_cost: dict | None = None
    training_time_sec: int = 0
    unlock_requirements: dict | None = None


TROOP_REGISTRY: list[TroopInfo] = [
    # Barracks (GID=19)
    TroopInfo("Legionnaire",        1, 19, ("legionnaire",)),
    TroopInfo("Praetorian",         2, 19, ("praetorian",)),
    TroopInfo("Imperian",           3, 19, ("imperian",)),
    TroopInfo("Phalanx",            1, 19, ("phalanx",),
              attack=15, def_infantry=40, def_cavalry=50, speed=7, carry=35,
              training_cost={"wood": 100, "clay": 130, "iron": 55, "crop": 30}, training_time_sec=460),
    TroopInfo("Swordsman",          2, 19, ("swordsman",),
              attack=65, def_infantry=35, def_cavalry=20, speed=6, carry=45,
              training_cost={"wood": 170, "clay": 180, "iron": 250, "crop": 80}, training_time_sec=1120,
              unlock_requirements={"Academy": 1}),
    TroopInfo("Clubswinger",        1, 19, ("clubswinger", "club swinger")),
    TroopInfo("Spearman",           2, 19, ("spearman",)),
    TroopInfo("Axeman",             3, 19, ("axeman", "axe man")),
    TroopInfo("Scout",              4, 19, ("scout", "teutonic scout")),
    TroopInfo("Pathfinder",         3, 19, ("pathfinder",),
              attack=0, def_infantry=20, def_cavalry=10, speed=17, carry=0, crop_per_hour=2,
              training_cost={"wood": 170, "clay": 150, "iron": 20, "crop": 40}, training_time_sec=933,
              unlock_requirements={"Academy": 5, "Stable": 1}),

    # Stable (GID=20)
    TroopInfo("Equites Legati",     1, 20, ("equites legati", "eq. legati")),
    TroopInfo("Equites Imperatoris",2, 20, ("equites imperatoris", "eq. imperatoris")),
    TroopInfo("Equites Caesaris",   3, 20, ("equites caesaris", "eq. caesaris")),
    TroopInfo("Theutates Thunder",  1, 20, ("theutates thunder", "theutates", "tt"),
              attack=100, def_infantry=9, def_cavalry=105, speed=19, carry=75, crop_per_hour=2,
              training_cost={"wood": 350, "clay": 450, "iron": 230, "crop": 60}, training_time_sec=1600,
              unlock_requirements={"Academy": 5, "Stable": 1}),
    TroopInfo("Druidrider",         2, 20, ("druidrider", "druid rider"),
              attack=45, def_infantry=115, def_cavalry=55, speed=16, carry=35, crop_per_hour=2,
              training_cost={"wood": 360, "clay": 330, "iron": 280, "crop": 120}, training_time_sec=1320,
              unlock_requirements={"Academy": 5, "Stable": 3}),
    TroopInfo("Haeduan",            3, 20, ("haeduan",),
              attack=140, def_infantry=50, def_cavalry=165, speed=13, carry=65, crop_per_hour=3,
              training_cost={"wood": 500, "clay": 620, "iron": 675, "crop": 170}, training_time_sec=3600,
              unlock_requirements={"Academy": 15, "Stable": 10}),
    TroopInfo("Paladin",            1, 20, ("paladin",)),
    TroopInfo("Teutonic Knight",    2, 20, ("teutonic knight", "knight")),

    # Workshop (GID=21)
    TroopInfo("Ram",                1, 21, ("ram",)),
    TroopInfo("Fire Catapult",      2, 21, ("fire catapult", "fire cat")),
    TroopInfo("Catapult",           2, 21, ("catapult", "cat")),
]


def _build_lookup() -> dict[str, TroopInfo]:
    lookup: dict[str, TroopInfo] = {}
    for t in TROOP_REGISTRY:
        lookup[t.canonical_name.lower()] = t
        for alias in t.aliases:
            lookup[alias.lower()] = t
    return lookup

_LOOKUP: dict[str, TroopInfo] = _build_lookup()


def get_troop(name: str) -> TroopInfo | None:
    return _LOOKUP.get(name.strip().lower())


def get_troop_index(name: str) -> int:
    info = get_troop(name)
    return info.index if info else 1


def get_building_gid_for_troop(name: str) -> int | None:
    info = get_troop(name)
    return info.building_gid if info else None


def get_building_name_for_troop(name: str) -> str | None:
    gid = get_building_gid_for_troop(name)
    return {19: "Barracks", 20: "Stable", 21: "Workshop"}.get(gid)


def normalize_troop_name(raw: str) -> str:
    info = get_troop(raw)
    if info:
        return info.canonical_name
    return raw.strip().title().replace("_", " ")


# 向後相容字典
BARRACKS_TROOPS: dict[str, str] = {
    t.aliases[0]: t.canonical_name
    for t in TROOP_REGISTRY if t.building_gid == 19
}
STABLE_TROOPS: dict[str, str] = {
    t.aliases[0]: t.canonical_name
    for t in TROOP_REGISTRY if t.building_gid == 20
}
WORKSHOP_TROOPS: dict[str, str] = {
    t.aliases[0]: t.canonical_name
    for t in TROOP_REGISTRY if t.building_gid == 21
}