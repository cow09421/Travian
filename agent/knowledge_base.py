import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from config import config
from parser.state_builder import GameState


RESOURCE_FIELD_COSTS = {
    "wood_cutters": {
        0: {"wood": 50, "clay": 40, "iron": 30, "crop": 20, "time_sec": 460},
        1: {"wood": 100, "clay": 80, "iron": 60, "crop": 40, "time_sec": 920},
        2: {"wood": 200, "clay": 160, "iron": 120, "crop": 80, "time_sec": 1880},
        3: {"wood": 400, "clay": 320, "iron": 240, "crop": 160, "time_sec": 3760},
        4: {"wood": 800, "clay": 640, "iron": 480, "crop": 320, "time_sec": 7520},
        5: {"wood": 1600, "clay": 1280, "iron": 960, "crop": 640, "time_sec": 15040},
        6: {"wood": 3200, "clay": 2560, "iron": 1920, "crop": 1280, "time_sec": 30080},
        7: {"wood": 6400, "clay": 5120, "iron": 3840, "crop": 2560, "time_sec": 60160},
        8: {"wood": 12800, "clay": 10240, "iron": 7680, "crop": 5120, "time_sec": 120320},
        9: {"wood": 25600, "clay": 20480, "iron": 15360, "crop": 10240, "time_sec": 240640},
        10: {"wood": 51200, "clay": 40960, "iron": 30720, "crop": 20480, "time_sec": 481280},
        11: {"wood": 102400, "clay": 81920, "iron": 61440, "crop": 40960, "time_sec": 962560},
        12: {"wood": 204800, "clay": 163840, "iron": 122880, "crop": 81920, "time_sec": 1925120},
    },
    "clay_pits": {
        0: {"wood": 80, "clay": 40, "iron": 30, "crop": 20, "time_sec": 460},
        1: {"wood": 65, "clay": 100, "iron": 45, "crop": 30, "time_sec": 920},
        2: {"wood": 130, "clay": 200, "iron": 90, "crop": 60, "time_sec": 1880},
        3: {"wood": 260, "clay": 400, "iron": 180, "crop": 120, "time_sec": 3760},
        4: {"wood": 520, "clay": 800, "iron": 360, "crop": 240, "time_sec": 7520},
        5: {"wood": 1040, "clay": 1600, "iron": 720, "crop": 480, "time_sec": 15040},
        6: {"wood": 2080, "clay": 3200, "iron": 1440, "crop": 960, "time_sec": 30080},
        7: {"wood": 4160, "clay": 6400, "iron": 2880, "crop": 1920, "time_sec": 60160},
        8: {"wood": 8320, "clay": 12800, "iron": 5760, "crop": 3840, "time_sec": 120320},
        9: {"wood": 16640, "clay": 25600, "iron": 11520, "crop": 7680, "time_sec": 240640},
        10: {"wood": 33280, "clay": 51200, "iron": 23040, "crop": 15360, "time_sec": 481280},
        11: {"wood": 66560, "clay": 102400, "iron": 46080, "crop": 30720, "time_sec": 962560},
        12: {"wood": 133120, "clay": 204800, "iron": 92160, "crop": 61440, "time_sec": 1925120},
    },
    "iron_mines": {
        0: {"wood": 100, "clay": 80, "iron": 30, "crop": 60, "time_sec": 460},
        1: {"wood": 200, "clay": 160, "iron": 60, "crop": 120, "time_sec": 920},
        2: {"wood": 400, "clay": 320, "iron": 120, "crop": 240, "time_sec": 1880},
        3: {"wood": 800, "clay": 640, "iron": 240, "crop": 480, "time_sec": 3760},
        4: {"wood": 1600, "clay": 1280, "iron": 480, "crop": 960, "time_sec": 7520},
        5: {"wood": 3200, "clay": 2560, "iron": 960, "crop": 1920, "time_sec": 15040},
        6: {"wood": 6400, "clay": 5120, "iron": 1920, "crop": 3840, "time_sec": 30080},
        7: {"wood": 12800, "clay": 10240, "iron": 3840, "crop": 7680, "time_sec": 60160},
        8: {"wood": 25600, "clay": 20480, "iron": 7680, "crop": 15360, "time_sec": 120320},
        9: {"wood": 51200, "clay": 40960, "iron": 15360, "crop": 30720, "time_sec": 240640},
        10: {"wood": 102400, "clay": 81920, "iron": 30720, "crop": 61440, "time_sec": 481280},
        11: {"wood": 204800, "clay": 163840, "iron": 61440, "crop": 122880, "time_sec": 962560},
        12: {"wood": 409600, "clay": 327680, "iron": 122880, "crop": 245760, "time_sec": 1925120},
    },
    "croplands": {
        0: {"wood": 70, "clay": 90, "iron": 70, "crop": 20, "time_sec": 460},
        1: {"wood": 140, "clay": 180, "iron": 140, "crop": 40, "time_sec": 920},
        2: {"wood": 280, "clay": 360, "iron": 280, "crop": 80, "time_sec": 1880},
        3: {"wood": 560, "clay": 720, "iron": 560, "crop": 160, "time_sec": 3760},
        4: {"wood": 1120, "clay": 1440, "iron": 1120, "crop": 320, "time_sec": 7520},
        5: {"wood": 2240, "clay": 2880, "iron": 2240, "crop": 640, "time_sec": 15040},
        6: {"wood": 4480, "clay": 5760, "iron": 4480, "crop": 1280, "time_sec": 30080},
        7: {"wood": 8960, "clay": 11520, "iron": 8960, "crop": 2560, "time_sec": 60160},
        8: {"wood": 17920, "clay": 23040, "iron": 17920, "crop": 5120, "time_sec": 120320},
        9: {"wood": 35840, "clay": 46080, "iron": 35840, "crop": 10240, "time_sec": 240640},
        10: {"wood": 71680, "clay": 92160, "iron": 71680, "crop": 20480, "time_sec": 481280},
        11: {"wood": 143360, "clay": 184320, "iron": 143360, "crop": 40960, "time_sec": 962560},
        12: {"wood": 286720, "clay": 368640, "iron": 286720, "crop": 81920, "time_sec": 1925120},
    },
}

BUILDING_COSTS = {
    "Main Building": {
        0: {"wood": 70, "clay": 40, "iron": 60, "crop": 15, "time_sec": 700},
        1: {"wood": 117, "clay": 67, "iron": 100, "crop": 25, "time_sec": 1170},
        2: {"wood": 196, "clay": 112, "iron": 167, "crop": 42, "time_sec": 1960},
        3: {"wood": 327, "clay": 187, "iron": 279, "crop": 70, "time_sec": 3270},
        4: {"wood": 546, "clay": 312, "iron": 466, "crop": 117, "time_sec": 5460},
        5: {"wood": 912, "clay": 521, "iron": 778, "crop": 195, "time_sec": 9120},
        6: {"wood": 1523, "clay": 870, "iron": 1300, "crop": 325, "time_sec": 15230},
        7: {"wood": 2543, "clay": 1452, "iron": 2170, "crop": 543, "time_sec": 25430},
        8: {"wood": 4247, "clay": 2425, "iron": 3624, "crop": 907, "time_sec": 42470},
        9: {"wood": 7093, "clay": 4050, "iron": 6052, "crop": 1515, "time_sec": 70930},
        10: {"wood": 11845, "clay": 6764, "iron": 10107, "crop": 2530, "time_sec": 118450},
    },
    "Warehouse": {
        0: {"wood": 130, "clay": 160, "iron": 90, "crop": 40, "time_sec": 1600, "capacity": 800},
        1: {"wood": 165, "clay": 205, "iron": 115, "crop": 50, "time_sec": 1800, "capacity": 1200},
        2: {"wood": 210, "clay": 260, "iron": 145, "crop": 65, "time_sec": 2100, "capacity": 1800},
        3: {"wood": 265, "clay": 330, "iron": 185, "crop": 82, "time_sec": 2650, "capacity": 2400},
        4: {"wood": 340, "clay": 420, "iron": 235, "crop": 104, "time_sec": 3400, "capacity": 3200},
        5: {"wood": 430, "clay": 535, "iron": 300, "crop": 133, "time_sec": 4300, "capacity": 4000},
        6: {"wood": 545, "clay": 680, "iron": 381, "crop": 169, "time_sec": 5450, "capacity": 5000},
        7: {"wood": 695, "clay": 865, "iron": 485, "crop": 214, "time_sec": 6950, "capacity": 6200},
        8: {"wood": 880, "clay": 1100, "iron": 616, "crop": 272, "time_sec": 8800, "capacity": 7600},
        9: {"wood": 1120, "clay": 1395, "iron": 782, "crop": 346, "time_sec": 11200, "capacity": 9200},
        10: {"wood": 1420, "clay": 1775, "iron": 994, "crop": 440, "time_sec": 14200, "capacity": 11000},
    },
    "Granary": {
        0: {"wood": 80, "clay": 100, "iron": 70, "crop": 20, "time_sec": 1200, "capacity": 800},
        1: {"wood": 100, "clay": 128, "iron": 89, "crop": 25, "time_sec": 1500, "capacity": 1200},
        2: {"wood": 128, "clay": 163, "iron": 114, "crop": 32, "time_sec": 1900, "capacity": 1800},
        3: {"wood": 163, "clay": 207, "iron": 145, "crop": 41, "time_sec": 2400, "capacity": 2400},
        4: {"wood": 207, "clay": 264, "iron": 185, "crop": 52, "time_sec": 3050, "capacity": 3200},
        5: {"wood": 264, "clay": 336, "iron": 235, "crop": 66, "time_sec": 3900, "capacity": 4000},
        6: {"wood": 336, "clay": 427, "iron": 300, "crop": 84, "time_sec": 4950, "capacity": 5000},
        7: {"wood": 427, "clay": 544, "iron": 381, "crop": 107, "time_sec": 6300, "capacity": 6200},
        8: {"wood": 544, "clay": 692, "iron": 485, "crop": 136, "time_sec": 8000, "capacity": 7600},
        9: {"wood": 692, "clay": 881, "iron": 617, "crop": 173, "time_sec": 10200, "capacity": 9200},
        10: {"wood": 881, "clay": 1122, "iron": 785, "crop": 220, "time_sec": 13000, "capacity": 11000},
    },
    "Barracks": {
        0: {"wood": 210, "clay": 140, "iron": 260, "crop": 120, "time_sec": 2600},
        1: {"wood": 267, "clay": 178, "iron": 330, "crop": 153, "time_sec": 3300},
        2: {"wood": 340, "clay": 226, "iron": 420, "crop": 194, "time_sec": 4200},
        3: {"wood": 432, "clay": 288, "iron": 534, "crop": 247, "time_sec": 5350},
        4: {"wood": 549, "clay": 366, "iron": 679, "crop": 314, "time_sec": 6800},
        5: {"wood": 698, "clay": 465, "iron": 864, "crop": 399, "time_sec": 8650},
    },
    "Rally Point": {
        0: {"wood": 110, "clay": 160, "iron": 70, "crop": 60, "time_sec": 1000},
        1: {"wood": 140, "clay": 204, "iron": 89, "crop": 76, "time_sec": 1270},
        2: {"wood": 178, "clay": 259, "iron": 113, "crop": 97, "time_sec": 1620},
        3: {"wood": 226, "clay": 330, "iron": 144, "crop": 123, "time_sec": 2060},
        4: {"wood": 287, "clay": 419, "iron": 183, "crop": 156, "time_sec": 2620},
        5: {"wood": 365, "clay": 533, "iron": 233, "crop": 198, "time_sec": 3330},
    },
    "Wall": {
        0: {"wood": 70, "clay": 90, "iron": 170, "crop": 0, "time_sec": 1500},
        1: {"wood": 89, "clay": 114, "iron": 216, "crop": 0, "time_sec": 1900},
        2: {"wood": 113, "clay": 145, "iron": 275, "crop": 0, "time_sec": 2420},
        3: {"wood": 144, "clay": 185, "iron": 350, "crop": 0, "time_sec": 3080},
        4: {"wood": 183, "clay": 235, "iron": 445, "crop": 0, "time_sec": 3910},
        5: {"wood": 233, "clay": 299, "iron": 566, "crop": 0, "time_sec": 4970},
    },
    "Cranny": {
        0: {"wood": 40, "clay": 50, "iron": 30, "crop": 10, "time_sec": 560, "capacity": 200},
        1: {"wood": 51, "clay": 64, "iron": 38, "crop": 13, "time_sec": 712, "capacity": 400},
        2: {"wood": 65, "clay": 81, "iron": 48, "crop": 16, "time_sec": 907, "capacity": 600},
        3: {"wood": 82, "clay": 103, "iron": 61, "crop": 21, "time_sec": 1154, "capacity": 800},
        4: {"wood": 105, "clay": 131, "iron": 78, "crop": 26, "time_sec": 1470, "capacity": 1000},
        5: {"wood": 133, "clay": 167, "iron": 99, "crop": 34, "time_sec": 1872, "capacity": 1200},
        6: {"wood": 170, "clay": 213, "iron": 126, "crop": 43, "time_sec": 2381, "capacity": 1400},
        7: {"wood": 216, "clay": 271, "iron": 160, "crop": 55, "time_sec": 3031, "capacity": 1600},
        8: {"wood": 275, "clay": 344, "iron": 204, "crop": 70, "time_sec": 3858, "capacity": 1800},
        9: {"wood": 350, "clay": 438, "iron": 259, "crop": 89, "time_sec": 4912, "capacity": 2000},
        10: {"wood": 445, "clay": 557, "iron": 330, "crop": 113, "time_sec": 6250, "capacity": 2200},
    },
    "Stable": {
        0: {"wood": 260, "clay": 140, "iron": 220, "crop": 100, "time_sec": 2400},
    },
    "Smithy": {
        0: {"wood": 180, "clay": 250, "iron": 500, "crop": 160, "time_sec": 3200},
    },
    "Academy": {
        0: {"wood": 220, "clay": 160, "iron": 90, "crop": 40, "time_sec": 2000},
    },
    "Marketplace": {
        0: {"wood": 80, "clay": 70, "iron": 120, "crop": 70, "time_sec": 1800},
    },
    "Hero's Mansion": {
        0: {"wood": 700, "clay": 670, "iron": 250, "crop": 250, "time_sec": 4000},
    },
    "Town Hall": {
        0: {"wood": 1250, "clay": 1110, "iron": 1260, "crop": 600, "time_sec": 18000},
    },
    "Sawmill": {
        0: {"wood": 520, "clay": 380, "iron": 290, "crop": 90, "time_sec": 5000},
    },
    "Brickyard": {
        0: {"wood": 440, "clay": 480, "iron": 320, "crop": 50, "time_sec": 5000},
    },
    "Iron Foundry": {
        0: {"wood": 200, "clay": 450, "iron": 510, "crop": 120, "time_sec": 5000},
    },
    "Grain Mill": {
        0: {"wood": 500, "clay": 440, "iron": 380, "crop": 1240, "time_sec": 5000},
    },
    }


KNOWLEDGE_SOURCES = [
    {
        "name": "travian_wiki_resources",
        "url": "https://travian.fandom.com/wiki/Resource_fields",
        "type": "wiki",
        "update_interval_hours": 72,
    },
    {
        "name": "travian_wiki_buildings",
        "url": "https://travian.fandom.com/wiki/Buildings",
        "type": "wiki",
        "update_interval_hours": 72,
    },
]

BUILDING_PREREQUISITES: dict[str, dict[str, int]] = {
    "Barracks": {"Main Building": 3},
    "Stable": {"Main Building": 5, "Barracks": 3},
    "Workshop": {"Main Building": 5, "Academy": 10},
    "Academy": {"Main Building": 3, "Barracks": 3},
    "Smithy": {"Main Building": 3, "Academy": 1},
    "Sawmill": {"Main Building": 5, "Woodcutter": 10},
    "Brickyard": {"Main Building": 5, "Clay Pit": 10},
    "Iron Foundry": {"Main Building": 5, "Iron Mine": 10},
    "Grain Mill": {"Main Building": 5, "Cropland": 5},
    "Marketplace": {"Main Building": 3, "Warehouse": 1, "Granary": 1},
    "Embassy": {"Main Building": 1},
    "Town Hall": {"Main Building": 10, "Academy": 10},
    "Residence": {"Main Building": 5},
    "Palace": {"Main Building": 5, "Embassy": 1},
    "Hero's Mansion": {"Rally Point": 1, "Main Building": 3},
    "Hospital": {"Main Building": 3, "Barracks": 1},
    "Wall": {},
    "Cranny": {},
}


def check_prerequisites(building_name: str, buildings: dict) -> tuple[bool, str]:
    prereqs = BUILDING_PREREQUISITES.get(building_name, {})
    if not prereqs:
        return True, ""
    for req_name, req_level in prereqs.items():
        current = buildings.get(req_name, 0)
        if current < req_level:
            return False, f"需要 {req_name} Lv{req_level}（當前 Lv{current}）"
    return True, ""


GAME_MECHANICS_TEXT = """# Travian Legends 核心機制

## 建造隊列
- 免費帳號：同時只能建造 1 個（資源田或建築）
- Plus 帳號：資源田和建築可各一個同時進行
- 新玩家保護期：無法攻擊他人，也無法被攻擊

## 資源田
- 18 塊田：木材x4、黏土x4、鐵x4、糧食x6
- slot_id 從 1 開始，1-18 對應 dorf1 的各個格子
- 升級成本隨等級指數增長（每級約翻倍）
- 糧食田是最重要的，因為人口和軍隊都消耗糧食

## 倉庫/穀倉
- Warehouse：儲存木材、黏土、鐵
- Granary：儲存糧食
- 升級倉庫是前期重要任務（避免資源浪費）
- 預設容量 800，升級後增加

## 軍事
- 新手保護期（100小時）內禁止攻擊
- 先建 Rally Point 才能派兵
- 先建 Barracks 才能訓練步兵
- 劫掠（Raid）只搶資源，攻擊（Attack）消滅防禦

## Main Building
- 等級越高，建造速度越快
- Lv1：標準速度，Lv10：快 33%，Lv20：快 60%
"""


class KnowledgeBase:
    def __init__(self):
        base = Path(r"C:\AI\Travian").resolve()
        self.knowledge_dir = base / "knowledge"
        self.static_dir = self.knowledge_dir / "static"
        self.dynamic_dir = self.knowledge_dir / "dynamic"
        self.learned_dir = self.knowledge_dir / "learned"
        self._cached_summary: Optional[str] = None
        self._cache_time: Optional[datetime] = None

    def init_dirs(self):
        for d in [self.static_dir, self.dynamic_dir, self.learned_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self._write_static_data()
        logger.info(f"📚 知識庫初始化完成: {self.knowledge_dir}")

    def _write_static_data(self):
        costs_file = self.static_dir / "resource_field_costs.json"
        if not costs_file.exists():
            costs_file.write_text(
                json.dumps(RESOURCE_FIELD_COSTS, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        building_file = self.static_dir / "building_costs.json"
        if not building_file.exists():
            building_file.write_text(
                json.dumps(BUILDING_COSTS, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        mechanics_file = self.static_dir / "game_mechanics.md"
        if not mechanics_file.exists():
            mechanics_file.write_text(GAME_MECHANICS_TEXT, encoding="utf-8")

    async def search_and_update(self):
        logger.info("🔍 開始搜尋 Travian 知識更新...")

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for source in KNOWLEDGE_SOURCES:
                try:
                    last_update = self._get_last_update(source["name"])
                    if last_update:
                        hours_since = (datetime.now(timezone.utc) - last_update).total_seconds() / 3600
                        if hours_since < source["update_interval_hours"]:
                            logger.debug(f"跳過 {source['name']}（{hours_since:.1f}h 前已更新）")
                            continue

                    logger.info(f"📥 從 {source['url']} 抓取知識...")
                    resp = await client.get(source["url"])
                    if resp.status_code == 200:
                        extracted = self._extract_wiki_content(resp.text, source["name"])
                        if extracted:
                            self._save_dynamic_knowledge(source["name"], extracted)
                            logger.info(f"✅ 已更新: {source['name']} ({len(extracted)} 字)")

                    await asyncio.sleep(2)

                except Exception as e:
                    logger.warning(f"抓取 {source['name']} 失敗: {e}")

        self._invalidate_cache()

    def _extract_wiki_content(self, html: str, source_name: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        content = soup.find(class_=re.compile(r"mw-content|article|content"))
        if not content:
            content = soup.find("main") or soup.body
        if not content:
            return ""
        text = content.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:5000]

    def record_failure(self, action_type: str, params: dict, error: str, state_context: dict):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_type": action_type,
            "params": params,
            "error": error,
            "context": {
                "build_queue_len": len(state_context.get("build_queue", [])),
                "resources": state_context.get("resources", {}),
            }
        }
        failure_file = self.learned_dir / "failed_actions.jsonl"
        with open(failure_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_success(self, action_type: str, params: dict, result: str):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_type": action_type,
            "params": params,
            "result": result,
        }
        success_file = self.learned_dir / "successful_patterns.jsonl"
        with open(success_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_upgrade_cost(self, field_type: str, current_level: int) -> Optional[dict]:
        costs = RESOURCE_FIELD_COSTS.get(field_type, {})
        return costs.get(current_level)

    def can_afford_upgrade(self, field_type: str, current_level: int, resources: dict) -> bool:
        cost = self.get_upgrade_cost(field_type, current_level)
        if not cost:
            return False
        return (
            resources.get("wood", 0) >= cost["wood"] and
            resources.get("clay", 0) >= cost["clay"] and
            resources.get("iron", 0) >= cost["iron"] and
            resources.get("crop", 0) >= cost["crop"]
        )

    def get_cheapest_affordable_field(self, resource_fields: dict, resources: dict) -> Optional[dict]:
        candidates = []
        for field_type, fields in resource_fields.items():
            for field in fields:
                level = field.get("level", 0)
                slot = field.get("slot", 0)
                if slot <= 0:
                    continue
                if self.can_afford_upgrade(field_type, level, resources):
                    cost = self.get_upgrade_cost(field_type, level)
                    if cost:
                        total_cost = cost["wood"] + cost["clay"] + cost["iron"] + cost["crop"]
                        candidates.append({
                            "field_type": field_type,
                            "slot_id": slot,
                            "current_level": level,
                            "total_cost": total_cost,
                        })

        if not candidates:
            return None

        return min(candidates, key=lambda x: (x["current_level"], x["total_cost"]))

    def get_new_building_recommendation(self, state: GameState) -> Optional[dict]:
        empty_slots = state.get("empty_building_slots", [])
        if not empty_slots:
            return None

        buildings = state.get("buildings", {})
        resources = state.get("resources", {})
        wood = resources.get("wood", 0)
        clay = resources.get("clay", 0)
        iron = resources.get("iron", 0)
        crop = resources.get("crop", 0)
        warehouse_cap = resources.get("warehouse_cap", 800)
        granary_cap = resources.get("granary_cap", 800)

        def can_afford(bname: str) -> bool:
            cost = BUILDING_COSTS.get(bname, {}).get(0)
            if not cost:
                return False
            return (wood >= cost["wood"] and clay >= cost["clay"]
                    and iron >= cost["iron"] and crop >= cost["crop"])

        # P1: 沒有倉庫/穀倉容量嚴重不足
        if warehouse_cap > 0:
            near_wh = (wood > warehouse_cap * 0.8 or clay > warehouse_cap * 0.8
                       or iron > warehouse_cap * 0.8)
            near_gr = crop > granary_cap * 0.8
            if near_wh and "Warehouse" not in buildings:
                return {"building_name": "Warehouse", "gid": 10,
                        "reason": "資源即將爆倉，需要倉庫擴充容量",
                        "priority": "high", "can_afford": can_afford("Warehouse")}
            if near_gr and "Granary" not in buildings:
                return {"building_name": "Granary", "gid": 11,
                        "reason": "糧食即將爆倉，需要穀倉擴充容量",
                        "priority": "high", "can_afford": can_afford("Granary")}

        def prereq_met(bname: str) -> tuple[bool, str]:
            return check_prerequisites(bname, buildings)

        # P2: 沒有兵舍
        if "Barracks" not in buildings:
            ok, reason = prereq_met("Barracks")
            if not ok:
                return {"building_name": "Barracks", "gid": 19,
                        "reason": f"兵舍是軍事發展的第一步（但{reason}）",
                        "priority": "medium", "can_afford": can_afford("Barracks"),
                        "blocked_by": reason}
            fields = state.get("resource_fields", {})
            all_levels = [f.get("level", 0) for flist in fields.values() for f in flist]
            avg = sum(all_levels) / max(len(all_levels), 1)
            if avg >= 2:
                return {"building_name": "Barracks", "gid": 19,
                        "reason": "資源田已有基礎，建設兵舍開始軍事發展",
                        "priority": "high", "can_afford": can_afford("Barracks")}
            return {"building_name": "Barracks", "gid": 19,
                    "reason": "兵舍是軍事發展的第一步，優先建造",
                    "priority": "medium", "can_afford": can_afford("Barracks")}

        # P3: 沒有 Rally Point
        if "Rally Point" not in buildings:
            return {"building_name": "Rally Point", "gid": 36,
                    "reason": "必要建築，沒有它無法派兵出征",
                    "priority": "high", "can_afford": can_afford("Rally Point")}

        # P4: 沒有 Cranny
        if "Cranny" not in buildings:
            return {"building_name": "Cranny", "gid": 23,
                    "reason": "保護資源不被劫掠，新手必備",
                    "priority": "medium", "can_afford": can_afford("Cranny")}

        # P5: 有兵舍但沒有 Smithy
        if "Barracks" in buildings and "Smithy" not in buildings:
            ok, reason = prereq_met("Smithy")
            if not ok:
                return {"building_name": "Smithy", "gid": 13,
                        "reason": f"提升部隊攻防能力（但{reason}）",
                        "priority": "low", "can_afford": can_afford("Smithy"),
                        "blocked_by": reason}
            return {"building_name": "Smithy", "gid": 13,
                    "reason": "提升部隊攻防能力",
                    "priority": "medium", "can_afford": can_afford("Smithy")}

        # P6: 有 Barracks 但沒有 Academy
        if "Barracks" in buildings and "Academy" not in buildings:
            ok, reason = prereq_met("Academy")
            if not ok:
                return {"building_name": "Academy", "gid": 17,
                        "reason": f"解鎖進階兵種（但{reason}）",
                        "priority": "low", "can_afford": can_afford("Academy"),
                        "blocked_by": reason}
            return {"building_name": "Academy", "gid": 17,
                    "reason": "解鎖進階兵種",
                    "priority": "medium", "can_afford": can_afford("Academy")}

        return None

    def get_recommended_building_action(self, state: dict) -> Optional[dict]:
        resources = state.get("resources", {})
        buildings = state.get("buildings", {})
        empty_slots = state.get("empty_building_slots", [])

        if not empty_slots:
            return None

        wood = resources.get("wood", 0)
        clay = resources.get("clay", 0)
        iron = resources.get("iron", 0)
        crop = resources.get("crop", 0)
        warehouse_cap = resources.get("warehouse_cap", 800)
        granary_cap = resources.get("granary_cap", 800)

        if (wood > warehouse_cap * 0.75 or clay > warehouse_cap * 0.75
                or iron > warehouse_cap * 0.75) and "Warehouse" not in buildings:
            return {"building_name": "Warehouse", "reason": "資源快滿，需要建倉庫"}

        if crop > granary_cap * 0.75 and "Granary" not in buildings:
            return {"building_name": "Granary", "reason": "糧食快滿，需要建穀倉"}

        if "Rally Point" not in buildings:
            return {"building_name": "Rally Point", "reason": "必要建築，用於派兵"}

        if "Barracks" not in buildings:
            fields = state.get("resource_fields", {})
            all_levels = [f.get("level", 0) for flist in fields.values() for f in flist]
            avg = sum(all_levels) / max(len(all_levels), 1)
            if avg >= 2:
                return {"building_name": "Barracks", "reason": "資源田已有基礎，開始建軍事建築"}

        return None

    def get_summary_for_llm(self) -> str:
        if self._cached_summary and self._cache_time:
            age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
            if age < 300:
                return self._cached_summary

        parts = []

        failure_file = self.learned_dir / "failed_actions.jsonl"
        if failure_file.exists():
            lines = failure_file.read_text(encoding="utf-8").strip().split("\n")
            recent_failures = []
            for line in lines[-10:]:
                try:
                    r = json.loads(line)
                    recent_failures.append(f"- [{r['action_type']}] 失敗原因: {r['error'][:80]}")
                except Exception:
                    pass
            if recent_failures:
                parts.append("### 近期失敗教訓\n" + "\n".join(recent_failures))

        notes_file = self.learned_dir / "strategy_notes.md"
        if notes_file.exists():
            notes = notes_file.read_text(encoding="utf-8")[:1000]
            if notes.strip():
                parts.append(f"### 策略筆記\n{notes}")

        dynamic_files = list(self.dynamic_dir.glob("*.md"))
        for f in dynamic_files[:2]:
            content = f.read_text(encoding="utf-8")[:500]
            if content.strip():
                parts.append(f"### {f.stem}\n{content}")

        summary = "\n\n".join(parts) if parts else "（知識庫初始化中）"
        self._cached_summary = summary
        self._cache_time = datetime.now(timezone.utc)
        return summary

    def _get_last_update(self, source_name: str) -> Optional[datetime]:
        marker = self.dynamic_dir / f"{source_name}.updated"
        if marker.exists():
            try:
                ts = float(marker.read_text())
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
        return None

    def _invalidate_cache(self):
        self._cached_summary = None
        self._cache_time = None

    def _save_dynamic_knowledge(self, source_name: str, content: str):
        file = self.dynamic_dir / f"{source_name}.md"
        file.write_text(
            f"# {source_name}\n更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{content}",
            encoding="utf-8"
        )
        marker = self.dynamic_dir / f"{source_name}.updated"
        marker.write_text(str(datetime.now(timezone.utc).timestamp()))


knowledge_base = KnowledgeBase()