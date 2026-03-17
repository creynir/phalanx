"""Phalanx — Multi-Agent Orchestration System."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("phalanx-cli")
except PackageNotFoundError:
    __version__ = "unknown"
