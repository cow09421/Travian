import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from loguru import logger

from shared.troop_data import _LOOKUP as _TROOP_ALIASES


def parse_build_queue(html: str) -> List[Dict]:
    queue = []
    try:
        soup = BeautifulSoup(html, "lxml")

        for el in soup.find_all(class_="timer"):
            p = el.find_parent("div") or el.find_parent("span") or el.find_parent("td")
            if not p:
                continue
            txt = p.get_text(" ", strip=True)
            timer_text = el.get_text(strip=True)
            seconds = _parse_timer(timer_text)
            if seconds is None or seconds == 0:
                continue
            name = _extract_queue_name(txt)
            if not name:
                continue
            level = _extract_level(txt)
            finish_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
            queue.append({
                "name": name,
                "level": level,
                "finish_at": finish_at,
                "seconds_left": seconds
            })

        # Also check content boxes
        for box in soup.select("#build .content, .buildDuration, .build_queue"):
            txt = box.get_text(" ", strip=True)
            timer_el = box.find(class_="timer")
            if timer_el:
                seconds = _parse_timer(timer_el.get_text(strip=True))
                if seconds and seconds > 0:
                    name = _extract_queue_name(txt)
                    level = _extract_level(txt)
                    finish_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
                    new_entry = {
                        "name": name or "Construction",
                        "level": level,
                        "finish_at": finish_at,
                        "seconds_left": seconds
                    }
                    # Deduplicate
                    if not any(e["finish_at"] == finish_at and e["name"] == new_entry["name"] for e in queue):
                        queue.append(new_entry)

    except Exception as e:
        logger.error(f"解析建造隊列失敗: {e}")

    return queue


def parse_troop_queue(html: str) -> List[Dict]:
    queue = []
    try:
        soup = BeautifulSoup(html, "lxml")

        for el in soup.find_all(class_="timer"):
            p = el.find_parent("div") or el.find_parent("span") or el.find_parent("td")
            if not p:
                continue
            txt = p.get_text(" ", strip=True)
            timer_text = el.get_text(strip=True)
            seconds = _parse_timer(timer_text)
            if seconds is None or seconds == 0:
                continue
            troop_name = _extract_troop_name(txt)
            if not troop_name:
                continue
            count = _extract_troop_count(txt)
            finish_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
            queue.append({
                "troop": troop_name,
                "count": count,
                "finish_at": finish_at,
                "seconds_left": seconds
            })

    except Exception as e:
        logger.error(f"解析訓練隊列失敗: {e}")

    return queue


def calculate_next_free_slot(build_queue: List[Dict], troop_queue: List[Dict]) -> Optional[str]:
    all_times = []
    for item in build_queue:
        if item.get("finish_at"):
            all_times.append(item["finish_at"])
    for item in troop_queue:
        if item.get("finish_at"):
            all_times.append(item["finish_at"])
    if not all_times:
        return None
    return sorted(all_times)[0]


def _parse_timer(timer_text: str) -> Optional[int]:
    if not timer_text:
        return None
    timer_text = timer_text.strip()
    # HH:MM:SS
    match = re.match(r'(\d+):(\d+):(\d+)$', timer_text)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
    # MM:SS
    match = re.match(r'(\d+):(\d+)$', timer_text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    # Just digits -> seconds
    if timer_text.isdigit():
        return int(timer_text)
    return None


def _extract_queue_name(text: str) -> Optional[str]:
    known = [
        "Main Building", "Rally Point", "Barracks", "Stable", "Workshop",
        "Academy", "Smithy", "Marketplace", "Embassy", "Palace",
        "Treasury", "Warehouse", "Granary", "Wall",
        "Great Barracks", "Great Stable", "Heros Mansion",
        "Cranny", "Town Hall", "Residence",
        "Woodcutter", "Clay Pit", "Iron Mine", "Cropland",
        "Sawmill", "Brickyard", "Iron Foundry", "Grain Mill", "Bakery",
        "Trade Office", "Hospital", "Watch Tower",
        "Great Warehouse", "Great Granary",
        "Tournament Square", "Waterworks", "Brewery",
        "Horse Drinking Trough", "Stone Wall", "Earth Wall",
        "Palisade", "Makeshift Wall", "Command Post",
        "Stonemason", "Bowyer", "Siege Workshop", "Chief's Quarters",
        "Great Wall", "Trapper", "Armoury",
    ]
    for name in known:
        if name.lower() in text.lower():
            return name
    return None


def _extract_level(text: str) -> int:
    patterns = [r'level\s*(\d+)', r'lv\.?\s*(\d+)', r'等級\s*(\d+)', r'(\d+)\s*級']
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return 0


def _extract_troop_name(text: str) -> Optional[str]:
    text_lower = text.lower()
    for alias, info in _TROOP_ALIASES.items():
        if alias in text_lower:
            return info.canonical_name
    return None


def _extract_troop_count(text: str) -> int:
    m = re.search(r'(\d+)\s*x', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*(?:troops?|units?)', text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)', text)
    if m:
        return int(m.group(1))
    return 0