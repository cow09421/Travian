import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

from config import config
from database import db
from scraper.browser import browser_manager, Page
from scraper.login import login_manager
from parser.state_builder import build_game_state, summarize_state, GameState
from agent.decision import decision_maker
from agent.planner import planner
from agent.memory import memory_manager
from agent.intel import intel_manager
from scheduler.action_dispatcher import execute_single_action, filter_valid_actions
from scheduler.sleep_manager import smart_sleep
from executor.hero import collect_hero_resources, send_hero_adventure, allocate_hero_points
from executor.quests import collect_quest_reward

MIN_SLEEP = 5
MAX_SLEEP = 60
MAP_SCAN_INTERVAL = 600


class Scheduler:
    def __init__(self):
        self.running = False
        self.paused = False
        self.current_page: Optional[Page] = None
        self.latest_state: Optional[dict] = None
        self.last_action_time: Optional[datetime] = None
        self.start_time: Optional[datetime] = None
        self.loop_task: Optional[asyncio.Task] = None
        self._loop_count = 0
        self._consecutive_waits = 0

    async def start(self):
        self.running = True
        self.paused = False
        self.start_time = datetime.now(timezone.utc)
        config.ensure_dirs()
        db.init_db()
        browser = await browser_manager.get_browser()
        self.current_page = await browser_manager.new_page()
        login_ok = await login_manager.ensure_login(self.current_page)
        if not login_ok:
            logger.error("登入失敗，無法啟動排程")
            self.running = False
            return

        await planner.load_active_goal()
        if not planner.current_goal:
            logger.info("無已儲存目標，由 AI 自主規劃第一個目標")
            state = await self._get_current_state()
            if state:
                self.latest_state = state
                summary = summarize_state(state)
                await self._auto_plan_next(state, summary)

        from agent.knowledge_base import knowledge_base
        knowledge_base.init_dirs()

        from agent.reflection import reflection_engine
        await reflection_engine.start()

        self.loop_task = asyncio.create_task(self._main_loop())
        logger.info("全自主排程已啟動")

    async def stop(self):
        from agent.reflection import reflection_engine
        await reflection_engine.stop()
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

    def pause(self):
        self.paused = True
        logger.info("排程已暫停")

    def resume(self):
        self.paused = False
        logger.info("排程已恢復")

    async def _main_loop(self):
        while self.running:
            try:
                if self.paused:
                    await asyncio.sleep(5)
                    continue

                self._loop_count += 1

                if not self.current_page:
                    logger.warning("頁面已關閉，重新獲取")
                    self.current_page = await browser_manager.new_page()
                    await login_manager.ensure_login(self.current_page)

                state = await self._get_current_state()
                if state:
                    self.latest_state = state
                    await db.save_state(state)

                if not state:
                    await asyncio.sleep(MAX_SLEEP)
                    continue

                if await self._pre_loop_priority_checks(state):
                    await asyncio.sleep(MIN_SLEEP)
                    continue

                if not planner.current_goal:
                    summary = summarize_state(state)
                    await self._auto_plan_next(state, summary)
                    await asyncio.sleep(MIN_SLEEP)
                    continue

                recent_actions = await db.get_recent_actions(10)
                memory_summary = await memory_manager.get_summary()
                diplomatic_intel = await intel_manager.get_diplomatic_intel(state)
                state["diplomatic_intel"] = diplomatic_intel
                map_intel = diplomatic_intel["summary_text"]

                from agent.knowledge_base import knowledge_base
                game_knowledge = knowledge_base.get_summary_for_llm()

                bq = state.get("build_queue", [])

                build_queue_full = state.get("build_queue_full", False)
                if build_queue_full:
                    queue_seconds = bq[0].get("seconds_left", 60) if bq else 60
                    sleep_sec = min(queue_seconds + 5, 120)
                    logger.info(f"⏳ 建造隊列已滿，跳過 LLM 決策，直接等待 {sleep_sec} 秒")
                    await asyncio.sleep(sleep_sec)
                    continue
                else:
                    best_field = knowledge_base.get_cheapest_affordable_field(
                        state.get("resource_fields", {}),
                        state.get("resources", {})
                    )
                    best_building = knowledge_base.get_recommended_building_action(state)

                    suggestions = []
                    if best_building:
                        suggestions.append(
                            f"建議蓋建築: {best_building['building_name']}（{best_building['reason']}）"
                        )
                    if best_field:
                        suggestions.append(
                            f"建議升資源田: {best_field['field_type']} slot#{best_field['slot_id']} "
                            f"(Lv{best_field['current_level']}, 資源足夠)"
                        )
                    else:
                        suggestions.append("資源不足以升級任何田")

                    knowledge_suggestion = " | ".join(suggestions) if suggestions else "等待資源累積"

                context = {
                    "recent_actions": recent_actions,
                    "memory": memory_summary or "（無）",
                    "map_intel": map_intel,
                    "goal": planner.current_goal.get("goal_text", "無特定目標"),
                    "game_knowledge": game_knowledge,
                    "knowledge_suggestion": knowledge_suggestion,
                    "strategy_notes": knowledge_base.get_summary_for_llm(),
                    "nudge": (
                        f"⚠️ 你已經連續等待 {self._consecutive_waits} 輪了！找點事做——"
                        f"升級什麼、蓋什麼都行，但不要再等了。"
                        if self._consecutive_waits >= 3 else ""
                    ),
                }

                raw_actions = await decision_maker.think_and_act(state, context)
                actions = await self._filter_valid_actions(raw_actions, state)

                results = []
                for action in actions:
                    result = await self._execute_single_action(action, state)
                    if result.get("success"):
                        knowledge_base.record_success(
                            action.get("name", ""), action.get("arguments", {}),
                            result.get("action_taken", "")
                        )
                    else:
                        knowledge_base.record_failure(
                            action.get("name", ""), action.get("arguments", {}),
                            result.get("error_msg", ""), state
                        )
                    results.append(result)
                    await asyncio.sleep(1)

                success_count = sum(1 for r in results if r.get("success"))
                logger.info(f"本輪完成 {success_count}/{len(results)} 個動作")

                executed_names = [a.get("name", "") for a in actions]
                if executed_names and all(n == "wait" for n in executed_names):
                    self._consecutive_waits += 1
                else:
                    self._consecutive_waits = 0

                if intel_manager.should_scan_map() or (bool(state.get("build_queue")) and intel_manager._last_scan_time is None):
                    logger.info("🗺️ 執行地圖掃描...")
                    try:
                        await intel_manager.scan_nearby(self.current_page)
                    except Exception as e:
                        logger.warning(f"地圖掃描失敗: {e}")

                sleep_sec = self._smart_sleep(state)
                if len(actions) == 0:
                    sleep_sec = min(sleep_sec, 30)
                logger.info(f"⏳ {sleep_sec} 秒後再次評估")
                await asyncio.sleep(sleep_sec)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循環異常: {e}")
                await asyncio.sleep(15)

    def _smart_sleep(self, state: dict) -> int:
        return smart_sleep(state, self._consecutive_waits, MIN_SLEEP, MAX_SLEEP)

    async def _filter_valid_actions(self, actions: list[dict], state: dict) -> list[dict]:
        return filter_valid_actions(actions, state)

    async def _pre_loop_priority_checks(self, state: dict) -> bool:
        hero = state.get("hero", {})
        rr = hero.get("hero_resource_rewards", {})
        if rr and any(v > 0 for v in rr.values()):
            logger.info("🎁 英雄有待轉移資源，優先執行 collect_hero_resources")
            result = await collect_hero_resources(self.current_page)
            await db.log_action("collect_hero_resources", {}, result.get("success", False), result.get("action_taken", ""))
            return True

        quests = state.get("quests", {})
        if quests.get("total_reward_ready", 0) > 0:
            logger.info("🏆 有任務獎勵可領取，優先執行 collect_quest_reward")
            result = await collect_quest_reward(self.current_page)
            await db.log_action("collect_quest_reward", {}, result.get("success", False), result.get("action_taken", ""))
            return True

        return False

    async def _execute_single_action(self, action: dict, state: dict) -> dict:
        name = action.get("name", "")
        args = action.get("arguments", {})

        if name == "complete":
            await planner.complete_goal()
            summary = summarize_state(state)
            await self._auto_plan_next(state, summary)
            result = {"success": True, "action_taken": "目標完成，規劃下一步"}
            self.last_action_time = datetime.now(timezone.utc)
            return result

        result = await execute_single_action(self.current_page, name, args, state)
        self.last_action_time = datetime.now(timezone.utc)
        return result

    async def _get_current_state(self) -> Optional[GameState]:
        try:
            if not self.current_page:
                return None
            dorf1_url = config.travian_url.rstrip("/") + "/dorf1.php"
            ok = await browser_manager.safe_goto(self.current_page, dorf1_url)
            if not ok or "login" in self.current_page.url or "dorf" not in self.current_page.url:
                logger.warning("Session 過期，重新登入...")
                login_manager._logged_in = False
                await login_manager.ensure_login(self.current_page)
                ok = await browser_manager.safe_goto(self.current_page, dorf1_url)
                if not ok:
                    logger.error("重新登入後仍無法載入 dorf1")
                    return None

            html_dorf1 = await self.current_page.content()
            if not html_dorf1:
                return None

            dorf2_url = config.travian_url.rstrip("/") + "/dorf2.php"
            ok2 = await browser_manager.safe_goto(self.current_page, dorf2_url)
            if not ok2:
                logger.warning("dorf2 載入失敗，只用 dorf1 資料")
                state = build_game_state(html_dorf1)
            else:
                html_dorf2 = await self.current_page.content()
                state = build_game_state(html_dorf1, html_dorf2)

            if not state.get("coord_x") and not state.get("coord_y"):
                logger.debug("HTML 解析未取得座標，嘗試 JS 方法...")
                try:
                    x, y = await intel_manager.extract_coords_from_page(self.current_page)
                    if x or y:
                        state["coord_x"] = x
                        state["coord_y"] = y
                except Exception as e:
                    logger.debug(f"JS 座標解析失敗: {e}")

            vx = state.get("coord_x") or state.get("resources", {}).get("coord_x") or 0
            vy = state.get("coord_y") or state.get("resources", {}).get("coord_y") or 0
            vname = state.get("village_name", "")
            if vx or vy:
                intel_manager.set_home(int(vx), int(vy), vname)

            return state
        except Exception as e:
            logger.error(f"獲取狀態失敗: {e}")
            return None

    async def _auto_plan_next(self, state: dict, game_summary: str = ""):
        if not state:
            return
        from agent.llm_client import llm_client

        res = state.get("resources", {})
        bld = state.get("buildings", {})
        fields = state.get("resource_fields", {})

        all_field_levels = []
        for ftype in fields.values():
            for f in ftype:
                all_field_levels.append(f.get("level", 0))
        avg_field = sum(all_field_levels) / max(len(all_field_levels), 1)

        prompt = f"""你是 Travian 遊戲 AI，目前玩家的長期目標是「變強」。

當前遊戲狀態：
- 資源：木={res.get('wood',0)}, 土={res.get('clay',0)}, 鐵={res.get('iron',0)}, 糧={res.get('crop',0)}
- 資源田平均等級：{avg_field:.1f}
- 建築：{list(bld.keys())}
- 建造隊列空閒

根據遊戲進度，給出下一個最優先的具體目標（一句話，可執行的）。
只輸出目標本身，不要解釋。例如：「將所有資源田升到 3 級」"""

        try:
            client = llm_client._get_client()
            resp = await client.chat.completions.create(
                model=config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3
            )
            next_goal = resp.choices[0].message.content.strip()
            logger.info(f"🤖 AI 自主規劃新目標: {next_goal}")

            summary = summarize_state(state)
            await planner.set_goal(next_goal, summary)
        except Exception as e:
            logger.error(f"自主規劃失敗: {e}")


scheduler = Scheduler()