# This file is deprecated. Reflection and learning are handled during plan step failure/completion in action_dispatcher/loop.
from loguru import logger

class ReflectionEngine:
    async def start(self):
        pass
        
    async def stop(self):
        pass

reflection_engine = ReflectionEngine()