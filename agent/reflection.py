import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from agent.knowledge_base import knowledge_base
from agent.llm_client import llm_client
from database import db
from config import config

REFLECTION_PROMPT = """你是一個 Travian 遊戲 AI 玩家的內部反思系統。

## 最近的行動記錄
{recent_actions}

## 當前村莊狀態
{state_summary}

請用 2-3 句話寫下：
1. 這段時間做了什麼，效果如何
2. 發現了什麼有趣的遊戲規律或機會
3. 接下來想嘗試什麼（不要只說「繼續升資源田」）

格式：直接寫，不要標題，不要條列，就像玩家在記日記。"""

MAX_NOTES = 15


class ReflectionEngine:

    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._think_count = 0
        self._last_search_time: Optional[datetime] = None

    async def start(self):
        self.running = True
        self._task = asyncio.create_task(self._reflection_loop())
        logger.info("🧠 持續反思引擎已啟動")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _reflection_loop(self):
        while self.running:
            try:
                self._think_count += 1
                await self._reflect()

                now = datetime.now(timezone.utc)
                if (not self._last_search_time or
                    (now - self._last_search_time).total_seconds() > 600):
                    await knowledge_base.search_and_update()
                    self._last_search_time = now

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"反思引擎錯誤: {e}")
                await asyncio.sleep(60)

    async def _reflect(self):
        try:
            recent_actions = await db.get_recent_actions(30)
            if not recent_actions:
                return

            state_text = ""
            try:
                latest = await db.get_latest_state()
                if latest:
                    res = latest.get("resources", {})
                    bld = list(latest.get("buildings", {}).keys())
                    state_text = f"資源: wood={res.get('wood',0)} clay={res.get('clay',0)} iron={res.get('iron',0)} crop={res.get('crop',0)} | 建築: {bld[:6]}"
            except Exception:
                pass

            actions_text = []
            for a in recent_actions[:20]:
                status = "OK" if a.get("success") else "FAIL"
                actions_text.append(f"[{status}] {a.get('action_type')}: {a.get('result_text', '')[:60]}")
            action_str = "\n".join(actions_text)

            prompt = REFLECTION_PROMPT.format(
                recent_actions=action_str[:2000],
                state_summary=state_text[:500] or "（無）"
            )

            insight = ""
            try:
                response = await llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.4,
                )
                insight = response["choices"][0]["message"]["content"].strip()
                if insight:
                    logger.info(f"🧠 反思洞察: {insight[:100]}...")
            except Exception as e:
                logger.warning(f"LLM 反思呼叫失敗: {e}")
                insight = None

            if not insight:
                successes = [a for a in recent_actions if a.get("success")]
                failures = [a for a in recent_actions if not a.get("success")]
                action_types = [a.get("action_type", "") for a in recent_actions[:15]]
                resource_field_count = sum(1 for a in recent_actions if a.get("action_type") == "upgrade_resource_field")
                build_count = sum(1 for a in recent_actions if a.get("action_type") == "upgrade_building")

                fallback_parts = []
                if successes:
                    fallback_parts.append(f"成功率 {len(successes)}/{len(recent_actions)}")
                if resource_field_count >= 8 and build_count == 0:
                    fallback_parts.append("一直升田，該考慮建築/訓兵")
                if failures:
                    bad = max(set(a.get("action_type", "") for a in failures), key=lambda x: sum(1 for f in failures if f.get("action_type") == x))
                    count = sum(1 for f in failures if f.get("action_type") == bad)
                    fallback_parts.append(f"{bad} 失敗 {count} 次")
                insight = "；".join(fallback_parts) if fallback_parts else f"完成 {len(recent_actions)} 個動作"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n\n## 反思日記 {timestamp}\n{insight}"

            notes_file: Path = knowledge_base.learned_dir / "strategy_notes.md"

            try:
                existing = notes_file.read_text(encoding="utf-8").strip() if notes_file.exists() else ""

                if existing:
                    existing_entries = existing.split("\n\n## ")
                    if len(existing_entries) > MAX_NOTES:
                        existing = "\n\n## ".join(existing_entries[-MAX_NOTES:])
                    last_entry = existing_entries[-1].strip() if existing_entries else ""
                    if last_entry and _similarity(last_entry[:100], insight[:100]) > 0.7:
                        logger.debug("跳過寫入：與最近條目過於相似")
                        return

                combined = existing + entry
                if combined:
                    notes_file.write_text(combined, encoding="utf-8")
                    logger.debug(f"📝 策略筆記已更新 ({len(insight)} 字)")
            except Exception as e:
                logger.debug(f"寫入策略筆記失敗: {e}")

            logger.debug(f"🧠 反思#{self._think_count} 完成")

        except Exception as e:
            logger.debug(f"反思過程出錯: {e}")


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a_words = set(a.lower().split()[:20])
    b_words = set(b.lower().split()[:20])
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    return len(intersection) / max(len(a_words | b_words), 1)


reflection_engine = ReflectionEngine()