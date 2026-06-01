"""
shared/building_data.py
Travian Legends 建築 GID 唯一事實來源。
以 parser/buildings.py 的 AID_TO_NAME 為黃金來源。
"""

# GID → 標準名稱
GID_TO_NAME: dict[int, str] = {
    1: "Woodcutter", 2: "Clay Pit", 3: "Iron Mine", 4: "Cropland",
    10: "Warehouse", 11: "Granary",
    12: "Sawmill", 13: "Brickyard", 14: "Iron Foundry", 15: "Grain Mill",
    16: "Bakery",
    17: "Marketplace", 18: "Main Building", 19: "Barracks", 20: "Stable",
    21: "Workshop", 22: "Academy", 23: "Smithy", 24: "Rally Point",
    25: "Residence", 26: "Palace", 27: "Treasury", 28: "Trade Office",
    29: "Great Barracks", 30: "Great Stable",
    31: "Hospital", 32: "Wall",
    33: "Watch Tower", 34: "Cranny",
    35: "Town Hall", 36: "Trade Route",
    37: "Armoury", 38: "Tournament Square",
    39: "Great Warehouse", 40: "Great Granary",
    41: "Waterworks", 42: "Brewery",
    43: "Horse Drinking Trough", 44: "Stone Wall",
    45: "Earth Wall", 46: "Palisade",
    47: "Makeshift Wall", 48: "Command Post",
    49: "Heros Mansion", 50: "Stonemason", 51: "Bowyer",
    52: "Siege Workshop", 53: "Chief's Quarters",
    54: "Great Wall", 55: "Trapper",
}

NAME_TO_GID: dict[str, int] = {v: k for k, v in GID_TO_NAME.items()}

_ALIAS_TO_GID: dict[str, int] = {
    "main building": 18, "mainbuilding": 18,
    "rally point": 24, "rallypoint": 24,
    "barracks": 19, "stable": 20,
    "workshop": 21, "siege workshop": 52,
    "academy": 22, "smithy": 23,
    "marketplace": 17, "market": 17,
    "warehouse": 10, "granary": 11,
    "cranny": 34, "wall": 32,
    "town hall": 35, "townhall": 35,
    "residence": 25, "palace": 26,
    "treasury": 27, "trade office": 28,
    "trade route": 36,
    "great barracks": 29, "great stable": 30,
    "hospital": 31, "watch tower": 33, "watchtower": 33,
    "heros mansion": 49, "hero's mansion": 49, "heroes mansion": 49,
    "stonemason": 50,
    "brewery": 42, "trapper": 55,
    "sawmill": 12, "brickyard": 13,
    "iron foundry": 14, "grain mill": 15, "bakery": 16,
    "great warehouse": 39, "great granary": 40,
    "horse drinking trough": 43,
    "command post": 48,
    "chiefs quarters": 53, "chief's quarters": 53,
    "great wall": 54,
    "tournament square": 38,
}


def get_gid(name: str) -> int | None:
    if not name:
        return None
    key = name.strip().lower()
    return _ALIAS_TO_GID.get(key) or NAME_TO_GID.get(name.strip().title())


def get_name(gid: int) -> str | None:
    return GID_TO_NAME.get(gid)