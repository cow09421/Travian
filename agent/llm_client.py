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
                    "description": "按優先順序排列的行動步驟，5-15步"
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

PLANNING_SYSTEM_PROMPT = """你是 Travian Legends 的自動化遊戲代理人。你的族群是羅馬人（Roman）。

## 你的核心職責
根據當前遊戲狀態，產生一個 **10~20 步** 的完整建設計畫。
計畫必須覆蓋接下來數小時的行動，而不是只做一件事。
每次被呼叫都必須輸出足夠多的步驟，避免頻繁重新規劃。

## Travian 策略知識（必須遵守）

### 早期優先序（人口 < 200）
1. **Cranny（地窖，GID=23）**：第一優先。沒有地窖就會被搶光。蓋到 Lv5 以上。
2. **Main Building（GID=15）**：升到 Lv3～5，加快建設速度。
3. **資源田全面升級**：木材(GID=1)、黏土(GID=2)、鐵礦(GID=3) 各升到 Lv3~5。農田(GID=4)優先升（羅馬人農作物消耗高）。
4. **Warehouse（GID=10）** & **Granary（GID=11）**：任何資源或農作物接近上限前必須升。
5. **空地不能留空**：`empty_building_slots` 列表有格子就要填建物。

### 中期優先序（人口 200~500）
1. Barracks（GID=19）→ 練 Legionnaire 保護村莊
2. Rally Point（GID=16）→ 才能派兵
3. 繼續升資源田到 Lv5~8
4. 升 Main Building 到 Lv10（解鎖更快建設）

### 被攻擊處理規則
- `incoming_attacks` 不為空 → 立刻把下一步改為蓋/升 Cranny
- troops_at_home 為空且已有 Barracks → 優先訓練 Legionnaire

### 絕對禁止
- 不可以把同一個 slot 同一個 field_type 重複列入計畫（例如 clay_pits slot#1 已在 queue 就不要再加）
- 計畫步驟不得少於 5 步（除非真的已達到當前階段所有目標）
- 不可以輸出 `complete` 除非確認沒有任何空地且資源田均 Lv5+

## 輸出格式
你必須用工具呼叫（tool use）輸出動作序列。
每次規劃輸出的步驟數：**10~20 步**。
步驟之間依賴性：前步驟的建物完成後才執行需要該建物作前提的後步驟。

## 狀態解讀提示
- `empty_building_slots`: 這些 slot 是空地，必須蓋建物
- `resource_fields_summary`: level=0 表示未升過，優先升
- `build_queue_full: true` 表示建設欄位已滿，這種情況下只能選擇 `wait`
- `incoming_attacks` 有資料時，防禦是最高優先

## 可用的 action 清單
- upgrade_building: {"building_name": "...", "current_level": ..., "gid": ...}
- upgrade_resource_field: {"field_type": "wood_cutters|clay_pits|iron_mines|croplands", "slot_id": ..., "current_level": ...}
- train_troops: {"troop_type": "...", "count": ...}
- wait: {"reason": "...", "seconds": ...}"""

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

        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
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
                for step_data in args.get("steps", []):
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
                logger.error(f"解析計劃失敗: {e}\n{traceback.format_exc()}")
                raise ValueError("LLM return invalid plan format")
        else:
            raise ValueError("LLM did not return tool_calls")

llm_client = LLMClient()