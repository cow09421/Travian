"""
agent/memory.py

Short-term → long-term memory compression management.

Responsibilities:
1. Cache latest summary to avoid repeated DB queries (_summary_cache)
2. Monitor consecutive failures, trigger LLM-based compression (_compress_memory)
3. Expose get_summary() and record_action() only, hiding compression details
"""
from loguru import logger

from database import db
from agent.llm_client import llm_client


class MemoryManager:
    _summary_cache: str = ""

    async def get_summary(self) -> str:
        if self._summary_cache:
            return self._summary_cache
        summary = await db.get_latest_summary()
        if summary:
            self._summary_cache = summary
        return self._summary_cache

    async def record_action(self, action_type: str, params: dict, success: bool, result_text: str):
        if not success:
            await self._record_failure(action_type, params, result_text)

    async def _record_failure(self, action_type: str, params: dict, error: str):
        logger.warning(f"記錄失敗: {action_type} -> {error}")
        failures = await db.get_recent_actions(5)
        failure_count = sum(1 for f in failures if not f.get("success"))
        if failure_count >= 3:
            await self._compress_memory()

    async def _compress_memory(self):
        try:
            recent_actions = await db.get_recent_actions(20)
            actions_text = "\n".join(
                f"{'✅' if a.get('success') else '❌'} {a.get('action_type')}: {a.get('result_text', '')[:80]}"
                for a in recent_actions
            )

            prompt = f"""請根據以下操作記錄，生成一個簡潔的摘要，記錄已經完成的事項和失敗的原因。
這將用於 AI 的長期記憶，幫助它避免重複錯誤。

操作記錄：
{actions_text}

請用 1-3 句話總結。"""

            response = await llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            summary = response["choices"][0]["message"]["content"]
            await db.save_summary(summary)
            self._summary_cache = summary
            logger.info(f"記憶已壓縮: {summary}")
        except Exception as e:
            logger.error(f"壓縮記憶失敗: {e}")

    async def clear_cache(self):
        self._summary_cache = ""


memory_manager = MemoryManager()