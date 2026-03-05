"""
Phalanx Agent OS Core Engine
"""

from .primitives import Soul, Action, Step
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
    PlaceholderBlock,
)
from .blocks.registry import BlockRegistry, BlockFactory
from .workflow import Workflow
from .yaml import parse_workflow_yaml

__all__ = [
    "Soul",
    "Action",
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
    "PlaceholderBlock",
    "BlockRegistry",
    "BlockFactory",
    "Workflow",
    "parse_workflow_yaml",
]
