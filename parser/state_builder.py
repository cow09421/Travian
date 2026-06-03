from datetime import datetime, timezone
import re
from typing import Optional, TypedDict, NotRequired

from loguru import logger

from parser.resources import parse_resources
from parser.buildings import parse_buildings
from parser.queue import parse_build_queue, parse_troop_queue, calculate_next_free_slot
from parser.troops import parse_troops
from parser.map_scanner import parse_map
from parser.hero import parse_hero_state


class Resources(TypedDict, total=False):
    wood: int
    clay: int
    iron: int
    crop: int
    wood_rate: int
    clay_rate: int
    iron_rate: int
    crop_rate: int
    warehouse_cap: int
    granary_cap: int
    free_crop: int

class ResourceField(TypedDict):
    slot: int
    level: int

class BuildQueueItem(TypedDict):
    name: str
    level: int
    finish_at: str
    seconds_left: int

class TroopQueueItem(TypedDict):
    troop: str
    count: int
    finish_at: str
    seconds_left: int

class BuildingSlot(TypedDict):
    level: int
    slot: int

class EmptySlot(TypedDict):
    slot: int
    gid: int
    name: str

class HeroState(TypedDict, total=False):
    hero_health: int | None
    hero_xp: int
    hero_level: int
    hero_available_points: int
    hero_status: str
    hero_items: list
    hero_adventures: list
    hero_resource_rewards: dict[str, int]

class QuestState(TypedDict, total=False):
    daily_quests: list
    main_quests: list
    total_reward_ready: int

class DiplomaticIntel(TypedDict, total=False):
    raid_targets: list
    threats: list
    neutrals: list
    scout_priority: list
    summary_text: str
    new_player_protection: bool
    protection_hours_remaining: float

class GameState(TypedDict, total=False):
    timestamp: str
    village_name: str
    resources: Resources
    buildings: dict[str, int]
    buildings_with_slots: dict[str, BuildingSlot]
    resource_fields: dict[str, list[ResourceField]]
    empty_building_slots: list[EmptySlot]
    coord_x: int
    coord_y: int
    build_queue: list[BuildQueueItem]
    build_queue_full: bool
    troop_queue: list[TroopQueueItem]
    troops: dict
    map: dict
    next_free_slot: str | None
    has_plus: bool
    hero: HeroState
    quests: QuestState
    diplomatic_intel: DiplomaticIntel
    protection_hours_remaining: float


def summarize_state(state: dict) -> str:
    if not state:
        return "尚無資料"
    res = state.get("resources", {})
    bld = state.get("buildings", {})
    fields = state.get("resource_fields", {})
    total_fields = sum(len(v) for v in fields.values())
    empty = len(state.get("empty_building_slots", []))
    return (
        f"資源: wood={res.get('wood',0)}, clay={res.get('clay',0)}, "
        f"iron={res.get('iron',0)}, crop={res.get('crop',0)} | "
        f"建築: {len(bld)} 棟 | "
        f"空建築格: {empty} 個 | "
        f"資源田: {total_fields} 塊 | "
        f"建造隊列: {len(state.get('build_queue', []))} 項"
    )


def _find_village_name(html: str) -> str:
    try:
        import bs4
        el = bs4.BeautifulSoup(html, "lxml").select_one("span.name")
        if el:
            return el.get_text(strip=True)
    except Exception:
        pass
    return "Unknown"


def build_game_state(html_dorf1: str, html_dorf2: str = "") -> dict:
    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "village_name": "Unknown",
        "resources": {},
        "buildings": {},
        "buildings_with_slots": {},
        "resource_fields": {},
        "empty_building_slots": [],
        "coord_x": 0,
        "coord_y": 0,
        "build_queue": [],
        "build_queue_full": False,
        "troop_queue": [],
        "troops": {},
        "map": {},
        "next_free_slot": None,
    }

    try:
        combined = html_dorf1 + html_dorf2

        resources = parse_resources(html_dorf1)
        # 任務一/步驟二：數值保護
        for k in ['wood', 'clay', 'iron', 'crop', 'wood_rate', 'clay_rate', 'iron_rate', 'crop_rate']:
            resources[k] = resources.get(k) or 0
        resources['warehouse_cap'] = resources.get('warehouse_cap') or 800
        resources['granary_cap'] = resources.get('granary_cap') or 800

        build_queue = parse_build_queue(html_dorf1)
        troop_queue = parse_troop_queue(html_dorf1)
        troops = parse_troops(html_dorf1)
        map_data = parse_map(html_dorf1)

        # Resource fields from dorf1, buildings from dorf2
        fields_data = parse_buildings(html_dorf1)
        buildings_data = parse_buildings(html_dorf2) if html_dorf2 else fields_data

        state["resources"] = resources
        state["buildings"] = buildings_data.get("buildings", {})
        state["buildings_with_slots"] = buildings_data.get("buildings_with_slots", {})
        state["resource_fields"] = fields_data.get("resource_fields", {})
        state["empty_building_slots"] = buildings_data.get("empty_slots", [])
        state["build_queue"] = build_queue
        has_plus = state.get("has_plus", False)
        state["build_queue_full"] = len(build_queue) >= (2 if has_plus else 1)
        state["troop_queue"] = troop_queue
        state["troops"] = troops
        state["map"] = map_data

        next_slot = calculate_next_free_slot(build_queue, troop_queue)
        if next_slot:
            state["next_free_slot"] = next_slot

        state["village_name"] = _find_village_name(combined)

        state["hero"] = parse_hero_state(combined)

        state["quests"] = {"daily_quests": [], "main_quests": [], "total_reward_ready": 0}

        coord_patterns = [
            r'(?:globalVillage|villageData|activeVillage|mapPosition|villageCenter)[^{]{0,20}\{[^}]*"x"\s*:\s*(-?\d+)[^}]*"y"\s*:\s*(-?\d+)',
            r"(?:globalVillage|mapPosition)[^{]{0,20}\{[^}]*'x'\s*:\s*(-?\d+)[^}]*'y'\s*:\s*(-?\d+)",
            r'(?:center|position|coords?)\s*[=:]\s*\[(-?\d+)\s*,\s*(-?\d+)\]',
            r'\{x\s*:\s*(-?\d+)\s*,\s*y\s*:\s*(-?\d+)\}',
            r'data-x=["\'](-?\d+)["\'][^>]*data-y=["\'](-?\d+)["\']',
            r'karte\.php\?x=(-?\d+)&(?:amp;)?y=(-?\d+)',
        ]

        coord_found = False
        for pattern in coord_patterns:
            m = re.search(pattern, html_dorf1)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                if -400 <= x <= 400 and -400 <= y <= 400:
                    state["coord_x"] = x
                    state["coord_y"] = y
                    logger.debug(f"從 pattern 解析到座標: ({x}|{y})")
                    coord_found = True
                    break

        if not coord_found and html_dorf2:
            for pattern in coord_patterns:
                m = re.search(pattern, html_dorf2)
                if m:
                    x, y = int(m.group(1)), int(m.group(2))
                    if -400 <= x <= 400 and -400 <= y <= 400:
                        state["coord_x"] = x
                        state["coord_y"] = y
                        logger.debug(f"從 dorf2 解析到座標: ({x}|{y})")
                        coord_found = True
                        break

        if not coord_found:
            panel_match = re.search(
                r'(?:village|村莊)[^(]{0,100}\((-?\d+)\s*\|\s*(-?\d+)\)',
                html_dorf1 + html_dorf2, re.I
            )
            if panel_match:
                x, y = int(panel_match.group(1)), int(panel_match.group(2))
                if -400 <= x <= 400 and -400 <= y <= 400:
                    state["coord_x"] = x
                    state["coord_y"] = y
                    logger.debug(f"從村莊面板解析到座標: ({x}|{y})")
                    coord_found = True

        if not coord_found:
            logger.debug("⚠️ 無法從 HTML 解析村莊座標，將嘗試 JS 方法")

        logger.debug(f"遊戲狀態建置完成: {state['village_name']}")
    except Exception as e:
        logger.error(f"建置遊戲狀態失敗: {e}")

    return state


async def get_game_state(browser, page=None) -> Optional[dict]:
    from config import config

    own_page = False
    try:
        if page is None:
            from scraper.page_reader import page_reader
            page = await page_reader.get_page(config.travian_url)
            own_page = True
            if page is None:
                logger.error("無法獲取頁面來讀取遊戲狀態")
                return None

        html = await page.content()
        if not html:
            logger.error("獲取頁面 HTML 為空")
            return None

        state = build_game_state(html)
        return state
    except Exception as e:
        logger.error(f"獲取遊戲狀態失敗: {e}")
        return None
    finally:
        if own_page and page:
            try:
                from scraper.browser import browser_manager
                await browser_manager.close_page(page)
            except Exception:
                pass