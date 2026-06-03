import time
from dataclasses import dataclass
from typing import Dict, Any, Optional
from parser.state_builder import GameState
from agent.plan_store import PlanStore
from agent.knowledge_base import knowledge_base, BUILDING_COSTS

@dataclass
class RuleDecision:
    action: str
    params: Dict[str, Any]
    need_replan: bool
    wait_seconds: int

class RuleEngine:
    async def evaluate(self, state: GameState, plan_store: PlanStore) -> RuleDecision:
        try:
            # P0 Emergency Checks
            res = state.get("resources", {})
            wood, clay, iron, crop = res.get('wood') or 0, res.get('clay') or 0, res.get('iron') or 0, res.get('crop') or 0
            wh_cap = res.get('warehouse_cap') or 800
            gr_cap = res.get('granary_cap') or 800
            crop_rate = res.get('crop_rate') or 0
        
        # 1. 糧食負產量且糧倉低於20%
        if crop_rate < 0 and crop < gr_cap * 0.2:
            fields = state.get("resource_fields", {}).get("croplands", [])
            if fields:
                min_field = min(fields, key=lambda f: f.get("level", 0))
                return RuleDecision("upgrade_resource_field", {"field_type": "croplands", "slot_id": min_field.get("slot"), "current_level": min_field.get("level")}, False, 0)
                
        # 2. 倉庫/糧倉滿載 (>90%)
        if wood > wh_cap * 0.9 or clay > wh_cap * 0.9 or iron > wh_cap * 0.9:
            bld = state.get("buildings", {})
            if "Warehouse" in bld:
                return RuleDecision("upgrade_building", {"building_name": "Warehouse", "current_level": bld["Warehouse"]}, False, 0)
                
        if crop > gr_cap * 0.9:
            bld = state.get("buildings", {})
            if "Granary" in bld:
                return RuleDecision("upgrade_building", {"building_name": "Granary", "current_level": bld["Granary"]}, False, 0)

        # 3. 英雄獎勵
        hero = state.get("hero", {})
        if hero.get("hero_resource_rewards") and any(v > 0 for v in hero["hero_resource_rewards"].values()):
            return RuleDecision("collect_hero_resources", {"reason": "英雄資源待領取"}, False, 0)
            
        # 4. 任務獎勵
        quests = state.get("quests", {})
        if quests.get("total_reward_ready", 0) > 0:
            return RuleDecision("collect_quest_reward", {}, False, 0)

        # 5. 英雄血量過低
        if hero.get("hero_health", 100) < 20:
            return RuleDecision("wait", {"reason": "英雄血量過低"}, False, 600)

        # 佇列檢查
        bq = state.get("build_queue", [])
        build_queue_full = state.get("build_queue_full", False)

        # 獲取計劃
        plan = await plan_store.load_active_plan()
        
        # P3 失效判斷
        if plan:
            hours_elapsed = (time.time() - plan.created_at) / 3600
            if hours_elapsed > plan.valid_for_hours:
                await plan_store.invalidate_plan(f"計劃超時 ({hours_elapsed:.1f} > {plan.valid_for_hours} 小時)")
                return RuleDecision("", {}, True, 0)
                
            # Todo: 連續失敗判斷等其他邏輯可以加在 action dispatcher 的失敗反饋中，或記錄在 store
            
        # P1 執行計劃
        step = await plan_store.get_next_pending_step()
        if step:
            if build_queue_full and step.action in ["upgrade_building", "upgrade_resource_field"]:
                queue_seconds = bq[0].get("seconds_left", 60) if bq else 60
                return RuleDecision("wait", {"reason": "佇列已滿"}, False, min(queue_seconds + 5, 120))
                
            cost = step.estimated_cost
            if cost:
                if wood < cost.get("wood", 0) or clay < cost.get("clay", 0) or iron < cost.get("iron", 0) or crop < cost.get("crop", 0):
                    # 資源不足，計算需要等待的時間
                    # 簡化計算：等待固定時間讓資源增加，或者呼叫精確計算
                    return RuleDecision("wait", {"reason": "資源不足"}, False, 300)
            
            # 準備執行，在此階段我們只返回決策，真正的執行和狀態更新交由 dispatcher / loop 處理
            return RuleDecision(step.action, step.params, False, 0)
            
            # P2 無計畫或計劃完成
            return RuleDecision("", {}, True, 60)
            
        except Exception as e:
            import traceback
            from loguru import logger
            logger.error(f"RuleEngine異常：{e}")
            logger.error(traceback.format_exc())
            return RuleDecision(action="wait", params={}, wait_seconds=60, need_replan=False)

rule_engine = RuleEngine()
