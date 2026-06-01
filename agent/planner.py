"""
agent/planner.py

Goal state machine management.

State transitions: set_goal() → advance_step() → complete_goal()
Persistence: DB read/write for crash recovery.
Navigation logic (advance_step, get_remaining_steps_text) lives here, not in the DB layer.
"""
import json
from typing import List, Optional

from loguru import logger

from agent.llm_client import llm_client
from database import db


class Planner:
    current_goal: Optional[dict] = None
    plan_steps: List[dict] = []
    current_step_index: int = 0

    async def set_goal(self, goal_text: str, game_state_summary: str = "") -> int:
        await db.cancel_goals()
        game_summary = game_state_summary or "尚無遊戲狀態資料"
        plan_data = await llm_client.plan(goal_text, game_summary)
        plan_json = json.dumps(plan_data, ensure_ascii=False)
        goal_id = await db.save_goal(goal_text, plan_json)
        self.current_goal = {
            "id": goal_id,
            "goal_text": goal_text,
            "plan_json": plan_json
        }
        self.plan_steps = plan_data
        self.current_step_index = 0
        logger.info(f"新目標已設定: {goal_text}，共 {len(self.plan_steps)} 個步驟")
        return goal_id

    def get_current_plan_text(self) -> str:
        if not self.plan_steps:
            return "（無計畫）"
        lines = []
        for i, step in enumerate(self.plan_steps):
            prefix = ">>>" if i == self.current_step_index else "   "
            status = "進行中" if i == self.current_step_index else ("已完成" if i < self.current_step_index else "等待中")
            desc = step.get("description", "")
            lines.append(f"{prefix} [{status}] 步驟{i+1}: {desc}")
        return "\n".join(lines)

    def advance_step(self):
        self.current_step_index += 1
        if self.current_step_index >= len(self.plan_steps):
            logger.info("所有計畫步驟已完成")
            return False
        return True

    def get_remaining_steps_text(self) -> str:
        remaining = self.plan_steps[self.current_step_index:]
        if not remaining:
            return "（所有步驟已完成）"
        lines = []
        for i, step in enumerate(remaining):
            idx = self.current_step_index + i
            desc = step.get("description", "")
            lines.append(f"步驟{idx+1}: {desc}")
        return "\n".join(lines)

    async def complete_goal(self):
        if self.current_goal:
            await db.complete_goal(self.current_goal["id"])
            logger.info(f"目標已完成: {self.current_goal['goal_text']}")
            self.current_goal = None
            self.plan_steps = []
            self.current_step_index = 0

    async def load_active_goal(self):
        goal = await db.get_active_goal()
        if goal:
            self.current_goal = goal
            try:
                self.plan_steps = json.loads(goal.get("plan_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                self.plan_steps = []
            self.current_step_index = 0
            logger.info(f"已載入未完成目標: {goal['goal_text']}")
            return True
        return False


planner = Planner()