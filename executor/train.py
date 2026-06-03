from datetime import datetime
from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager
from config import config
from executor.navigation import navigate_to_build
from shared.troop_data import (
    get_building_gid_for_troop as _get_gid_for_troop,
    get_troop_index as _get_troop_index,
    get_building_name_for_troop,
    BARRACKS_TROOPS, STABLE_TROOPS, WORKSHOP_TROOPS,
)


async def train_troops(page: Page, troop_type: str, count: int, state: dict = None) -> dict:
    result = {"success": False, "action_taken": "", "error_msg": ""}
    try:
        target_gid = _get_gid_for_troop(troop_type)
        if not target_gid:
            result["error_msg"] = f"找不到適合訓練 {troop_type} 的建築類型"
            return result

        building_name = {19: "Barracks", 20: "Stable", 21: "Workshop"}.get(target_gid, "?")

        slot_id = _find_building_slot(state, target_gid, building_name)

        if not slot_id:
            slot_id = await _find_building_slot_from_page(page, target_gid)

        if not slot_id:
            result["error_msg"] = f"{building_name} 尚未建造或找不到槽位"
            return result

        build_url = f"{config.travian_url}/build.php?id={slot_id}"
        logger.info(f"🏗️ 導航到 {building_name} (槽位 {slot_id}): {build_url}")
        ok = await browser_manager.safe_goto(page, build_url)
        if not ok:
            result["error_msg"] = f"無法導航到 {building_name}"
            return result

        await browser_manager.human_delay()

        troop_idx = _get_troop_index(troop_type)
        troop_input = await _find_troop_input(page, troop_idx, troop_type)

        if not troop_input:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            await page.screenshot(path=str(config.screenshots_dir / f"train_debug_{troop_type}_{ts}.png"))
            all_inputs = await page.evaluate("""
                () => Array.from(document.querySelectorAll('input')).map(i => ({
                    name: i.name, id: i.id, type: i.type,
                    classes: i.className, placeholder: i.placeholder
                }))
            """)
            logger.error(f"找不到訓練輸入框，頁面 input 列表: {all_inputs[:10]}")
            result["error_msg"] = f"找不到 {troop_type} 的輸入框（見截圖和日誌）"
            return result

        await troop_input.fill(str(count))
        await browser_manager.human_delay()

        train_btn = None
        for btn_sel in [
            "button:has-text('訓練')", "button:has-text('Train')",
            "button:has-text('train')", "input[type='submit']",
            "button[type='submit']", "button.green",
            ".barracksButton button", ".trainButton"
        ]:
            try:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    train_btn = btn
                    break
            except Exception:
                continue

        if train_btn:
            await train_btn.click()
            await browser_manager.human_delay()
            result["success"] = True
            result["action_taken"] = f"訓練 {count} 個 {troop_type}"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["error_msg"] = "找不到訓練按鈕"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.screenshots_dir / f"train_{troop_type}_{ts}.png"
        try:
            await page.screenshot(path=str(path))
        except Exception:
            pass

    except Exception as e:
        result["error_msg"] = f"訓練士兵時出錯: {e}"
        logger.error(result["error_msg"])

    return result


async def _find_troop_input(page, troop_idx: int, troop_type: str):
    selectors = [
        f"input[name='t{troop_idx}']",
        f"input[name='troops[{troop_idx}]']",
        f"input[id='t{troop_idx}']",
        f"input.trpInput:nth-of-type({troop_idx})",
        f"input[data-unit='{troop_idx}']",
        f".unitInput:nth-child({troop_idx}) input",
        f".troop_{troop_idx} input",
        f".unitRow:nth-child({troop_idx}) input[type='number']",
        f".unitRow:nth-child({troop_idx}) input[type='text']",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                logger.debug(f"找到訓練輸入框: {sel}")
                return el
        except Exception:
            continue
    return None


async def _find_building_slot_from_page(page, target_gid: int) -> int:
    import re
    from bs4 import BeautifulSoup

    try:
        dorf2_url = f"{config.travian_url}/dorf2.php"
        ok = await browser_manager.safe_goto(page, dorf2_url)
        if not ok:
            return None
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        for el in soup.select('div[class*="buildingSlot"]'):
            cls = " ".join(el.get("class", []))
            # class format: buildingSlot a{slot} g{gid} aid{slot} roman
            gid_match = re.search(r'\bg(\d+)\b', cls)
            aid_match = re.search(r'aid(\d+)', cls)
            level = 0
            level_el = el.select_one('.level')
            if level_el:
                try:
                    level = int(level_el.get_text(strip=True))
                except (ValueError, TypeError):
                    pass

            if gid_match and aid_match:
                gid = int(gid_match.group(1))
                aid = int(aid_match.group(1))
                if gid == target_gid and level > 0:
                    logger.info(f"找到 GID={target_gid} 在槽位 {aid}")
                    return aid

        gid_name_map = {19: "barracks", 20: "stable", 21: "workshop"}
        target_name = gid_name_map.get(target_gid, "")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = (a.get_text(strip=True) + " " + a.get("title", "")).lower()
            slot_m = re.search(r'build\.php\?id=(\d+)', href)
            if slot_m and target_name and target_name in text:
                return int(slot_m.group(1))

    except Exception as e:
        logger.error(f"掃描 dorf2 找槽位失敗: {e}")

    return None


from parser.state_builder import GameState as _GameState

def _find_building_slot(state: _GameState, target_gid: int, building_name: str) -> int:
    if not state:
        return None
    bws = state.get("buildings_with_slots", {})
    if building_name in bws:
        return bws[building_name].get("slot")
    return None


