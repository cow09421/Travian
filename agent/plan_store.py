import json
import uuid
import time
from typing import Optional, List

import aiosqlite
from loguru import logger

from agent.plan_model import BuildPlan, BuildStep
from database import db

class PlanStore:
    def __init__(self):
        self.db_path = db.db_path

    async def save_plan(self, plan: BuildPlan) -> None:
        async with aiosqlite.connect(self.db_path) as db_conn:
            await db_conn.execute(
                """INSERT OR REPLACE INTO build_plans
                   (plan_id, created_at, strategic_goal, plan_json, replan_trigger, valid_for_hours, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'active')""",
                (plan.plan_id, plan.created_at, plan.strategic_goal,
                 json.dumps(plan.to_dict(), ensure_ascii=False),
                 plan.replan_trigger, plan.valid_for_hours)
            )
            await db_conn.commit()
            logger.info(f"💾 計劃 {plan.plan_id} 已儲存")

    async def load_active_plan(self) -> Optional[BuildPlan]:
        async with aiosqlite.connect(self.db_path) as db_conn:
            db_conn.row_factory = aiosqlite.Row
            cur = await db_conn.execute(
                "SELECT * FROM build_plans WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
            )
            row = await cur.fetchone()
            if row:
                try:
                    data = json.loads(row["plan_json"])
                    return BuildPlan.from_dict(data)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode plan JSON for plan_id {row['plan_id']}")
            return None

    async def update_plan(self, plan: BuildPlan) -> None:
        # Re-save plan to update step statuses
        async with aiosqlite.connect(self.db_path) as db_conn:
            await db_conn.execute(
                "UPDATE build_plans SET plan_json = ? WHERE plan_id = ?",
                (json.dumps(plan.to_dict(), ensure_ascii=False), plan.plan_id)
            )
            await db_conn.commit()

    async def advance_step(self, step_id: str, status: str) -> None:
        plan = await self.load_active_plan()
        if not plan:
            return
        updated = False
        for step in plan.steps:
            if step.step_id == step_id:
                step.status = status
                updated = True
                break
        if updated:
            await self.update_plan(plan)
            # If all steps are done/failed/skipped, we might want to mark the plan as completed.
            all_finished = all(s.status in ["done", "failed", "skipped"] for s in plan.steps)
            if all_finished:
                await self.invalidate_plan("All steps finished")

    async def get_next_pending_step(self) -> Optional[BuildStep]:
        plan = await self.load_active_plan()
        if not plan:
            return None
        
        for step in plan.steps:
            if step.status == "pending" or step.status == "executing":
                # Ensure prerequisites are met
                if step.prerequisite_step_id:
                    prereq = next((s for s in plan.steps if s.step_id == step.prerequisite_step_id), None)
                    if prereq and prereq.status != "done":
                        continue
                return step
        return None

    async def invalidate_plan(self, reason: str) -> None:
        async with aiosqlite.connect(self.db_path) as db_conn:
            await db_conn.execute(
                "UPDATE build_plans SET status = 'invalidated', invalidated_reason = ? WHERE status = 'active'",
                (reason,)
            )
            await db_conn.commit()
            logger.info(f"🚫 當前計劃已失效: {reason}")

    async def get_plan_history_summary(self, n: int = 5) -> str:
        async with aiosqlite.connect(self.db_path) as db_conn:
            db_conn.row_factory = aiosqlite.Row
            cur = await db_conn.execute(
                "SELECT * FROM build_plans ORDER BY created_at DESC LIMIT ?", (n,)
            )
            rows = await cur.fetchall()
            
            if not rows:
                return "無歷史計劃"
            
            lines = []
            for row in reversed(rows):
                # Reverse to show oldest to newest in history
                t = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["created_at"]))
                status = row["status"]
                goal = row["strategic_goal"]
                reason = row["invalidated_reason"] or ""
                if status == "active":
                    lines.append(f"[{t}] (執行中) 目標: {goal}")
                else:
                    lines.append(f"[{t}] ({status}) 目標: {goal} {f'({reason})' if reason else ''}")
            
            return "\n".join(lines)

plan_store = PlanStore()
