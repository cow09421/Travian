import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager
from config import config
from executor.navigation import navigate_to_build, navigate_to_resource
from shared.building_data import get_gid


async def _find_and_click_upgrade_button(page: Page) -> tuple[bool, str]:
    selectors = [
        "button.green.build",
        "a.green.build",
        "button.green:has-text('升級')",
        "button.green:has-text('Upgrade')",
        "a.green:has-text('升級')",
        ".contractLink a.green",
        ".contractLink button.green",
        "#build .green",
        ".build_options .green",
        "button.green:visible",
        "a.green:visible",
        "button[type='button'].green",
        ".build_button button",
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            count = await btn.count()
            if count > 0 and await btn.is_visible() and await btn.is_enabled():
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=8000)
                logger.debug(f"點擊成功: {sel}")
                return True, ""
        except Exception as e:
            logger.debug(f"選擇器 {sel} 失敗: {e}")
            continue

    html = await page.content()
    soup = BeautifulSoup(html, "lxml")

    queue_indicators = [
        "underConstruction", "under-construction", "buildingInProgress",
        "notPossible", "建造中", "升級中"
    ]
    for indicator in queue_indicators:
        if indicator in html:
            return False, f"隊列已滿或已在升級中（{indicator}）"

    if any(kw in html for kw in ["notEnough", "not enough", "insufficient", "資源不足"]):
        return False, "資源不足"

    all_btns = [
        f"{b.name}[{' '.join(b.get('class', []))}]: {b.get_text(strip=True)[:40]}"
        for b in soup.find_all(["button", "a"], class_=True)[:15]
    ]
    return False, f"找不到升級按鈕，頁面元素: {all_btns}"


async def upgrade_building(page: Page, building_name: str, current_level: int = None) -> dict:
    result = {"success": False, "action_taken": "", "error_msg": "", "next_available": None}
    try:
        building_key = building_name.strip().lower()

        dorf2_url = f"{config.travian_url}/dorf2.php"
        ok = await browser_manager.safe_goto(page, dorf2_url)
        if not ok:
            result["error_msg"] = "無法導航到 dorf2"
            return result

        await page.wait_for_load_state("networkidle", timeout=10000)
        html = await page.content()

        soup = BeautifulSoup(html, "lxml")
        build_url = None

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            link_text = a.get_text(strip=True).lower()
            link_title = a.get("title", "").lower()
            if "build.php?id=" in href and (
                building_key in link_text or
                building_key in link_title
            ):
                build_url = f"{config.travian_url}/{href}" if not href.startswith("http") else href
                break

        if not build_url:
            for div in soup.select("div[class*='buildingSlot']"):
                txt = div.get_text(strip=True).lower()
                if building_key in txt:
                    a = div.find("a", href=lambda h: h and "build.php?id=" in h)
                    if a:
                        href = a["href"]
                        build_url = f"{config.travian_url}/{href}" if not href.startswith("http") else href
                        break

        if not build_url:
            building_id = _find_building_id(building_key, building_name)
            if building_id:
                build_url = f"{config.travian_url}/build.php?id={building_id}"

        if not build_url:
            result["error_msg"] = f"找不到建築 {building_name} 的位置"
            return result

        logger.info(f"🔗 導航到建築頁面: {build_url}")
        ok = await browser_manager.safe_goto(page, build_url)
        if not ok:
            result["error_msg"] = f"無法導航到 {build_url}"
            return result

        await page.wait_for_load_state("networkidle", timeout=10000)
        await browser_manager.human_delay()

        clicked, error = await _find_and_click_upgrade_button(page)

        if clicked:
            level_str = f" Lv{current_level}→{current_level + 1}" if current_level else ""
            result["success"] = True
            result["action_taken"] = f"升級建築 {building_name}{level_str}"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["error_msg"] = error

        await browser_manager.take_screenshot(page, f"build_{building_name}")

    except Exception as e:
        result["error_msg"] = f"升級建築時出錯: {e}"
        logger.error(result["error_msg"], exc_info=True)

    return result


async def upgrade_resource_field(page: Page, field_type: str, slot_id: int, current_level: int = None) -> dict:
    result = {"success": False, "action_taken": "", "error_msg": "", "screenshot_path": None}

    if not slot_id or slot_id <= 0:
        result["error_msg"] = f"slot_id={slot_id} 無效，必須是正整數"
        logger.error(result["error_msg"])
        return result

    try:
        build_url = f"{config.travian_url}/build.php?id={slot_id}"
        logger.info(f"🔗 導航到資源田: {build_url} ({field_type}, 當前Lv{current_level})")

        ok = await browser_manager.safe_goto(page, build_url)
        if not ok:
            result["error_msg"] = f"無法導航到 {build_url}"
            return result

        await page.wait_for_load_state("networkidle", timeout=10000)
        await browser_manager.human_delay()

        if "build.php" not in page.url:
            result["error_msg"] = "頁面導航失敗"
            return result

        clicked, error = await _find_and_click_upgrade_button(page)

        if clicked:
            level_str = f" Lv{current_level}→{(current_level or 0) + 1}"
            result["success"] = True
            result["action_taken"] = f"升級 {field_type} slot#{slot_id}{level_str}"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["error_msg"] = error
            logger.warning(f"❌ slot#{slot_id}: {error}")

        result["screenshot_path"] = await browser_manager.take_screenshot(page, f"resource_{field_type}_{slot_id}")

    except Exception as e:
        result["error_msg"] = f"升級資源田時出錯: {e}"
        logger.error(result["error_msg"], exc_info=True)

    return result


def _find_building_id(building_key: str, original_name: str) -> Optional[int]:
    gid = get_gid(original_name)
    if gid:
        return gid
    gid = get_gid(building_key)
    if gid:
        return gid
    return None


def _get_field_id(slot_id: int) -> int:
    return slot_id if slot_id > 0 else None


def _check_resources(html: str) -> Optional[str]:
    patterns = [
        (r'(?:not enough|missing|requires?)[^<]*?(\d+)\s*(?:wood|lumber)', "wood"),
        (r'(?:not enough|missing|requires?)[^<]*?(\d+)\s*(?:clay)', "clay"),
        (r'(?:not enough|missing|requires?)[^<]*?(\d+)\s*(?:iron)', "iron"),
        (r'(?:not enough|missing|requires?)[^<]*?(\d+)\s*(?:crop)', "crop"),
    ]
    needed = []
    for pat, res in patterns:
        m = re.search(pat, html, re.I)
        if m:
            needed.append(f"{res}:{m.group(1)}")
    return ", ".join(needed) if needed else None


def _check_max_level(html: str) -> Optional[int]:
    m = re.search(r'(?:already at|current|max)[^<]*?level\s*(\d+)', html, re.I)
    if m:
        return int(m.group(1))
    return None