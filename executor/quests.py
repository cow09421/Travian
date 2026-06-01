from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager


async def collect_quest_reward(page: Page, quest_id: str = None) -> dict:
    result = {"success": False, "collected_count": 0, "rewards": [], "screenshot_path": None}
    try:
        quest_url = f"{config.travian_url}/questmasterOverview.php"
        ok = await browser_manager.safe_goto(page, quest_url)
        if not ok:
            quest_url = f"{config.travian_url}/questmaster.php"
            ok = await browser_manager.safe_goto(page, quest_url)
        if not ok:
            result["error_msg"] = "無法導航到任務頁面"
            return result

        await browser_manager.human_delay()

        collect_selectors = [
            "button.collectReward",
            "button.questReward",
            "button:has-text('Collect')",
            "button:has-text('領取')",
            "button:has-text('收穫')",
            "a.collectReward",
            "a.questReward",
            "a:has-text('Collect')",
            "a:has-text('領取')",
            ".collectReward button",
            ".questReward button",
        ]

        collected = 0
        collected_rewards = []

        buttons = []
        seen_selectors = set()
        for sel in collect_selectors:
            try:
                els = page.locator(sel)
                count = await els.count()
                for i in range(count):
                    btn = els.nth(i)
                    if await btn.is_visible() and await btn.is_enabled():
                        key = f"{sel}_{i}"
                        if key not in seen_selectors:
                            seen_selectors.add(key)
                            buttons.append(btn)
            except Exception:
                continue

        if not buttons:
            html = await page.content()
            if "no quest" in html.lower() or "沒有任務" in html:
                result["success"] = True
                result["action_taken"] = "無可領取的任務獎勵"
                return result
            result["error_msg"] = "找不到可領取的任務獎勵按鈕"
            logger.warning(result["error_msg"])
            return result

        for btn in buttons:
            try:
                btn_html = await btn.inner_html()
                btn_text = await btn.text_content()
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=8000)
                await browser_manager.human_delay()
                collected += 1
                collected_rewards.append(btn_text or btn_html[:60])
                logger.info(f"領取任務獎勵: {btn_text or btn_html[:60]}")
            except Exception as e:
                logger.warning(f"點擊任務獎勵按鈕失敗: {e}")

        if collected > 0:
            result["success"] = True
            result["collected_count"] = collected
            result["rewards"] = collected_rewards
            result["action_taken"] = f"已領取 {collected} 個任務獎勵"
            logger.info(f"✅ {result['action_taken']}")
        else:
            result["action_taken"] = "所有按鈕均無法點擊"
            logger.warning(result["action_taken"])

        result["screenshot_path"] = await browser_manager.take_screenshot(page, "quest_reward")

    except Exception as e:
        result["error_msg"] = f"領取任務獎勵失敗: {e}"
        logger.error(result["error_msg"])
        result["screenshot_path"] = await browser_manager.take_screenshot(page, "quest_reward_error")

    return result