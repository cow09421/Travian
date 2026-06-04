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
from raider.farm_list import farm_list_manager

MIN_SLEEP = 5
MAX_SLEEP = 60
MAX_REPLAN_RETRIES = 3
REPLAN_BACKOFF_BASE = 60
REPLAN_COOLDOWN = 1800


def _find_building_slot(state: GameState, gid: int) -> Optional[int]:
    """從 buildings_with_slots 中找到指定 gid 的 slot_id"""
    for bname, b in state.get("buildings_with_slots", {}).items():
        if b.get("gid") == gid:
            return b.get("slot")
    return None


def _pre_loop_priority_checks(state: GameState) -> Optional[dict]:
    """硬規則優先，不經 LLM，不燒 token。
    按優先級順序，找到第一個符合的就返回動作。"""
    res = state.get("resources", {})
    buildings = state.get("buildings", {})
    buildings_gid = state.get("buildings_by_gid", {})
    troops_home = state.get("troops", {}).get("home", {})
    total_troops_home = sum(troops_home.values())
    has_rally_point = "Rally Point" in buildings
    has_barracks = "Barracks" in buildings

    # 優先級1（最高）：兵 >20 且有 Rally Point → 派出去掠奪
    if total_troops_home > 20 and has_rally_point:
        ready = farm_list_manager.get_ready_targets()
        if ready:
            target = ready[0]
            return {
                "action": "send_raid",
                "target_x": target.coord_x,
                "target_y": target.coord_y,
                "troops": {"legionnaire": max(5, total_troops_home // 3)},
                "use_farm_list": True,
            }
        # 沒有農場目標但兵太多 → 強制 LLM 處理
        logger.warning(f"{total_troops_home} 兵在家但無農場目標可用，交給 LLM")

    # 優先級2：被攻擊且資源 > Cranny 保護量 → 轉移資源（stub）
    incoming = state.get("diplomatic_intel", {}).get("incoming_attacks", [])
    if incoming:
        logger.warning(f"偵測到 {len(incoming)} 波攻擊，保護資源優先")
        # 用 Cranny 的保護
        cranny_level = buildings.get("Cranny", 0)
        cranny_cap = {0: 0, 1: 400, 2: 600, 3: 800, 4: 1000}.get(cranny_level, 1200)
        wh_cap = res.get("warehouse_cap", 800)
        for r in ["wood", "clay", "iron"]:
            if res.get(r, 0) > min(cranny_cap, wh_cap) * 0.8:
                return {
                    "action": "trade_resources",
                    "target": "alliance_member",
                    "resource_type": r,
                    "reason": "受攻擊前轉移資源",
                }

    # 優先級3：Barracks 不存在 → 強制建 Barracks（比 Warehouse 更優先）
    if not has_barracks and not state.get("build_queue_full", False):
        slot = state.get("next_free_slot")
        if slot is not None:
            return {"action": "upgrade_building", "building_name": "Barracks", "gid": 19, "slot_id": slot}

    # 優先級4：Barracks 存在但訓練佇列為空且資源足夠 → 訓練
    if has_barracks:
        tq = state.get("troop_queue", [])
        if not tq:
            res_w = res.get("wood", 0)
            res_c = res.get("clay", 0)
            # Legionnaire cost: wood=120, clay=130, iron=150, crop=30
            max_by_wood = res_w // 120
            max_by_clay = res_c // 130
            max_count = min(max_by_wood, max_by_clay, 20)
            if max_count >= 3:
                return {
                    "action": "train_troops",
                    "troop_type": "legionnaire",
                    "count": max_count,
                }

    # 優先級5：Cranny (GID=23): 沒有就馬上蓋（新手保護）
    if 23 not in buildings_gid and not state.get("build_queue_full", False):
        slot = state.get("next_free_slot")
        if slot is not None:
            return {"action": "upgrade_building", "gid": 23, "slot_id": slot}

    # 優先級6：Warehouse (GID=10): 任一資源 >85% 倉庫容量就升
    wh_cap = res.get("warehouse_cap", 800)
    if any(res.get(r, 0) > wh_cap * 0.85 for r in ["wood", "clay", "iron"]):
        if not state.get("build_queue_full", False):
            ws = _find_building_slot(state, gid=10)
            if ws is not None:
                return {"action": "upgrade_building", "gid": 10, "slot_id": ws}

    # 優先級7：Granary (GID=11): crop >85%
    gr_cap = res.get("granary_cap", 800)
    if res.get("crop", 0) > gr_cap * 0.85:
        if not state.get("build_queue_full", False):
            gs = _find_building_slot(state, gid=11)
            if gs is not None:
                return {"action": "upgrade_building", "gid": 11, "slot_id": gs}

    return None  # 交給 LLM


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

                state = await self._build_state()
                if not state:
                    await asyncio.sleep(MAX_SLEEP)
                    continue

                await db.save_state(state)

                if await self._run_hard_rules(state):
                    continue

                decision = await rule_engine.evaluate(state, plan_store)

                if decision.need_replan:
                    logger.info("需要重新規劃，呼叫 LLM...")
                    success = await self._replan_with_backoff(state)
                    if not success:
                        logger.warning("本輪重新規劃未完成，繼續主迴圈")
                    await asyncio.sleep(MIN_SLEEP)
                    continue

                await self._execute_step(state, decision)

            except asyncio.CancelledError:
                break
            except Exception as e:
                import traceback
                logger.error(
                    f"主循環未預期異常: {e}\n"
                    f"完整 Traceback:\n{traceback.format_exc()}"
                )
                await asyncio.sleep(15)

    async def _run_hard_rules(self, state: GameState) -> bool:
        """執行硬規則優先檢查，回傳 True 表示已處理（呼叫方應 continue）"""
        hard_rule = _pre_loop_priority_checks(state)
        if not hard_rule:
            return False
        logger.info(f"⚡ 硬規則觸發: {hard_rule['action']}")
        result = await execute_single_action(
            self.current_page, hard_rule["action"], hard_rule, state
        )
        if result.get("success"):
            logger.info(f"✅ 硬規則動作成功")
        else:
            logger.warning(f"❌ 硬規則動作失敗: {result.get('error_msg')}")
        await asyncio.sleep(MIN_SLEEP)
        return True

    async def _execute_step(self, state: GameState, decision) -> None:
        """執行單一 action 並更新 step 狀態"""
        if decision.wait_seconds > 0:
            logger.info(f"等待 {decision.wait_seconds} 秒...")
            await asyncio.sleep(decision.wait_seconds)
        elif decision.action:
            logger.info(f"執行動作: {decision.action} {decision.params}")
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
            await asyncio.sleep(MIN_SLEEP)
        else:
            await asyncio.sleep(MIN_SLEEP)

    async def _do_replan(self, state: GameState):
        """呼叫LLM生成新計劃，寫入PlanStore，並驗證最低步數。"""
        import traceback

        state_summary = state_summarizer.summarize_for_planning(state)
        history_summary = await plan_store.get_plan_history_summary(n=3)
        new_plan = await llm_client.request_new_plan(state_summary, history_summary, raw_state=state)

        if len(new_plan.steps) < 10:
            logger.warning(f"LLM 只產了 {len(new_plan.steps)} 步，補充 wait 至 15 步以避免重複規劃迴圈")
            from agent.plan_model import BuildStep
            import uuid
            for _ in range(15 - len(new_plan.steps)):
                new_plan.steps.append(BuildStep(
                    step_id=str(uuid.uuid4()),
                    action="wait",
                    params={"reason": "補充等待避免重複規劃"},
                    reason="LLM 步驟數過少，自動補充等待",
                    estimated_cost={},
                ))

        await plan_store.save_plan(new_plan)
        logger.info(f"✅ 新計劃已生成寫入資料庫：{new_plan.strategic_goal}，共{len(new_plan.steps)}步")

    async def _replan_with_backoff(self, state: GameState) -> bool:
        """重新規劃，失敗時指數退避重試。
        回傳 True 表示成功，False 表示已超過重試上限進入冷卻。"""
        import traceback

        for attempt in range(1, MAX_REPLAN_RETRIES + 1):
            try:
                logger.info(f"重新規劃嘗試 {attempt}/{MAX_REPLAN_RETRIES}...")
                await self._do_replan(state)
                logger.info(f"重新規劃成功（第 {attempt} 次嘗試）")
                return True

            except Exception as e:
                wait = REPLAN_BACKOFF_BASE * attempt
                logger.error(
                    f"重新規劃失敗（第 {attempt}/{MAX_REPLAN_RETRIES} 次）: {e}\n"
                    f"完整 Traceback:\n{traceback.format_exc()}"
                )
                if attempt < MAX_REPLAN_RETRIES:
                    logger.info(f"等待 {wait}s 後重試...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"重新規劃已達上限 {MAX_REPLAN_RETRIES} 次，"
                        f"進入 {REPLAN_COOLDOWN // 60} 分鐘冷卻"
                    )
                    await asyncio.sleep(REPLAN_COOLDOWN)
                    logger.info("冷卻結束，重置重試計數器")
                    return False

        return False

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