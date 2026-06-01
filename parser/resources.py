import re
from bs4 import BeautifulSoup
from loguru import logger


def parse_resources(html: str) -> dict:
    result = {
        "wood": 0, "clay": 0, "iron": 0, "crop": 0,
        "wood_rate": 0, "clay_rate": 0, "iron_rate": 0, "crop_rate": 0,
        "warehouse_cap": 20000, "granary_cap": 8000,
        "free_crop": 0
    }
    try:
        soup = BeautifulSoup(html, "lxml")

        # Individual resource values: #l1=wood, #l2=clay, #l3=iron, #l4=crop
        id_map = {"l1": "wood", "l2": "clay", "l3": "iron", "l4": "crop"}
        for eid, key in id_map.items():
            el = soup.find(id=eid)
            if el:
                result[key] = _extract_int(el.get_text(strip=True))

        # Free crop
        fc = soup.find(id="stockBarFreeCrop")
        if fc:
            result["free_crop"] = _extract_int(fc.get_text(strip=True))

        # Stock bar container for capacity
        stock_bar = soup.find(id="stockBar")
        if stock_bar:
            warehouse = stock_bar.find(class_="warehouse")
            if warehouse:
                txt = warehouse.get_text(strip=True)
                cap_el = warehouse.find(class_="capacity")
                if cap_el:
                    result["warehouse_cap"] = _extract_int(cap_el.get_text(strip=True))
                elif "capacity" not in txt:
                    cap_match = re.search(r'(\d{3,6})\s*/\s*(\d{3,6})', txt)
                    if cap_match:
                        result["warehouse_cap"] = int(cap_match.group(2))

            granary = stock_bar.find(class_="granary")
            if granary:
                txt = granary.get_text(strip=True)
                cap_el = granary.find(class_="capacity")
                if cap_el:
                    result["granary_cap"] = _extract_int(cap_el.get_text(strip=True))
                elif "capacity" not in txt:
                    cap_match = re.search(r'(\d{3,6})\s*/\s*(\d{3,6})', txt)
                    if cap_match:
                        result["granary_cap"] = int(cap_match.group(2))

        # Rates from page text (per hour patterns)
        rate_patterns = [
            (r'wood[\s\S]*?(\d+)\s*per\s*hour', "wood_rate"),
            (r'clay[\s\S]*?(\d+)\s*per\s*hour', "clay_rate"),
            (r'iron[\s\S]*?(\d+)\s*per\s*hour', "iron_rate"),
            (r'crop[\s\S]*?(\d+)\s*per\s*hour', "crop_rate"),
        ]
        for pat, key in rate_patterns:
            m = re.search(pat, html, re.I)
            if m:
                result[key] = int(m.group(1))

        # Fallback: if l1-l4 didn't work, parse the stockBarButton elements
        if result["wood"] == 0 and result["clay"] == 0:
            stock_bar = soup.find(id="stockBar")
            if stock_bar:
                buttons = stock_bar.find_all(class_=lambda c: c and "stockBarButton" in c)
                for btn in buttons:
                    cls = " ".join(btn.get("class", []))
                    val = _extract_int(btn.get_text(strip=True))
                    if "resource1" in cls:
                        result["wood"] = val
                    elif "resource2" in cls:
                        result["clay"] = val
                    elif "resource3" in cls:
                        result["iron"] = val
                    elif "resource4" in cls:
                        result["crop"] = val
                    elif val and not result.get("free_crop"):
                        result["free_crop"] = val

    except Exception as e:
        logger.error(f"解析資源資訊失敗: {e}")

    return result


def _extract_int(text: str) -> int:
    cleaned = re.sub(r'[^\d]', '', text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0