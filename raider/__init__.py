from typing import Protocol, Any


class RaidExecutor(Protocol):
    async def send_raid(self, target_x: int, target_y: int, troops: dict) -> dict:
        ...


class StateProvider(Protocol):
    async def get_game_state(self) -> dict:
        ...