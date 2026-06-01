from typing import Optional

from playwright.async_api import Page
from loguru import logger

from scraper.browser import browser_manager
from scraper.login import login_manager


class PageReader:

    async def get_page(self, url: Optional[str] = None) -> Optional[Page]:
        page = None
        try:
            page = await browser_manager.new_page()
            if url:
                ok = await browser_manager.safe_goto(page, url)
                if not ok:
                    await browser_manager.close_page(page)
                    return None
            login_ok = await login_manager.ensure_login(page)
            if not login_ok:
                await browser_manager.close_page(page)
                return None
            return page
        except Exception as e:
            logger.error(f"獲取頁面失敗: {e}")
            if page:
                await browser_manager.close_page(page)
            return None

    async def read_html(self, url: str) -> Optional[str]:
        page = await self.get_page(url)
        if not page:
            return None
        try:
            html = await page.content()
            return html
        except Exception as e:
            logger.error(f"讀取 HTML 失敗: {e}")
            return None
        finally:
            await browser_manager.close_page(page)

    async def read_current_html(self, page: Page) -> Optional[str]:
        try:
            return await page.content()
        except Exception as e:
            logger.error(f"讀取當前頁面 HTML 失敗: {e}")
            return None


page_reader = PageReader()