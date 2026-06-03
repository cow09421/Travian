"""
scheduler/action_dispatcher.py

Action filtering and dispatch.
- filter_valid_actions(actions, state) → filtered action list
- execute_single_action(page, action_name, action_params, state) → result dict
"""
import json
from datetime import datetime, timezone

from playwright.async_api import Page
from loguru import logger

from database import db
from executor.build import upgrade_building, upgrade_resource_field
from executor.train import train_troops
from executor.attack import send_attack, send_raid, send_scout
from executor.hero import collect_hero_resources, send_hero_adventure, allocate_hero_points
from executor.quests import collect_quest_reward
from parser.state_builder import summarize_state, GameState
from shared.troop_data import get_building_gid_for_troop as _get_troop_building_gid


async def execute_single_action(
    page: Page,
    action_name: str,
    action_params: dict,
    state: GameState,
) -> dict:
    try:
        logger.info(f"🎮 執行動作: {action_name}, 參數: {json.dumps(action_params, ensure_ascii=False)[:200]}")
        result = {}

        if action_name == "upgrade_building":
            result = await upgrade_building(
                page,
                action_params.get("building_name", ""),
                action_params.get("current_level")
            )
        elif action_name == "upgrade_resource_field":
            result = await upgrade_resource_field(
                page,
                action_params.get("field_type", ""),
                action_params.get("slot_id", 0),
                action_params.get("current_level")
            )
        elif action_name == "train_troops":
            result = await train_troops(
                page,
                action_params.get("troop_type", ""),
                action_params.get("count", 10),
                state=state
            )
        elif action_name == "send_attack":
            result = await send_attack(
                page,
                action_params.get("target_x", 0),
                action_params.get("target_y", 0),
                action_params.get("mission_type", "raid"),
                action_params.get("troops", {})
            )
        elif action_name == "send_raid":
            result = await send_raid(
                page,
                action_params.get("target_x", 0),
                action_params.get("target_y", 0),
                action_params.get("troops", {})
            )
        elif action_name == "send_scout":
            result = await send_scout(
                page,
                action_params.get("target_x", 0),
                action_params.get("target_y", 0)
            )
        elif action_name == "wait":
            result = {"success": True, "action_taken": f"等待: {action_params.get('reason', '')}"}
        elif action_name == "collect_hero_resources":
            result = await collect_hero_resources(page)
        elif action_name == "send_hero_on_adventure":
            result = await send_hero_adventure(
                page,
                action_params.get("adventure_id")
            )
        elif action_name == "allocate_hero_points":
            result = await allocate_hero_points(
                page,
                action_params.get("attribute", "resources"),
                action_params.get("points", 1)
            )
        elif action_name == "collect_quest_reward":
            result = await collect_quest_reward(
                page,
                action_params.get("quest_id")
            )
        elif action_name == "complete":
            from parser.state_builder import summarize_state
            from agent.plan_store import plan_store
            await plan_store.invalidate_plan("目標完成")
            summary = summarize_state(state)
            result = {"success": True, "action_taken": "目標完成，規劃下一步"}
        else:
            result = {"success": False, "error_msg": f"未知動作: {action_name}"}

        status_icon = "✅" if result.get("success") else "❌"
        logger.info(f"{status_icon} {result.get('action_taken') or result.get('error_msg', '')}")

        await db.log_action(
            action_type=action_name,
            action_params=action_params,
            success=result.get("success", False),
            result_text=result.get("action_taken") or result.get("error_msg", ""),
            screenshot_path=result.get("screenshot_path")
        )

        return result

    except Exception as e:
        logger.error(f"執行動作時出錯: {e}")
        await db.log_action("error", {}, False, str(e))
        return {"success": False, "error_msg": str(e)}


def filter_valid_actions(actions: list[dict], state: dict) -> list[dict]:
    bq = state.get("build_queue", [])
    tq = state.get("troop_queue", [])
    build_queue_full = state.get("build_queue_full", False)

    fields_by_slot = {}
    for ftype, f_list in state.get("resource_fields", {}).items():
        for f in f_list:
            fields_by_slot[f["slot"]] = {**f, "field_type": ftype}

    valid = []
    build_action_count = 0

    for action in actions:
        name = action.get("name", "")
        args = action.get("arguments", {})

        if name in ("upgrade_resource_field", "upgrade_building"):
            if build_queue_full:
                logger.debug(f"⏳ 跳過: {name} - 建造隊列已滿（正常等待）")
                continue
            if build_action_count >= 1:
                logger.warning(f"🚫 過濾: {name} - 本輪已有建造動作")
                continue
            if name == "upgrade_resource_field":
                slot_id = args.get("slot_id", 0)
                if slot_id <= 0 or slot_id not in fields_by_slot:
                    logger.warning(f"🚫 過濾: slot_id={slot_id} 無效")
                    continue
                action["arguments"]["current_level"] = fields_by_slot[slot_id]["level"]
            build_action_count += 1

        elif name == "train_troops":
            if len(tq) > 0:
                logger.info("ℹ️ 跳過訓兵: 訓兵隊列有任務")
                continue

            troop_type = args.get("troop_type", "")
            buildings = state.get("buildings", {})

            building_gid = _get_troop_building_gid(troop_type)
            required_building = {19: "Barracks", 20: "Stable", 21: "Workshop"}.get(building_gid) if building_gid else None

            if required_building and required_building not in buildings:
                logger.warning(f"🚫 跳過訓兵: {required_building} 尚未建造（無法訓練 {args.get('troop_type')}）")
                continue

            if required_building and buildings.get(required_building, 0) <= 0:
                logger.warning(f"🚫 跳過訓兵: {required_building} 等級為 0")
                continue

        valid.append(action)

    logger.info(f"📋 動作過濾: {len(actions)} → {len(valid)} 個")
    return valid