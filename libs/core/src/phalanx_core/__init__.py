"""
Phalanx Agent OS Core Engine
"""

from .primitives import Soul, Task, Step
from .runner import PhalanxTeamRunner, ExecutionResult
from .state import WorkflowState
from .blocks.base import BaseBlock
from .blocks.implementations import (
    LinearBlock,
    FanOutBlock,
    SynthesizeBlock,
    DebateBlock,
    RetryBlock,
    TeamLeadBlock,
    EngineeringManagerBlock,
    MessageBusBlock,
    RouterBlock,
)
from .workflow import Workflow

__all__ = [
    "Soul",
    "Task",
    "Step",
    "PhalanxTeamRunner",
    "ExecutionResult",
    "WorkflowState",
    "BaseBlock",
    "LinearBlock",
    "FanOutBlock",
    "SynthesizeBlock",
    "DebateBlock",
    "RetryBlock",
    "TeamLeadBlock",
    "EngineeringManagerBlock",
    "MessageBusBlock",
    "RouterBlock",
    "Workflow",
]
