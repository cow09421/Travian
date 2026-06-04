import asyncio
import random
import subprocess
import sys
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from loguru import logger

from config import config


class BrowserManager:
    _instance: Optional["BrowserManager"] = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _playwright = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def ensure_playwright_installed(self):
        try:
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, check=True
            )
            logger.info("Chromium 已安裝")
        except subprocess.CalledProcessError as e:
            logger.warning(f"playwright install 失敗: {e}，嘗試繼續...")

    async def get_browser(self) -> Browser:
        if self._browser is None:
            await self.ensure_playwright_installed()
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=config.headless,
                slow_mo=config.browser_slow_mo,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            )
            logger.info("瀏覽器已啟動")
        return self._browser

    async def get_context(self) -> BrowserContext:
        if self._context is None:
            browser = await self.get_browser()
            self._context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            logger.info("瀏覽器 context 已建立")
        return self._context

    async def new_page(self) -> Page:
        ctx = await self.get_context()
        page = await ctx.new_page()
        return page

    async def close_page(self, page: Page):
        try:
            await page.close()
        except Exception as e:
            logger.debug(f"關閉頁面時出錯: {e}")

    async def close(self):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"關閉瀏覽器時出錯: {e}")
        finally:
            self._context = None
            self._browser = None
            self._playwright = None
            logger.info("瀏覽器已關閉")

    async def human_delay(self, min_s: float = None, max_s: float = None):
        mn = min_s if min_s is not None else config.min_operation_delay
        mx = max_s if max_s is not None else config.max_operation_delay
        delay = random.uniform(mn, mx)
        logger.debug(f"人類模擬延遲 {delay:.2f} 秒")
        await asyncio.sleep(delay)

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser page not initialized. Call launch() first.")
        return self._page

    async def safe_goto(self, page: Page, url: str, max_retries: int = 3) -> bool:
        for attempt in range(1, max_retries + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                await self.human_delay()
                return True
            except Exception as e:
                logger.warning(f"導航到 {url} 失敗 (第{attempt}次): {e}")
                if attempt == max_retries:
                    return False
                await asyncio.sleep(2 ** attempt)
        return False

    async def safe_click(self, page: Page, selector: str, max_retries: int = 3) -> bool:
        for attempt in range(1, max_retries + 1):
            try:
                await page.wait_for_selector(selector, timeout=10000)
                await page.click(selector)
                await self.human_delay()
                return True
            except Exception as e:
                logger.warning(f"點擊 {selector} 失敗 (第{attempt}次): {e}")
                if attempt == max_retries:
                    return False
                await asyncio.sleep(1)
        return False

    async def take_screenshot(self, page: Page, prefix: str) -> str | None:
        try:
            from config import config
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = config.screenshots_dir / f"{prefix}_{ts}.png"
            await page.screenshot(path=str(path))
            return str(path)
        except Exception as e:
            logger.debug(f"截圖失敗 ({prefix}): {e}")
            return None

    async def get_page_html(self, page: Page, url: str = None) -> Optional[str]:
        try:
            if url:
                ok = await self.safe_goto(page, url)
                if not ok:
                    return None
            html = await page.content()
            return html
        except Exception as e:
            logger.error(f"獲取頁面 HTML 失敗: {e}")
            return None


browser_manager = BrowserManager()