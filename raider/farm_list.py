"""
管理農場目標列表 — 搶劫是成長的引擎
"""
import json
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta


@dataclass
class FarmTarget:
    coord_x: int
    coord_y: int
    village_name: str
    owner: str
    population: int
    last_raided: Optional[datetime] = None
    avg_loot: int = 0
    raid_interval: int = 3600
    is_active: bool = True
    defense_level: str = "none"

    @property
    def worth_raiding(self) -> bool:
        if not self.is_active:
            return False
        if self.defense_level == "heavy":
            return False
        if self.population < 50:
            return True
        return self.avg_loot > 100

    @property
    def ready_to_raid(self) -> bool:
        if self.last_raided is None:
            return True
        return (datetime.now() - self.last_raided).total_seconds() >= self.raid_interval


class FarmListManager:
    def __init__(self):
        self.targets: List[FarmTarget] = []

    def scan_neighbors(self, map_data: dict, my_coord: tuple, radius: int = 15):
        candidates = []
        for tile in map_data.get("tiles", []):
            if tile.get("type") != "village":
                continue
            if tile.get("owner") == "self":
                continue
            dist = abs(tile["x"] - my_coord[0]) + abs(tile["y"] - my_coord[1])
            if dist > radius:
                continue
            score = self._score_target(tile, dist)
            candidates.append((score, tile))

        candidates.sort(reverse=True)
        self.targets = [
            FarmTarget(
                coord_x=t["x"],
                coord_y=t["y"],
                village_name=t.get("name", "Unknown"),
                owner=t.get("owner", "Unknown"),
                population=t.get("population", 0),
            )
            for _, t in candidates[:30]
        ]

    def _score_target(self, tile: dict, distance: int) -> float:
        pop = tile.get("population", 999)
        score = 1000.0 / max(pop, 1)
        score -= distance * 2
        return score

    def get_ready_targets(self) -> List[FarmTarget]:
        return [t for t in self.targets if t.worth_raiding and t.ready_to_raid]

    def update_loot(self, target: FarmTarget, loot: int, had_defense: bool):
        target.last_raided = datetime.now()
        target.avg_loot = int(target.avg_loot * 0.7 + loot * 0.3)
        if had_defense:
            target.defense_level = "light"
        if loot == 0 and not had_defense:
            target.is_active = False
        if target.avg_loot > 500:
            target.raid_interval = 1800
        elif target.avg_loot > 200:
            target.raid_interval = 3600
        else:
            target.raid_interval = 7200


farm_list_manager = FarmListManager()