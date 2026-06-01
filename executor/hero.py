from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager


async def collect_hero_resources(page: Page) -> dict:
    result = {"success": False, "transferred": {}, "screenshot_path": None}
    try:
        hero_url = f"{config.travian_url}/hero.php"
        ok = await browser_manager.safe_goto(page, hero_url)
        if not ok:
            result["error_msg"] = "無法導航到英雄頁面"
            return result

        await browser_manager.human_delay()

        transfer_selectors = [
            "button:has-text('轉移')",
            "button:has-text('Transfer')",
            "button:has-text('collect')",
            "button:has-text('Collect')",
            "a:has-text('轉移')",
            ".heroInventory button",
            ".hero-inventory button",
            ".heroAction button",
            "button.transfer",
            "a.transfer",
        ]

        clicked = False
        for sel in transfer_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    await page.wait_for_load_state("networkidle", timeout=8000)
                    clicked = True
                    logger.info(f"點擊轉移資源按鈕: {sel}")
                    break
            except Exception:
                continue

        if not clicked:
            html = await page.content()
            if any(kw in html.lower() for kw in ["沒有資源可轉移", "no resources", "沒有可轉移"]):
                result["success"] = True
                result["action_taken"] = "無待轉移英雄資源"
                logger.info("英雄沒有需要轉移的資源")
                return result

            result["error_msg"] = "找不到轉移資源按鈕"
            logger.warning(result["error_msg"])
            return result

        await browser_manager.human_delay()

        confirm_btn = page.locator(
            "button:has-text('確定'), button:has-text('Confirm'), "
            "button:has-text('Yes'), button:has-text('Ok')"
        )
        if await confirm_btn.count() > 0 and await confirm_btn.first.is_visible():
            await confirm_btn.first.click()
            await browser_manager.human_delay()

        result["success"] = True
        result["action_taken"] = "英雄資源已轉移到倉庫"
        logger.info(f"✅ {result['action_taken']}")
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_collect")

    except Exception as e:
        result["error_msg"] = f"英雄資源收集失敗: {e}"
        logger.error(result["error_msg"])
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_collect_error")

    return result


async def send_hero_adventure(page: Page, adventure_id: int) -> dict:
    result = {"success": False, "adventure_id": adventure_id, "screenshot_path": None}
    try:
        adv_url = f"{config.travian_url}/hero.php?t=3"
        ok = await browser_manager.safe_goto(page, adv_url)
        if not ok:
            result["error_msg"] = "無法導航到冒險頁面"
            return result

        await browser_manager.human_delay()

        send_selectors = [
            f"a[data-id='{adventure_id}']",
            f"button[data-id='{adventure_id}']",
            f".adventureCard[data-id='{adventure_id}'] button",
            f".adventure[data-id='{adventure_id}'] a",
            "button:has-text('Send')",
            "button:has-text('出發')",
            "a:has-text('Send')",
            "a:has-text('出發')",
        ]

        clicked = False
        for sel in send_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    await page.wait_for_load_state("networkidle", timeout=8000)
                    clicked = True
                    logger.info(f"點擊冒險出征按鈕: {sel}")
                    break
            except Exception:
                continue

        if not clicked:
            adventures = page.locator(".adventureCard, .adventure, [class*='adventure']")
            count = await adventures.count()
            for i in range(count):
                adv = adventures.nth(i)
                html = await adv.inner_html()
                if str(adventure_id) in html:
                    btn = adv.locator("button, a").first
                    if await btn.count() > 0:
                        await btn.click()
                        await page.wait_for_load_state("networkidle", timeout=8000)
                        clicked = True
                        break

        if not clicked:
            result["error_msg"] = f"找不到冒險 {adventure_id} 的出征按鈕"
            return result

        await browser_manager.human_delay()

        confirm_btn = page.locator(
            "button:has-text('確定'), button:has-text('Confirm'), "
            "button:has-text('Yes'), button:has-text('Ok')"
        )
        if await confirm_btn.count() > 0 and await confirm_btn.first.is_visible():
            await confirm_btn.first.click()
            await browser_manager.human_delay()

        result["success"] = True
        result["action_taken"] = f"英雄已出發冒險 (ID: {adventure_id})"
        logger.info(f"✅ {result['action_taken']}")
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_adventure")

    except Exception as e:
        result["error_msg"] = f"英雄冒險出征失敗: {e}"
        logger.error(result["error_msg"])
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_adventure_error")

    return result


async def allocate_hero_points(page: Page, attribute: str, points: int) -> dict:
    result = {"success": False, "screenshot_path": None}
    try:
        hero_url = f"{config.travian_url}/hero.php"
        ok = await browser_manager.safe_goto(page, hero_url)
        if not ok:
            result["error_msg"] = "無法導航到英雄頁面"
            return result

        await browser_manager.human_delay()

        attr_map = {
            "fighting_strength": ["offbonus", "off_bonus", "fighting", "attack"],
            "off_bonus": ["offbonus", "off_bonus", "fighting", "attack"],
            "def_bonus": ["defbonus", "def_bonus", "defense", "defence"],
            "resources": ["resbonus", "res_bonus", "resource", "production"],
        }

        attr_keywords = attr_map.get(attribute, [attribute])

        attr_btn = None
        for kw in attr_keywords:
            try:
                el = page.locator(f"input[name*='{kw}'], input[id*='{kw}'], "
                                  f"button:has-text('{kw}'), a:has-text('{kw}')").first
                if await el.count() > 0 and await el.is_visible():
                    attr_btn = el
                    break
            except Exception:
                continue

        if not attr_btn:
            buttons = page.locator("input[type='text'], input[type='number']")
            bc = await buttons.count()
            for i in range(bc):
                try:
                    b = buttons.nth(i)
                    name = await b.get_attribute("name") or ""
                    bid = await b.get_attribute("id") or ""
                    combined = name + bid
                    if any(kw in combined.lower() for kw in attr_keywords):
                        attr_btn = b
                        break
                except Exception:
                    continue

        if not attr_btn:
            result["error_msg"] = f"找不到屬性 {attribute} 的分配輸入框"
            return result

        await attr_btn.fill(str(points))
        await browser_manager.human_delay()

        save_selectors = [
            "button:has-text('Save')",
            "button:has-text('確認')",
            "button:has-text('分配')",
            "button.green",
            "input[type='submit']",
        ]

        clicked = False
        for sel in save_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    await page.wait_for_load_state("networkidle", timeout=8000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            result["error_msg"] = "找不到屬性分配確認按鈕"
            return result

        result["success"] = True
        result["action_taken"] = f"英雄屬性 {attribute} 已分配 {points} 點"
        logger.info(f"✅ {result['action_taken']}")
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_allocate")

    except Exception as e:
        result["error_msg"] = f"英雄屬性分配失敗: {e}"
        logger.error(result["error_msg"])
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "hero_allocate_error")

    return result