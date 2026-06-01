import re
from bs4 import BeautifulSoup
from loguru import logger

from shared.building_data import GID_TO_NAME as AID_TO_NAME


def parse_buildings(html: str) -> dict:
    result = {
        "buildings": {},
        "empty_slots": [],
        "resource_fields": {
            "wood_cutters": [],
            "clay_pits": [],
            "iron_mines": [],
            "croplands": []
        }
    }
    try:
        soup = BeautifulSoup(html, "lxml")

        # --- Resource Fields ---
        for el in soup.select('a[class*="resourceField"]'):
            cls = " ".join(el.get("class", []))
            aid_match = re.search(r'gid(\d+)', cls)
            slot_match = re.search(r'buildingSlot(\d+)', cls)
            level_match = re.search(r'level(\d+)', cls)
            if not aid_match:
                continue
            gid = int(aid_match.group(1))
            slot = int(slot_match.group(1)) if slot_match else 0
            level = int(level_match.group(1)) if level_match else 0

            field_map = {1: "wood_cutters", 2: "clay_pits", 3: "iron_mines", 4: "croplands"}
            key = field_map.get(gid)
            if key:
                result["resource_fields"][key].append({"slot": slot, "level": level})

        for key in result["resource_fields"]:
            result["resource_fields"][key].sort(key=lambda x: x["slot"])

        # --- Buildings (dorf2) ---
        for el in soup.select('div[class*="buildingSlot"]'):
            cls = " ".join(el.get("class", []))
            # class format: buildingSlot a{slotId} g{gid} aid{slotId} roman
            aid_match = re.search(r'aid(\d+)', cls)
            gid_match = re.search(r'\bg(\d+)\b', cls)
            if not aid_match:
                continue
            aid = int(aid_match.group(1))
            gid = int(gid_match.group(1)) if gid_match else 0
            # Level 取自子元素 .level 的文字內容
            level = 0
            level_el = el.select_one('.level')
            if level_el:
                try:
                    level = int(level_el.get_text(strip=True))
                except (ValueError, TypeError):
                    pass
            if gid == 0 or level == 0:
                name = AID_TO_NAME.get(gid) or f"building_{gid}"
                result["empty_slots"].append({"slot": aid, "gid": gid, "name": name})
                continue
            name = AID_TO_NAME.get(gid)
            if name:
                result["buildings"][name] = level
                if "buildings_with_slots" not in result:
                    result["buildings_with_slots"] = {}
                result["buildings_with_slots"][name] = {"level": level, "slot": aid}

        # --- Fallback from HTML text ---
        if not result["buildings"]:
            result = _fallback_buildings(html, result)

    except Exception as e:
        logger.error(f"解析建築資訊失敗: {e}")

    return result


def _fallback_buildings(html: str, result: dict) -> dict:
    try:
        building_patterns = [
            (r'Main\s+Building[^a-z]*?(\d+)', "Main Building"),
            (r'Rally\s+Point[^a-z]*?(\d+)', "Rally Point"),
            (r'Barracks[^a-z]*?(\d+)', "Barracks"),
            (r'Stable[^a-z]*?(\d+)', "Stable"),
            (r'Workshop[^a-z]*?(\d+)', "Workshop"),
            (r'Smithy[^a-z]*?(\d+)', "Smithy"),
            (r'Marketplace[^a-z]*?(\d+)', "Marketplace"),
            (r'Granary[^a-z]*?(\d+)', "Granary"),
            (r'Warehouse[^a-z]*?(\d+)', "Warehouse"),
            (r'Academy[^a-z]*?(\d+)', "Academy"),
            (r'Cranny[^a-z]*?(\d+)', "Cranny"),
            (r'Wall[^a-z]*?(\d+)', "Wall"),
            (r'[Hh]ero[^a-z]*?(\d+)', "Heros Mansion"),
            (r'Embassy[^a-z]*?(\d+)', "Embassy"),
            (r'Residence[^a-z]*?(\d+)', "Residence"),
            (r'Palace[^a-z]*?(\d+)', "Palace"),
            (r'Treasury[^a-z]*?(\d+)', "Treasury"),
            (r'Trade\s+Office[^a-z]*?(\d+)', "Trade Office"),
            (r'Town\s+Hall[^a-z]*?(\d+)', "Town Hall"),
            (r'Hospital[^a-z]*?(\d+)', "Hospital"),
        ]
        for pat, name in building_patterns:
            m = re.search(pat, html, re.I)
            if m:
                val = int(m.group(1))
                if val < 100:  # sanity check — buildings never exceed level 25
                    result["buildings"][name] = val
    except Exception as e:
        logger.error(f"備用建築解析失敗: {e}")
    return result