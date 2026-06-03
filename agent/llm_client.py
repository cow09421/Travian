import asyncio
import json
import uuid
import traceback
import time
from typing import Callable, Dict, List, Optional, Any

from openai import AsyncOpenAI
from loguru import logger

from config import config
from database import db
from agent.plan_model import BuildPlan, BuildStep

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

PLANNING_SYSTEM_PROMPT = """你是Travian Legends的策略顧問。你的職責是制定具體可執行的建造計劃，而不是直接操控遊戲。
你的職責：
1. 分析當前遊戲狀態
2. 制定未來2-6小時的建造/訓兵計劃（5-15個步驟）
3. 每個步驟必須包含具體的action和params

Travian遊戲基本原則（按優先級）：
- 糧食生產率必須 > 0（否則村莊人口會下降）
- 倉庫/糧倉不能滿（會停止生產）
- 建造佇列永遠不應空著（有空位就要安排建造任務）
- 資源田等級應均衡提升，不要某一種遠超其他
- 核心建築（Barracks、Stable、Workshop）等級決定兵種上限

可用的action清單與其params：
- upgrade_building: {"building_name": "...", "current_level": ...}
- upgrade_resource_field: {"field_type": "wood_cutters|clay_pits|iron_mines|croplands", "slot_id": ..., "current_level": ...}
- train_troops: {"troop_type": "...", "count": ...}

計劃格式要求：
- steps按執行優先順序排列
- 每步的estimated_cost必須填寫，讓執行層做資源檢查
- reason必須說明為什麼做這步（供人類審查）
- 如果某步依賴前一步完成才能執行，填寫prerequisite_step_id
- valid_for_hours：如果你認為2小時後情況可能有重大變化，設短一點

注意事項：
- 不要規劃超出倉庫容量的步驟
- 不要在糧食生產為負時規劃訓兵
- 訓兵前確認Barracks/Stable已達到要求等級"""

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

    async def request_new_plan(self, state_summary: str, history_summary: str) -> BuildPlan:
        """
        呼叫LLM生成新的BuildPlan。
        """
        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": f"歷史計劃摘要:\n{history_summary}\n\n當前狀態摘要:\n{state_summary}\n\n請根據以上資訊，制定最新的建造計劃。"}
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