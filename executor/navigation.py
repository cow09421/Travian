from typing import Optional

from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager
from config import config
from shared.building_data import get_gid, NAME_TO_GID as BUILDING_NAME_TO_GID

URL_SECTIONS = {
    "resources": "dorf1.php",
    "buildings": "dorf2.php",
    "map": "karte.php",
    "statistics": "statistics",
    "reports": "report/overview",
    "messages": "nachrichten.php",
}

async def dismiss_popups(page: Page):
    """關閉已知的遊戲彈窗"""
    popup_selectors = [
        "button.dialogButtonOk",
        "button[class*='dialogButton']",
        ".dialog .button.ok",
        ".closeWindow",
        "#closeWindowButton",
        ".infobox .close",
        "div.dialogContent + div button",
        ".dialog button.button",
    ]
    for selector in popup_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(500)
                logger.info(f"已關閉彈窗: {selector}")
        except Exception:
            pass

    try:
        btn = page.get_by_role("button", name="確定")
        if await btn.is_visible():
            await btn.click()
            await page.wait_for_timeout(500)
            logger.info("已關閉彈窗: 確定")
    except Exception:
        pass


from parser.state_builder import GameState as _GameState

def _resolve_slot_for_section(section: str, state: Optional[_GameState]) -> Optional[int]:
    """Look up a building name in state.buildings_with_slots to find its slot."""
    if not state:
        return None
    building_gid_map = {"rally_point": "Rally Point", "barracks": "Barracks",
                        "stable": "Stable", "workshop": "Workshop",
                        "academy": "Academy", "smithy": "Smithy",
                        "market": "Marketplace", "main_building": "Main Building",
                        "warehouse": "Warehouse", "granary": "Granary"}
    name = building_gid_map.get(section)
    if not name:
        return None
    bws = state.get("buildings_with_slots", {})
    info = bws.get(name)
    if info:
        return info.get("slot")
    return None


async def navigate_to(page: Page, section: str, sub_id: str = None,
                      state: Optional[dict] = None) -> bool:
    if section in URL_SECTIONS:
        url = f"{config.travian_url}/{URL_SECTIONS[section]}"
    elif section == "build":
        if sub_id:
            url = f"{config.travian_url}/build.php?id={sub_id}"
        else:
            url = f"{config.travian_url}/dorf2.php"
    elif section == "resource":
        if sub_id:
            url = f"{config.travian_url}/dorf1.php?id={sub_id}"
        else:
            url = f"{config.travian_url}/dorf1.php"
    else:
        building_slot = _resolve_slot_for_section(section, state)
        if building_slot is not None:
            url = f"{config.travian_url}/build.php?id={building_slot}"
        else:
            gid = BUILDING_NAME_TO_GID.get(section.title())
            if gid:
                url = f"{config.travian_url}/build.php?id={gid}"
            else:
                url = f"{config.travian_url}/{section}"

    ok = await browser_manager.safe_goto(page, url)
    await dismiss_popups(page)
    return ok


async def navigate_to_build(page: Page, building_id: int) -> bool:
    return await navigate_to(page, "build", str(building_id))


async def navigate_to_resource(page: Page, field_id: int) -> bool:
    return await navigate_to(page, "resource", str(field_id))