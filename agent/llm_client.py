import asyncio
import json
import uuid
import traceback
import time
from typing import Callable, Dict, List, Optional, Any, TYPE_CHECKING

from openai import AsyncOpenAI
from loguru import logger

from config import config
from database import db
from agent.plan_model import BuildPlan, BuildStep
from agent.state_summarizer import compress_state_for_llm
from agent.knowledge_base import get_llm_strategy_context

if TYPE_CHECKING:
    from parser.state_builder import GameState

PLANNING_TOOL = {
    "type": "function",
    "function": {
        "name": "create_build_plan",
        "description": "根據當前遊戲狀態，制定接下來的建造/訓兵計劃",
        "parameters": {
            "type": "object",
            "properties": {
                "strategic_goal": {
                    "type": "string",
                    "description": "本計劃的戰略目標，一句話描述"
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "動作名稱，例如：upgrade_building, upgrade_resource_field, train_troops"
                            },
                            "params": {
                                "type": "object",
                                "description": "動作所需的參數，例如：{\"building_name\": \"Main Building\", \"current_level\": 0}"
                            },
                            "reason": {
                                "type": "string",
                                "description": "LLM的決策理由"
                            },
                            "prerequisite_step_id": {
                                "type": ["string", "null"],
                                "description": "前置步驟id，若無則填 null"
                            },
                            "estimated_cost": {
                                "type": "object",
                                "description": "預估資源成本，例如：{\"wood\": 100, \"clay\": 100, \"iron\": 100, \"crop\": 100}"
                            }
                        },
                        "required": ["action", "params", "reason", "estimated_cost"]
                    },
                    "description": "行動步驟列表。每個元素必須是物件（object），絕對不可以是數字或字串。按優先順序排列，5-15步"
                },
                "replan_trigger": {
                    "type": "string",
                    "description": "什麼情況下需要放棄此計劃並重新規劃"
                },
                "valid_for_hours": {
                    "type": "number",
                    "description": "計劃的有效期（小時），通常2-8小時"
                }
            },
            "required": ["strategic_goal", "steps", "replan_trigger", "valid_for_hours"]
        }
    }
}

WORLD_CLASS_SYSTEM_PROMPT = """
你是 Travian Legends 的世界頂尖玩家 AI 代理人，族群：羅馬人（Roman）。
你的唯一目標是制霸伺服器：最高人口、最強軍隊、最多村莊。

═══════════════════════════════════════
★ 頂尖玩家的核心理解（最重要）★
═══════════════════════════════════════

「搶劫是成長的引擎，不是建設。」

頂尖玩家的資源 90% 來自搶劫其他村莊，只有 10% 來自自己的資源田。
你的目標是儘快建立掠奪機器，讓資源源源不斷從地圖上流向你的村莊。

─────────────────────────────────────
羅馬人特有優勢（必須利用）
─────────────────────────────────────
1. 雙建設（Double Build）：資源田和建築物可以「同時」升級，不用等。
   → 每次規劃必須「同時」安排資源田 + 建築物兩條線。

2. 軍隊品質高：Equites Imperatoris（帝國騎兵）是伺服器最強進攻單位之一。
   → 早期目標：訓練 Legionnaire 用於掠奪，中期過渡到騎兵。

3. 英雄強：Roman 英雄屬性加成攻擊，英雄掠奪效率極高。
   → 英雄必須時刻在外掠奪，不可以待在村莊。

═══════════════════════════════════════
★ 強制執行的建設順序 ★
═══════════════════════════════════════

【第一階段：0~72小時，建立掠奪基礎】

建築線（Main Building 並行）：
  1. Main Building → Lv3（加速建設）
  2. Cranny Lv1（基本保護，頂尖玩家只需 Lv1~2，不是 Lv5）
  3. Barracks Lv1（立刻開始訓練 Legionnaire）
  4. Rally Point Lv1（才能看到地圖上的移動，才能派兵）
  5. Warehouse Lv2 / Granary Lv2（配合訓練消耗）

資源田線（同時進行）：
  - Cropland 全部升到 Lv2（羅馬人糧食消耗大）
  - Clay（黏土）Lv1→2（Barracks需要大量黏土）
  - Wood / Iron 維持和 Clay 同等級即可

【第二階段：72小時~第7天，擴大掠奪規模】

  1. Barracks → Lv5（加快訓練速度，每小時 15+ 兵）
  2. Stable Lv1（如果資源允許，開始訓練騎兵）
  3. Smithy Lv1 → 研究 Legionnaire / Equites 裝備升級
  4. 資源田全面升到 Lv3~4
  5. Main Building → Lv10（解鎖快速建設）
  6. Academy Lv1（為後期做準備）

【第三階段：第7天後，建立軍事霸權】

  1. Equites Imperatoris（帝騎）開始量產
  2. 第二村莊（Colony 方向）：往高倍率 15 穀田擴張
  3. Embassy → 加入最強聯盟
  4. Rally Point → Lv10（派更多隊伍同時掠奪）

═══════════════════════════════════════
★ 掠奪決策規則（硬規則，優先於一切）★
═══════════════════════════════════════

當 troops_at_home > 20 AND has_rally_point = true：
  → 必須在計畫中包含 send_raid 動作，把兵派出去
  → 絕不讓超過 30 個兵待在家裡超過 1 小時（浪費掠奪機會）

掠奪目標優先順序：
  1. 人口 < 60 的村莊（極可能是廢棄帳號）
  2. 人口 60~150 的低活躍玩家
  3. 有 Oasis（綠洲）的格子（Robber/NPC 資源）
  4. 人口 > 300 的玩家（需要評估是否有防禦）

英雄規則：
  - 英雄必須和至少 5~10 個兵一起出去掠奪
  - 英雄在家時視為「資源浪費」，必須馬上派出
  - 英雄等級每升1級，掠奪加成 +10%

═══════════════════════════════════════
★ 軍事防禦規則（被攻擊時）★
═══════════════════════════════════════

incoming_attacks 不為空：
  選項A（推薦）：把資源 trade_to 盟友或隊友 → 不給攻擊者搶到
  選項B：讓資源留在 Cranny 保護範圍內（Lv2 Cranny 保護約 600 資源）
  選項C：反擊（只有在你的軍力 > 對方估計兵力時）

  ⚠ 不要用珍貴兵力做防禦，進攻型軍隊遭到防禦損耗大。
  ⚠ 被打了就繼續掠奪，資源會補回來。

═══════════════════════════════════════
★ 計畫輸出規則 ★
═══════════════════════════════════════

1. 每次規劃必須輸出 15~25 步
2. 必須同時包含兩條平行線：
   - 建築物升級序列
   - 資源田升級序列
3. 如有可派兵機會，必須在計畫開頭就加入 send_raid 步驟
4. 步驟間距合理：考慮建設時間，不要在前一個還在建的時候安排同一建設欄位
5. 禁止輸出 complete，除非兵力超過 500 且所有建築物已達當前階段目標

═══════════════════════════════════════
★ 可用的 action 清單 ★
═══════════════════════════════════════
- upgrade_building: {"building_name": "...", "current_level": ..., "gid": ...}
- upgrade_resource_field: {"field_type": "wood_cutters|clay_pits|iron_mines|croplands", "slot_id": ..., "current_level": ...}
- train_troops: {"troop_type": "...", "count": ...}
- send_raid: {"target_x": ..., "target_y": ..., "troops": {"legionnaire": ...}}
- wait: {"reason": "...", "seconds": ...}

═══════════════════════════════════════
★ 嚴格禁止事項 ★
═══════════════════════════════════════

× 讓兵力在家閒置超過 30 分鐘
× 把 Cranny 升到 Lv5 以上（浪費建設欄位和資源）
× 忽視空地不建設
× 計畫步驟少於 10 步
× 同一個 slot 在計畫中出現兩次
× 先升 Warehouse 而不先升 Barracks（兵比倉庫重要）
"""

class LLMClient:
    def __init__(self):
        self._client = None
        self.model = config.llm_model

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=config.nvidia_api_key
            )
        return self._client

    async def chat(self, messages: List[dict], tools: List[dict] = None,
                   tool_choice: str = "auto", max_tokens: int = None,
                   temperature: float = None) -> dict:
        import random
        max_retries = 3
        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens or config.llm_max_tokens,
                    "temperature": temperature if temperature is not None else config.llm_temperature,
                    "timeout": 45,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                response = await self._get_client().chat.completions.create(**kwargs)

                resp_json = response.model_dump_json()
                usage = response.usage
                await db.log_llm_call(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    model=self.model,
                    response_json=resp_json
                )

                return response.model_dump()

            except Exception as e:
                logger.warning(f"LLM API 呼叫失敗 (第{attempt+1}次): {type(e).__name__}: {str(e)[:100]}")
                if attempt < max_retries - 1:
                    wait_times = [3, 10]
                    jitter = random.uniform(0, 3)
                    wait_time = wait_times[attempt] + jitter
                    logger.info(f"等待 {wait_time:.1f} 秒後重試...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"LLM API 呼叫最終失敗: {e}")
                    raise

    async def request_new_plan(self, state_summary: str, history_summary: str, raw_state: GameState = None) -> BuildPlan:
        """
        呼叫LLM生成新的BuildPlan。
        """
        import json

        # 如果有 raw_state，壓縮成精簡 JSON 附加到提示詞
        compressed = ""
        if raw_state:
            try:
                compressed = json.dumps(compress_state_for_llm(raw_state), ensure_ascii=False, default=str)
            except Exception:
                compressed = ""

        base_content = f"歷史計劃摘要:\n{history_summary}\n\n當前狀態摘要:\n{state_summary}\n"
        if compressed:
            base_content += f"\n精簡狀態 JSON:\n{compressed[:3000]}\n"

        empty_slots_raw = raw_state.get("empty_building_slots", []) if raw_state else []
        if empty_slots_raw:
            from agent.knowledge_base import recommend_building_for_empty_slot
            rec = recommend_building_for_empty_slot(
                current_buildings=raw_state.get("buildings", {}),
                resources=raw_state.get("resources", {}),
                population=raw_state.get("population", 0),
                build_queue_full=raw_state.get("build_queue_full", False),
            )
            if rec:
                base_content += (
                    f"\n\u26a0\ufe0f 重要提示：目前有 {len(empty_slots_raw)} 個建築空地未使用！"
                    f"建議立即建造：{rec['building_name']}（原因：{rec['reason']}）\n"
                )
            else:
                base_content += (
                    f"\n📌 目前有 {len(empty_slots_raw)} 個建築空地，"
                    f"建造佇列已滿，等待空位後繼續建造。\n"
                )

        messages = [
            {"role": "system", "content": WORLD_CLASS_SYSTEM_PROMPT + "\n\n" + get_llm_strategy_context()},
            {"role": "user", "content": base_content + "\n請根據以上資訊，制定最新的建造計劃（10~20 步）。"}
        ]
        
        logger.info("📡 呼叫 LLM 進行戰略規劃...")
        response = await self.chat(
            messages=messages,
            tools=[PLANNING_TOOL],
            tool_choice={"type": "function", "function": {"name": "create_build_plan"}}
        )
        
        choice = response["choices"][0]
        message = choice["message"]
        
        if message.get("tool_calls"):
            tc = message["tool_calls"][0]
            try:
                args = json.loads(tc["function"]["arguments"])
                plan_id = str(uuid.uuid4())
                steps = []
                raw_steps = args.get("steps", [])

                if not isinstance(raw_steps, list):
                    raise ValueError(
                        f"LLM steps 欄位型別錯誤：期望 list，實際 {type(raw_steps).__name__}，"
                        f"原始值：{raw_steps!r}"
                    )

                steps = []
                for idx, step_data in enumerate(raw_steps):
                    if not isinstance(step_data, dict):
                        logger.error(
                            f"steps[{idx}] 型別錯誤：期望 dict，實際 {type(step_data).__name__}，"
                            f"值：{step_data!r}，略過此 step"
                        )
                        continue
                    step_id = str(uuid.uuid4())
                    steps.append(BuildStep(
                        step_id=step_id,
                        action=step_data.get("action", ""),
                        params=step_data.get("params", {}),
                        reason=step_data.get("reason", ""),
                        estimated_cost=step_data.get("estimated_cost", {}),
                        prerequisite_step_id=step_data.get("prerequisite_step_id"),
                        status="pending"
                    ))
                
                if len(steps) == 0:
                    raise ValueError(
                        f"LLM 回傳的 steps 全為無效格式，原始 raw_steps：{raw_steps!r}"
                    )

                plan = BuildPlan(
                    plan_id=plan_id,
                    created_at=time.time(),
                    strategic_goal=args.get("strategic_goal", ""),
                    steps=steps,
                    replan_trigger=args.get("replan_trigger", ""),
                    valid_for_hours=args.get("valid_for_hours", 4.0)
                )
                logger.info(f"✅ LLM 成功生成新計劃: {plan.strategic_goal} ({len(plan.steps)}步)")
                return plan
            except Exception as e:
                logger.error(
                    f"解析計劃失敗: {e}\n"
                    f"完整 Traceback:\n{traceback.format_exc()}\n"
                    f"LLM 原始回傳 args: {args!r}"
                )
                raise ValueError(f"LLM return invalid plan format: {e}") from e
        else:
            raise ValueError("LLM did not return tool_calls")

llm_client = LLMClient()