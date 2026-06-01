import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import Page
from loguru import logger

from config import config
from scraper.browser import browser_manager

SESSION_FILE = Path(config.base_dir) / "session.json"


class LoginManager:
    _logged_in: bool = False

    def _is_game_url(self, url: str) -> bool:
        game_keywords = ["dorf1", "dorf2", "ingame", "village", "build.php",
                         "map.php", "hero", "profile", "allianceOverview"]
        return any(kw in url for kw in game_keywords)

    async def is_logged_in(self, page: Page) -> bool:
        if self._logged_in:
            return True
        try:
            current_url = page.url
            if self._is_game_url(current_url):
                self._logged_in = True
                return True
            content = await page.content()
            if any(kw in content for kw in ["resourceFieldId", "buildingSlot",
                                             "wood\",", "\"clay\"", "dorf1.php"]):
                self._logged_in = True
                return True
            return False
        except Exception as e:
            logger.error(f"檢查登入狀態失敗: {e}")
            return False

    async def verify_login_by_navigation(self, page: Page) -> bool:
        try:
            dorf1_url = config.travian_url.rstrip("/") + "/dorf1.php"
            await page.goto(dorf1_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            if self._is_game_url(page.url):
                self._logged_in = True
                return True
            return False
        except Exception as e:
            logger.error(f"導航驗證失敗: {e}")
            return False

    async def restore_session(self, page: Page) -> bool:
        if not SESSION_FILE.exists():
            logger.info("無儲存的 session 檔案")
            return False
        try:
            storage = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            context = page.context
            await context.add_cookies(storage.get("cookies", []))
            logger.info("已還原 session，驗證中...")
            return await self.verify_login_by_navigation(page)
        except Exception as e:
            logger.warning(f"還原 session 失敗: {e}")
            return False

    async def save_session(self, page: Page):
        try:
            cookies = await page.context.cookies()
            SESSION_FILE.write_text(
                json.dumps({"cookies": cookies}, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.info("Session 已儲存")
        except Exception as e:
            logger.warning(f"儲存 session 失敗: {e}")

    async def login(self, page: Page) -> bool:
        if await self.restore_session(page):
            logger.info("Session 還原成功，已登入")
            return True

        logger.info("執行登入流程...")
        try:
            login_url = config.travian_url.rstrip("/") + "/login.php"
            await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            username_sel = "input[name='name']"
            password_sel = "input[name='password']"
            submit_sel = "button[type='submit']"

            try:
                await page.wait_for_selector(username_sel, timeout=15000)
            except Exception:
                username_sel = "input[type='text'], input[type='email']"
                try:
                    await page.wait_for_selector(username_sel, timeout=5000)
                except Exception:
                    logger.error("找不到登入表單，截圖留存")
                    await page.screenshot(
                        path=str(config.screenshots_dir / "login_no_form.png")
                    )
                    return False

            await page.click(username_sel)
            await page.keyboard.press("Control+a")
            await page.type(username_sel, config.travian_username, delay=80)
            await browser_manager.human_delay(0.5, 1.0)

            await page.click(password_sel)
            await page.keyboard.press("Control+a")
            await page.type(password_sel, config.travian_password, delay=80)
            await browser_manager.human_delay(0.5, 1.0)

            await page.screenshot(
                path=str(config.screenshots_dir / "login_before_submit.png")
            )

            try:
                await page.wait_for_selector(submit_sel, timeout=5000)
                await page.click(submit_sel)
            except Exception:
                await page.press(password_sel, "Enter")

            try:
                await page.wait_for_function(
                    "() => ['dorf1','dorf2','ingame','village','build.php','map.php'].some(k => window.location.href.includes(k))",
                    timeout=12000
                )
                logger.info(f"登入後跳轉到: {page.url}")
            except Exception:
                await page.wait_for_timeout(6000)

            await page.screenshot(
                path=str(config.screenshots_dir / "login_after_submit.png")
            )

            if self._is_game_url(page.url):
                self._logged_in = True
                await self.save_session(page)
                logger.info(f"✅ 登入成功！頁面: {page.url}")
                return True
            else:
                logger.error(f"登入失敗，當前 URL: {page.url}")
                return False

        except Exception as e:
            logger.error(f"登入過程出錯: {e}")
            try:
                await page.screenshot(
                    path=str(config.screenshots_dir / "login_error.png")
                )
            except Exception:
                pass
            return False

    async def ensure_login(self, page: Page) -> bool:
        if self._logged_in:
            return True
        result = await self.login(page)
        if not result:
            logger.warning("第一次登入失敗，等待 3 秒後重試...")
            await asyncio.sleep(3)
            result = await self.login(page)
        return result

    def logout(self):
        self._logged_in = False
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
            logger.info("已清除 session")


login_manager = LoginManager()