from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class BuildStep:
    step_id: str
    action: str
    params: Dict[str, Any]
    reason: str
    estimated_cost: Dict[str, int]
    prerequisite_step_id: Optional[str] = None
    status: str = "pending"

    @classmethod
    def from_dict(cls, data: dict) -> 'BuildStep':
        return cls(
            step_id=data.get("step_id", ""),
            action=data.get("action", ""),
            params=data.get("params", {}),
            reason=data.get("reason", ""),
            estimated_cost=data.get("estimated_cost", {}),
            prerequisite_step_id=data.get("prerequisite_step_id"),
            status=data.get("status", "pending")
        )

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "params": self.params,
            "reason": self.reason,
            "estimated_cost": self.estimated_cost,
            "prerequisite_step_id": self.prerequisite_step_id,
            "status": self.status
        }

@dataclass
class BuildPlan:
    plan_id: str
    created_at: float
    strategic_goal: str
    steps: List[BuildStep]
    replan_trigger: str
    valid_for_hours: float

    @classmethod
    def from_dict(cls, data: dict) -> 'BuildPlan':
        steps = [BuildStep.from_dict(step_data) for step_data in data.get("steps", [])]
        return cls(
            plan_id=data.get("plan_id", ""),
            created_at=data.get("created_at", 0.0),
            strategic_goal=data.get("strategic_goal", ""),
            steps=steps,
            replan_trigger=data.get("replan_trigger", ""),
            valid_for_hours=data.get("valid_for_hours", 4.0)
        )

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "strategic_goal": self.strategic_goal,
            "steps": [step.to_dict() for step in self.steps],
            "replan_trigger": self.replan_trigger,
            "valid_for_hours": self.valid_for_hours
        }
