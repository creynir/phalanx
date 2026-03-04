"""
Phalanx Agent OS Core Engine
"""

from .primitives import Soul, Task
from .runner import PhalanxTeamRunner, ExecutionResult
from .state import WorkflowState
from .blocks.base import BaseBlock
from .blocks.implementations import LinearBlock, FanOutBlock, SynthesizeBlock, DebateBlock
from .blueprint import Blueprint

__all__ = [
    "Soul",
    "Task",
    "PhalanxTeamRunner",
    "ExecutionResult",
    "WorkflowState",
    "BaseBlock",
    "LinearBlock",
    "FanOutBlock",
    "SynthesizeBlock",
    "DebateBlock",
    "Blueprint",
]
