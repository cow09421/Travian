import os
import sys
import asyncio
import signal
from datetime import datetime
from pathlib import Path

try:
    from loguru import logger
    from config import config, validate_config
    from scheduler.loop import scheduler
    from raider.raid_scheduler import raid_scheduler
    from raider.farm_list import farm_list_manager
except ImportError as e:
    print(f"\n❌ 套件匯入失敗: {e}")
    print("請執行: pip install -r requirements.txt")
    input("\n按 Enter 關閉...")
    sys.exit(1)
except Exception as e:
    import traceback
    print(f"\n❌ 啟動時發生錯誤: {e}")
    traceback.print_exc()
    input("\n按 Enter 關閉...")
    sys.exit(1)


LOG_FILE = config.logs_dir / f"travian_{datetime.now().strftime('%Y%m%d')}.log"
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:7}</level> | {message}")
logger.add(str(LOG_FILE), level="DEBUG",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level:7} | {name}:{line} | {message}",
           rotation="10 MB", retention="7 days")


async def startup_check():
    print("\n🔍 啟動檢查中...\n")

    print("  [1/4] 檢查 .env 設定...", end=" ")
    try:
        validate_config()
        config.ensure_dirs()
        for folder in [config.logs_dir, config.screenshots_dir]:
            folder.mkdir(parents=True, exist_ok=True)
        print("✅")
    except SystemExit:
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False

    print("  [2/4] 初始化資料庫...", end=" ")
    try:
        from database import db
        db.init_db()
        print("✅")
    except Exception as e:
        print(f"❌ {e}")
        input("\n按 Enter 關閉...")
        return False

    print("  [3/4] 檢查 Playwright 瀏覽器...", end=" ")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        print("✅")
    except Exception as e:
        print(f"❌ {e}")
        print("  請執行：playwright install chromium")
        input("\n按 Enter 關閉...")
        return False

    print("  [4/4] 測試 NVIDIA API 連線...", end=" ")
    try:
        import httpx
        api_key = config.nvidia_api_key
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://integrate.api.nvidia.com/v1/models",
                headers=headers
            )
            if resp.status_code == 200:
                print("✅")
            else:
                print(f"⚠️ HTTP {resp.status_code}")
    except ImportError:
        print("⚠️ httpx 未安裝，跳過 API 測試")
    except Exception as e:
        print(f"⚠️ {e}")

    print("\n✅ 所有檢查通過\n")
    return True


async def main():
    logger.info("🤖 Travian AI Agent 啟動中（全自主模式）")
    logger.info(f"目標伺服器: {config.travian_url}")

    ok = await startup_check()
    if not ok:
        logger.error("啟動檢查失敗")
        return

    await scheduler.start()

    if not scheduler.running:
        logger.error("啟動失敗")
        return

    # 注入實際的 executor 和 scraper 給 raid_scheduler
    from scheduler.action_dispatcher import execute_single_action
    from scraper.browser import browser_manager

    async def _scraper_get_state():
        page = browser_manager._page
        if not page:
            return {}
        from scheduler.loop import _build_state
        state = await scheduler._build_state()
        return state or {}

    raid_scheduler.executor = type("Executor", (), {"send_raid": lambda x, y, troops=None: execute_single_action(
        browser_manager._page, "send_raid", {"target_x": x, "target_y": y, "troops": troops or {}}, {}
    )})()
    raid_scheduler.scraper = type("Scraper", (), {"get_game_state": _scraper_get_state})()

    logger.info("✅ 已登入 Travian，AI 將自動管理所有遊戲操作")
    logger.info("📋 按 Ctrl+C 停止")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("收到停止信號")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        pass

    # 並行執行兩個排程器
    raid_task = asyncio.create_task(raid_scheduler.run())
    main_task = asyncio.create_task(stop_event.wait())

    try:
        done, pending = await asyncio.wait(
            [main_task, raid_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("正在關閉...")
        await scheduler.stop()
        logger.info("Travian AI Agent 已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print(f"\n❌ 未預期錯誤: {e}")
        traceback.print_exc()
    finally:
        print("程式已結束")