# This file is deprecated. Planning is now handled by LLMClient and PlanStore.
from loguru import logger

class Planner:
    async def load_active_goal(self):
        pass
    
    async def set_goal(self, goal, summary):
        pass

    async def complete_goal(self):
        pass

planner = Planner()