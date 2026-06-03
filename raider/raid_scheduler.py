"""
獨立的掠奪排程器，和建設排程器分開運行。
每隔 10 分鐘檢查一次是否有兵可以派出。
"""
import asyncio
from loguru import logger
from raider.farm_list import farm_list_manager


class RaidScheduler:
    def __init__(self, executor, scraper):
        self.executor = executor
        self.scraper = scraper
        self.check_interval = 600

    async def run(self):
        logger.info("掠奪排程器啟動")
        while True:
            try:
                await self._raid_cycle()
            except Exception as e:
                logger.error(f"掠奪循環錯誤: {e}")
            await asyncio.sleep(self.check_interval)

    async def _raid_cycle(self):
        state = await self.scraper.get_game_state()
        troops_home = state.get("troops", {}).get("home", {})
        total_troops = sum(troops_home.values())

        if total_troops < 5:
            logger.debug("兵力不足，等待訓練完成")
            return

        ready_targets = farm_list_manager.get_ready_targets()
        if not ready_targets:
            logger.debug("所有農場目標冷卻中")
            return

        troops_to_send = max(5, total_troops // len(ready_targets[:5]))

        for target in ready_targets[:5]:
            logger.info(f"派 {troops_to_send} 兵掠奪 ({target.coord_x}|{target.coord_y}) {target.village_name}")
            result = await self.executor.send_raid(
                x=target.coord_x,
                y=target.coord_y,
                troops={"legionnaire": troops_to_send},
            )
            if result.get("success"):
                logger.info(f"掠奪成功: ({target.coord_x}|{target.coord_y})")
            else:
                logger.warning(f"掠奪失敗: {result.get('error_msg')}")


raid_scheduler = RaidScheduler(None, None)