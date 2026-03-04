"""
Phalanx Agent OS Core Engine
"""

from .primitives import Soul, Task
from .runner import PhalanxTeamRunner, ExecutionResult

__all__ = ["Soul", "Task", "PhalanxTeamRunner", "ExecutionResult"]
