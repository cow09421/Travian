import re
from bs4 import BeautifulSoup
from loguru import logger


def parse_hero_state(page) -> dict:
    try:
        url = page.url
        html = page.content()
    except Exception:
        html = page
        url = ""

    result = {
        "hero_health": None,
        "hero_xp": 0,
        "hero_level": 0,
        "hero_available_points": 0,
        "hero_status": "idle",
        "hero_items": [],
        "hero_adventures": [],
        "hero_resource_rewards": {},
    }

    try:
        if not html:
            return result

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()

        health_selectors = [
            "#heroHealthBar", ".heroHealthBar",
            "[data-health]", ".hero-health",
            ".health-bar", ".healthBar",
        ]
        for sel in health_selectors:
            el = soup.select_one(sel)
            if el:
                style = el.get("style", "")
                wm = re.search(r'width\s*:\s*(\d+)%', style)
                if wm:
                    result["hero_health"] = int(wm.group(1))
                    break
                tm = re.search(r'(\d+)', el.get_text(strip=True))
                if tm:
                    result["hero_health"] = int(tm.group(1))
                    break

        if result["hero_health"] is None:
            health_matches = re.findall(r'(?:hp|health|生命)[:\s]*(\d+)\s*[/]\s*(\d+)', text, re.I)
            for curr, maxv in health_matches:
                c, m = int(curr), int(maxv)
                if m > 0:
                    result["hero_health"] = int(c / m * 100)
                    break

        xp_m = re.search(r'(?:xp|經驗|experience)[:\s]*(\d+)\s*(?:/\s*\d+)?', text, re.I)
        if xp_m:
            result["hero_xp"] = int(xp_m.group(1))

        lv_m = re.search(r'(?:level|等級|lv)[.:\s]*(\d+)', text, re.I)
        if lv_m:
            result["hero_level"] = int(lv_m.group(1))

        pt_m = re.search(r'(?:points?|屬性點|attribute|stat)[^:]{0,10}[:\s]*(\d+)', text, re.I)
        if pt_m:
            result["hero_available_points"] = int(pt_m.group(1))

        if "dead" in text.lower() or "死亡" in text:
            result["hero_status"] = "dead"
        elif any(kw in text.lower() for kw in ["adventure", "冒險中", "away"]):
            result["hero_status"] = "adventure"
        else:
            result["hero_status"] = "idle"

        item_slots = ["helmet", "armor", "weapon", "shield", "boots", "horse"]
        for slot in item_slots:
            slot_el = soup.select_one(f"[data-slot='{slot}'], .{slot}, .itemSlot.{slot}")
            if slot_el:
                name = slot_el.get("title", "") or slot_el.get_text(strip=True)
                bonus = ""
                bonus_el = slot_el.select_one(".bonus, .effect, .itemBonus")
                if bonus_el:
                    bonus = bonus_el.get_text(strip=True)
                if name:
                    result["hero_items"].append({
                        "slot": slot, "name": name, "bonus": bonus
                    })

        adv_cards = soup.select(".adventureCard, .adventure, [class*='adventure']")
        for card in adv_cards:
            adv_id = None
            id_el = card.select_one("[data-id], .adventureId")
            if id_el:
                adv_id = int(id_el.get("data-id", 0) or id_el.get_text(strip=True))

            diff = "normal"
            diff_el = card.select_one(".difficulty, .adventureDiff")
            if diff_el:
                dt = diff_el.get_text(strip=True).lower()
                if "easy" in dt:
                    diff = "easy"
                elif "hard" in dt:
                    diff = "hard"

            duration = 45
            dur_m = re.search(r'(\d+)\s*(?:min|分鐘|小時)?', card.get_text())
            if dur_m:
                val = int(dur_m.group(1))
                if "hour" in card.get_text() or "小時" in card.get_text():
                    duration = val * 60
                else:
                    duration = val

            if adv_id:
                result["hero_adventures"].append({
                    "id": adv_id,
                    "difficulty": diff,
                    "duration_minutes": duration,
                })

        inv_text = soup.select_one(".heroInventory, .inventory, .hero-items, [class*='hero']")
        if inv_text:
            inv_html = str(inv_text)
        else:
            inv_html = text

        for res_name, kw in [("wood", "wood"), ("clay", "clay"), ("iron", "iron"), ("crop", "crop")]:
            m = re.search(rf'{kw}[:\s]*(\d+)', inv_html, re.I)
            if m:
                result["hero_resource_rewards"][res_name] = int(m.group(1))

        if result["hero_adventures"] and not any(result["hero_resource_rewards"].values()):
            pass

    except Exception as e:
        logger.warning(f"英雄頁面解析失敗: {e}")

    return result