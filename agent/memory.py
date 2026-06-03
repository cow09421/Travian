# This file is deprecated. History summary is now handled by PlanStore.
from loguru import logger

class MemoryManager:
    async def get_summary(self):
        return ""

memory_manager = MemoryManager()