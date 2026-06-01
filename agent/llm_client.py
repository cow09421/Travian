import asyncio
import json
import re
import traceback
from typing import Callable, Dict, List, Optional, Any

from openai import AsyncOpenAI
from loguru import logger

from config import config
from database import db


LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "upgrade_building",
            "description": "升級村莊內的建築（如 Main Building、Barracks、Warehouse 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "building_name": {"type": "string", "description": "建築名稱，如 Main Building, Barracks, Granary"},
                    "current_level": {"type": "integer", "description": "當前等級"}
                },
                "required": ["building_name", "current_level"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "upgrade_resource_field",
            "description": "升級資源田（wood/clay/iron/crop）",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_type": {
                        "type": "string",
                        "enum": ["wood_cutters", "clay_pits", "iron_mines", "croplands"],
                        "description": "資源田類型"
                    },
                    "slot_id": {"type": "integer", "description": "田的絕對槽位編號（從遊戲狀態的資源田清單中取得，如 wood_cutters[5] 的 slot_id 為 5，對應 build.php?id=5 的 URL）"},
                    "current_level": {"type": "integer", "description": "當前等級"}
                },
                "required": ["field_type", "slot_id", "current_level"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "train_troops",
            "description": "在兵舍訓練士兵",
            "parameters": {
                "type": "object",
                "properties": {
                    "troop_type": {"type": "string", "description": "兵種名稱（如 Phalanx, Swordsman, Legionnaire）"},
                    "count": {"type": "integer", "description": "訓練數量"}
                },
                "required": ["troop_type", "count"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_attack",
            "description": "攻擊或劫掠指定座標的村莊",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_x": {"type": "integer", "description": "目標 X 座標"},
                    "target_y": {"type": "integer", "description": "目標 Y 座標"},
                    "mission_type": {
                        "type": "string",
                        "enum": ["raid", "attack"],
                        "description": "任務類型：raid=劫掠, attack=攻擊"
                    },
                    "troops": {
                        "type": "object",
                        "description": "派出的兵力，如 {\"Phalanx\": 50}",
                        "additionalProperties": {"type": "integer"}
                    }
                },
                "required": ["target_x", "target_y", "mission_type", "troops"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_scout",
            "description": "偵察指定座標的村莊",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_x": {"type": "integer", "description": "目標 X 座標"},
                    "target_y": {"type": "integer", "description": "目標 Y 座標"}
                },
                "required": ["target_x", "target_y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "等待直到某個時間點再繼續（用於等建造或訓練完成）",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "等待原因"},
                    "wait_until": {"type": "string", "description": "ISO 格式的時間點"}
                },
                "required": ["reason", "wait_until"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete",
            "description": "標記當前目標為完成（當你判斷目標已達成或無法達成時使用）",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "完成或放棄的原因"}
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "collect_hero_resources",
            "description": "將英雄背包中的資源獎勵轉移到村莊倉庫。當英雄有待領取的資源時應立即執行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "執行原因"}
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_hero_on_adventure",
            "description": "派遣英雄去冒險。適合在英雄閒置且有可出征冒險時執行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "adventure_id": {"type": "integer", "description": "冒險任務 ID，從英雄狀態的 hero_adventures 列表中取得"},
                    "reason": {"type": "string", "description": "選擇該冒險的原因"}
                },
                "required": ["adventure_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "allocate_hero_points",
            "description": "分配英雄可用屬性點。有可用點數時優先分配。",
            "parameters": {
                "type": "object",
                "properties": {
                    "attribute": {
                        "type": "string",
                        "enum": ["fighting_strength", "off_bonus", "def_bonus", "resources"],
                        "description": "要強化的屬性。前期建議 resources 增加資源產量，有軍事目標時選 fighting_strength"
                    },
                    "points": {"type": "integer", "description": "分配點數"}
                },
                "required": ["attribute", "points"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "collect_quest_reward",
            "description": "領取已完成的任務獎勵（每日任務或主線任務）。有可領取獎勵時應優先執行，因為這是免費資源。",
            "parameters": {
                "type": "object",
                "properties": {
                    "quest_id": {
                        "type": "string",
                        "description": "特定任務 ID；留空表示一次性領取所有可領取的獎勵"
                    }
                },
                "required": []
            }
        }
    }
]


SYSTEM_PROMPT_TEMPLATE = """你是一個 Travian 遊戲的 AI 自動操作助手。你的目標是幫助玩家發展村莊、建設軍隊、攻擊敵人。

## Travian 基本知識
- Travian 是一款網頁策略遊戲，玩家建設村莊、訓練軍隊、與其他玩家互動
- 每個村莊有 4 種資源：木材(wood)、黏土(clay)、鐵(iron)、糧食(crop)
- 資源田有 18 塊：木材 x4、黏土 x4、鐵 x4、糧食 x6
- 資源產量每小時計算一次，升級資源田可增加產量
- 建造建築和訓練士兵需要資源和時間
- 建造隊列同時只能有一個項目（除非有 Main Building 加成）
- 主要建築物包括：Main Building, Barracks, Stable, Workshop, Smithy, Academy, Market, Granary, Warehouse, Rally Point, Wall, Cranny, Residence/Palace, Embassy, Trade Office, Heros Mansion, Town Hall, Treasury, Hospital
- 羅馬兵種：Legionnaire, Praetorian, Imperian, Equites Legati, Equites Imperatoris, Equites Caesaris
- 高盧兵種：Phalanx, Swordsman, Pathfinder, Theutates Thunder, Druidrider, Haeduan
- 條頓兵種：Clubswinger, Spearman, Axeman, Scout, Paladin, Teutonic Knight
- 攻擊分為 raid(劫掠，只搶資源) 和 attack(攻擊，消滅敵軍和防禦)

## 當前目標
{goal}

## 遊戲當前狀態
{state}

## 最近操作記錄
{recent_actions}

## 長期記憶摘要
{memory_summary}

## 剩餘計畫步驟
{plan_steps}

## 重要規則
1. 你必須立即給出一個可執行的動作，不能回答「等待」除非建造隊列已滿
2. 如果資源不足，選擇升級生產最低等級的資源田
3. 如果建造隊列已滿，使用 wait 動作等待最早完成的任務
4. 每次只做一個最優先的動作
5. 新帳號開局優先順序：資源田升級 > 倉庫/穀倉 > 主建築 > 兵舍
6. 看到 complete 代表當前目標完成，會自動規劃下一個目標
7. upgrade_resource_field 的 slot_id 必須使用當前狀態中「資源田」欄位的方括號數字，例如狀態顯示「wood_cutters[5]:Lv2」，則 slot_id=5，這對應 build.php?id=5 的 URL

請根據當前遊戲狀態，使用工具來執行最合理的下一步動作。考慮資源是否足夠、隊列是否空閒等因素。如果你需要等待，請使用 wait 工具。如果目標已達成，請使用 complete 工具。"""


def _parse_action_from_text(content: str) -> Optional[dict]:
    content_lower = content.lower()

    if any(kw in content_lower for kw in ["upgrade", "升級", "wood", "clay", "iron", "crop", "木材", "黏土", "鐵", "糧食"]):
        slot_match = re.search(r'slot[#\s]*(\d+)|#(\d+)|位置\s*(\d+)', content_lower)
        slot_id = int((slot_match.group(1) or slot_match.group(2) or slot_match.group(3))) if slot_match else 1

        field_type = "wood_cutters"
        if "clay" in content_lower or "黏土" in content_lower:
            field_type = "clay_pits"
        elif "iron" in content_lower or "鐵" in content_lower:
            field_type = "iron_mines"
        elif "crop" in content_lower or "糧" in content_lower:
            field_type = "croplands"

        return {
            "id": "parsed_from_text",
            "name": "upgrade_resource_field",
            "arguments": {"field_type": field_type, "slot_id": slot_id, "current_level": 1}
        }

    if any(kw in content_lower for kw in ["wait", "等待", "隊列已滿", "queue full"]):
        return {
            "id": "parsed_from_text",
            "name": "wait",
            "arguments": {"reason": "建造隊列繁忙", "wait_until": ""}
        }

    return None


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
                   temperature: float = None, stream: bool = False) -> dict:
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

    async def decide(self, system_prompt: str, user_message: str = None) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message or "根據當前遊戲狀態，請立即執行最優先的下一個動作。必須使用工具，不要只回覆文字。"}
        ]

        response = await self.chat(messages, tools=LLM_TOOLS, tool_choice="required")

        choice = response["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "unknown")

        logger.info(f"🔍 LLM finish_reason: {finish_reason}")
        logger.info(f"🔍 LLM content: {str(message.get('content', ''))[:200]}")
        logger.info(f"🔍 LLM tool_calls: {message.get('tool_calls')}")

        result = {
            "content": message.get("content", ""),
            "tool_calls": []
        }

        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                result["tool_calls"].append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "arguments": args
                })
            logger.info(f"✅ LLM 回傳 tool_calls: {[tc['name'] for tc in result['tool_calls']]}")
        else:
            logger.warning(f"⚠️ LLM 沒有回傳 tool_calls！finish_reason={finish_reason}，嘗試從文字解析...")
            content = message.get("content", "")
            parsed = _parse_action_from_text(content)
            if parsed:
                result["tool_calls"] = [parsed]
                logger.info(f"🔧 從文字解析出動作: {parsed['name']}")

        return result

    async def decide_multi(self, system_prompt: str) -> list[dict]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                "根據當前遊戲狀態，選擇最有價值的動作組合。\n"
                "規則：\n"
                "1. 建造動作（upgrade_resource_field 或 upgrade_building）只能選 1 個，選最有價值的那個\n"
                "2. 訓兵（train_troops）可以同時進行，但只在 Barracks/Stable 存在且空閒時才選\n"
                "3. 偵察或攻擊（send_scout/send_attack）有兵力時可同時進行\n"
                "4. 建造隊列忙碌時，不要給任何建造動作\n"
                "請思考：現在最值得做的一件建造/升級是什麼？為什麼？然後輸出工具呼叫。"
            )}
        ]

        response = await self.chat(
            messages,
            tools=LLM_TOOLS,
            tool_choice="required",
        )

        choice = response["choices"][0]
        message = choice["message"]

        actions = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                actions.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "arguments": args,
                })
            logger.info(f"✅ LLM decide_multi 回傳 {len(actions)} 個動作: {[a['name'] for a in actions]}")
        else:
            logger.warning("⚠️ LLM decide_multi 沒有回傳 tool_calls")

        return actions


    async def plan(self, goal_text: str, game_state_summary: str) -> List[dict]:
        prompt = f"""你是一個 Travian 遊戲規劃助手。請根據玩家的目標和當前遊戲狀態，制定一個具體的步驟計畫。

玩家目標：{goal_text}

當前遊戲狀態摘要：
{game_state_summary}

請以 JSON 陣列格式回傳分步計畫，每個步驟包含：
- "step": 步驟編號（整數）
- "action": 動作類型字串（upgrade_building / upgrade_resource / train_troops / send_attack / send_scout / wait）
- "description": 人類可讀的描述
- "details": 詳細參數字典

範例格式：
[
  {{"step": 1, "action": "upgrade_resource", "description": "升級木材田 #3 到 Lv5", "details": {{"field_type": "wood_cutters", "slot_id": 3, "target_level": 5}}}},
  {{"step": 2, "action": "upgrade_building", "description": "升級 Main Building 到 Lv5", "details": {{"building_name": "Main Building", "target_level": 5}}}},
  {{"step": 3, "action": "train_troops", "description": "訓練 50 個 Phalanx", "details": {{"troop_type": "Phalanx", "count": 50}}}}
]

只回傳 JSON，不要有其他文字。"""

        try:
            response = await self.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                max_tokens=4096,
                temperature=0.3,
            )
            content = response["choices"][0]["message"]["content"]
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            plan = json.loads(cleaned)
            if isinstance(plan, list):
                return plan
            return []
        except Exception as e:
            logger.error(f"規劃失敗: {e}")
            return []


llm_client = LLMClient()