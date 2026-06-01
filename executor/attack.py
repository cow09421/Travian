from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager
from executor.navigation import navigate_to_build
from config import config
from datetime import datetime
from shared.troop_data import get_troop_index as _get_troop_index_by_name


async def send_attack(page: Page, target_x: int, target_y: int,
                      mission_type: str, troops: dict) -> dict:
    result = {
        "success": False,
        "action_taken": "",
        "error_msg": "",
        "next_available": None
    }
    try:
        ok = await navigate_to_build(page, 39)  # Rally Point
        if not ok:
            result["error_msg"] = "無法導航到集結點"
            return result

        await browser_manager.human_delay()

        raid_link = page.locator(f"a[href*='a=2'], a:has-text('Raid'), a:has-text('raid'), "
                                  f"a:has-text('劫掠')")
        attack_link = page.locator(f"a[href*='a=1'], a:has-text('Attack'), a:has-text('attack'), "
                                    f"a:has-text('攻擊')")

        if mission_type == "raid" and await raid_link.count() > 0:
            await raid_link.first.click()
        elif await attack_link.count() > 0:
            await attack_link.first.click()
        else:
            target_url = f"{config.travian_url}/build.php?id=39&a={1 if mission_type == 'attack' else 2}"
            await browser_manager.safe_goto(page, target_url)

        await browser_manager.human_delay()

        x_input = page.locator("input[name='x'], input[name*='targe']")
        y_input = page.locator("input[name='y'], input[name*='targe']")
        if await x_input.count() == 0:
            coord_input = page.locator("input[name*='coord'], input[name*='c']")
            if await coord_input.count() > 0:
                await coord_input.first.fill(f"({target_x}|{target_y})")
            else:
                result["error_msg"] = "找不到座標輸入框"
                return result
        else:
            await x_input.first.fill(str(target_x))
            await y_input.first.fill(str(target_y))

        await browser_manager.human_delay()

        troop_inputs = page.locator("input[type='text'].troop_input, input[name='t1'], input[name='t2'], input[name='t3'], input[name='t4'], input[name='t5'], input[name='t6']")
        if await troop_inputs.count() > 0:
            for troop_name, troop_count in troops.items():
                idx = _get_troop_index_by_name(troop_name)
                ti = page.locator(f"input[name='t{idx}']")
                if await ti.count() == 0:
                    ti = troop_inputs.nth(idx - 1) if idx <= await troop_inputs.count() else None
                if ti and await ti.count() > 0:
                    await ti.first.fill(str(troop_count))
                    await browser_manager.human_delay(0.3, 0.8)

        ok_btn = page.locator("button:has-text('Ok'), button:has-text('OK'), button:has-text('Send'), "
                               "button[type='submit'], input[value='ok'], input[value='send']")
        if await ok_btn.count() > 0:
            await ok_btn.first.click()
            await browser_manager.human_delay()
            confirm_btn = page.locator("button:has-text('Ok'), button:has-text('confirm'), "
                                        "a:has-text('Yes'), button[type='submit']")
            if await confirm_btn.count() > 0:
                await confirm_btn.first.click()
                await browser_manager.human_delay()
            result["success"] = True
            result["action_taken"] = f"{mission_type} ({target_x}|{target_y}) 派出 {troops}"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["error_msg"] = "找不到確認按鈕"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.screenshots_dir / f"attack_{target_x}_{target_y}_{ts}.png"
        try:
            await page.screenshot(path=str(path))
        except Exception:
            pass

    except Exception as e:
        result["error_msg"] = f"發送攻擊時出錯: {e}"
        logger.error(result["error_msg"])

    return result


async def send_scout(page: Page, target_x: int, target_y: int) -> dict:
    result = {
        "success": False,
        "action_taken": "",
        "error_msg": "",
        "next_available": None
    }
    try:
        ok = await navigate_to_build(page, 39)  # Rally Point
        if not ok:
            result["error_msg"] = "無法導航到集結點"
            return result

        await browser_manager.human_delay()

        scout_url = f"{config.travian_url}/build.php?id=39&a=3"
        await browser_manager.safe_goto(page, scout_url)
        await browser_manager.human_delay()

        coord_input = page.locator("input[name*='coord'], input[name*='c'], input[name='x'], input[name='y']")
        if await coord_input.count() > 0:
            await coord_input.first.fill(f"({target_x}|{target_y})")
        else:
            result["error_msg"] = "找不到座標輸入框"
            return result

        await browser_manager.human_delay()

        scout_check = page.locator("input[type='checkbox'], input[name*='t1']")
        if await scout_check.count() > 0:
            await scout_check.first.check()
            await browser_manager.human_delay()

        ok_btn = page.locator("button:has-text('Ok'), button:has-text('Send'), "
                               "button[type='submit'], input[value='ok']")
        if await ok_btn.count() > 0:
            await ok_btn.first.click()
            await browser_manager.human_delay()
            result["success"] = True
            result["action_taken"] = f"偵察 ({target_x}|{target_y})"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["error_msg"] = "找不到確認按鈕"

    except Exception as e:
        result["error_msg"] = f"偵察時出錯: {e}"
        logger.error(result["error_msg"])

    return result