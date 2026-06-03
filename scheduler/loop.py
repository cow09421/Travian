import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from config import config
from database import db
from scraper.browser import browser_manager, Page
from scraper.login import login_manager
from parser.state_builder import build_game_state, summarize_state, GameState

from agent.plan_store import plan_store
from agent.state_summarizer import state_summarizer
from agent.llm_client import llm_client
from scheduler.rule_engine import rule_engine
from scheduler.action_dispatcher import execute_single_action
from agent.intel import intel_manager

MIN_SLEEP = 5
MAX_SLEEP = 60

class GameLoop:
    def __init__(self):
        self.running = False
        self.paused = False
        self.current_page: Optional[Page] = None

    async def start(self):
        self.running = True
        self.paused = False
        config.ensure_dirs()
        db.init_db()
        browser = await browser_manager.get_browser()
        self.current_page = await browser_manager.new_page()
        login_ok = await login_manager.ensure_login(self.current_page)
        if not login_ok:
            logger.error("登入失敗，無法啟動排程")
            self.running = False
            return

        from agent.knowledge_base import knowledge_base
        knowledge_base.init_dirs()

        self.loop_task = asyncio.create_task(self._main_loop())
        logger.info("全自主排程已啟動")

    async def stop(self):
        self.running = False
        if self.loop_task:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
        if self.current_page:
            await browser_manager.close_page(self.current_page)
        await browser_manager.close()
        db.close()
        logger.info("排程已停止")

    async def _main_loop(self):
        while self.running:
            try:
                if self.paused:
                    await asyncio.sleep(5)
                    continue

                if not self.current_page:
                    self.current_page = await browser_manager.new_page()
                    await login_manager.ensure_login(self.current_page)

                # 1. 獲取遊戲狀態
                state = await self._build_state()
                if not state:
                    await asyncio.sleep(MAX_SLEEP)
                    continue

                await db.save_state(state)

                # 2. RuleEngine評估（不呼叫LLM）
                decision = await rule_engine.evaluate(state, plan_store)

                # 3. 如果需要重新規劃，呼叫LLM
                if decision.need_replan:
                    logger.info("需要重新規劃，呼叫 LLM...")
                    await self._do_replan(state)
                    await asyncio.sleep(MIN_SLEEP)
                    continue
                
                # 4. 執行動作
                if decision.wait_seconds > 0:
                    logger.info(f"等待 {decision.wait_seconds} 秒...")
                    await asyncio.sleep(decision.wait_seconds)
                elif decision.action:
                    logger.info(f"執行動作: {decision.action} {decision.params}")
                    
                    # 取出對應的 step_id
                    step = await plan_store.get_next_pending_step()
                    step_id = step.step_id if step and step.action == decision.action else None
                    
                    if step_id:
                        await plan_store.advance_step(step_id, "executing")

                    result = await execute_single_action(self.current_page, decision.action, decision.params, state)
                    
                    if result.get("success"):
                        logger.info(f"✅ 動作成功: {result.get('action_taken')}")
                        if step_id:
                            await plan_store.advance_step(step_id, "done")
                    else:
                        logger.warning(f"❌ 動作失敗: {result.get('error_msg')}")
                        if step_id:
                            await plan_store.advance_step(step_id, "failed")
                            # Check if consecutive failures requires replanning (todo)
                    
                    await asyncio.sleep(MIN_SLEEP)
                else:
                    await asyncio.sleep(MIN_SLEEP)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循環異常: {e}")
                await asyncio.sleep(15)

    async def _do_replan(self, state: GameState):
        """呼叫LLM生成新計劃，寫入PlanStore"""
        try:
            state_summary = state_summarizer.summarize_for_planning(state)
            history_summary = await plan_store.get_plan_history_summary(n=3)
            new_plan = await llm_client.request_new_plan(state_summary, history_summary)
            await plan_store.save_plan(new_plan)
            logger.info(f"✅ 新計劃已生成寫入資料庫：{new_plan.strategic_goal}，共{len(new_plan.steps)}步")
        except Exception as e:
            logger.error(f"重新規劃失敗: {e}")

    async def _build_state(self) -> GameState:
        try:
            dorf1_url = config.travian_url.rstrip("/") + "/dorf1.php"
            ok = await browser_manager.safe_goto(self.current_page, dorf1_url)
            if not ok or "login" in self.current_page.url or "dorf" not in self.current_page.url:
                login_manager._logged_in = False
                await login_manager.ensure_login(self.current_page)
                ok = await browser_manager.safe_goto(self.current_page, dorf1_url)
                if not ok:
                    return None

            html_dorf1 = await self.current_page.content()
            if not html_dorf1:
                return None

            dorf2_url = config.travian_url.rstrip("/") + "/dorf2.php"
            ok2 = await browser_manager.safe_goto(self.current_page, dorf2_url)
            if not ok2:
                state = build_game_state(html_dorf1)
            else:
                html_dorf2 = await self.current_page.content()
                state = build_game_state(html_dorf1, html_dorf2)

            return state
        except Exception as e:
            logger.error(f"獲取狀態失敗: {e}")
            return None

scheduler = GameLoop()