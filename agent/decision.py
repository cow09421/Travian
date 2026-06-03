# This file is deprecated. Autonomous decisions are now handled by RuleEngine and LLMClient planning.
from loguru import logger

class AutonomousBrain:
    async def think_and_act(self, state, context):
        logger.warning("decision.py is deprecated.")
        return []

decision_maker = AutonomousBrain()