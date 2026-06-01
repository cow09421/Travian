import re
from typing import Dict, List
from bs4 import BeautifulSoup
from loguru import logger

from shared.troop_data import normalize_troop_name


def parse_troops(html: str) -> dict:
    result = {
        "home": {},
        "away": []
    }
    try:
        soup = BeautifulSoup(html, "lxml")

        troop_images = soup.select("img[src*='unit'], img[class*='unit'], td[class*='unit'] img")
        if troop_images:
            for img in troop_images:
                parent = img.find_parent("td") or img.find_parent("div")
                if parent:
                    parent_text = parent.get_text(strip=True)
                else:
                    continue
                name = _extract_troop_name_from_img(img.get("src", ""), img.get("alt", ""))
                count = _extract_number(parent_text)
                if name and count > 0:
                    result["home"][name] = result["home"].get(name, 0) + count

        if not result["home"]:
            tables = soup.select("table")
            for table in tables:
                rows = table.select("tr")
                for row in rows:
                    cells = row.select("td")
                    if len(cells) >= 2:
                        first_text = cells[0].get_text(strip=True)
                        second_text = cells[1].get_text(strip=True)
                        name = _extract_troop_name_generic(first_text)
                        count = _extract_number(second_text)
                        if name and count > 0:
                            result["home"][name] = result["home"].get(name, 0) + count

        # Regex pass only runs if DOM parsing found nothing (avoids double-count)
        if not result["home"]:
            troop_patterns = [
                (r'(Phalanx|Spearman)[:\s]*(\d+)',),
                (r'(Swordsman|Axeman)[:\s]*(\d+)',),
                (r'(Legionnaire)[:\s]*(\d+)',),
                (r'(Praetorian)[:\s]*(\d+)',),
                (r'(Imperian)[:\s]*(\d+)',),
                (r'(Clubswinger)[:\s]*(\d+)',),
                (r'(Theutates\s*Thunder)[:\s]*(\d+)',),
                (r'(Druidrider)[:\s]*(\d+)',),
                (r'(Haeduan)[:\s]*(\d+)',),
                (r'(Equites\s*(?:Legati|Imperatoris|Caesaris))[:\s]*(\d+)',),
                (r'(Ram)[:\s]*(\d+)',),
                (r'(Catapult)[:\s]*(\d+)',),
                (r'(Pathfinder|Scout)[:\s]*(\d+)',),
                (r'(Paladin)[:\s]*(\d+)',),
                (r'(Knight)[:\s]*(\d+)',),
            ]
            for pat_tuple in troop_patterns:
                pat = pat_tuple[0]
                for m in re.finditer(pat, html, re.I):
                    name = _normalize_troop_name(m.group(1))
                    count = int(m.group(2))
                    if name and count > 0:
                        result["home"][name] = result["home"].get(name, 0) + count

        away_sections = soup.select("div.troopsAway, #troopsAway, .away")
        if away_sections:
            for section in away_sections:
                text = section.get_text(" ", strip=True)
                if text:
                    result["away"].append(text)

    except Exception as e:
        logger.error(f"解析兵力資訊失敗: {e}")

    return result


def _extract_troop_name_from_img(src: str, alt: str) -> str:
    if alt:
        return normalize_troop_name(alt)
    from shared.troop_data import _LOOKUP
    src_lower = src.lower()
    for alias, info in _LOOKUP.items():
        if alias in src_lower:
            return info.canonical_name
    return ""


def _extract_troop_name_generic(text: str) -> str:
    return normalize_troop_name(text.strip()[:30])


def _normalize_troop_name(name: str) -> str:
    return normalize_troop_name(name)


def _extract_number(text: str) -> int:
    cleaned = re.sub(r'[^\d]', '', text)
    try:
        return int(cleaned)
    except ValueError:
        return 0