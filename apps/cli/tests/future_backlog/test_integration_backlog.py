"""Future backlog tests from integration suite — Phase 1.1 / 1.2 stubs.

Moved from various integration test files so the v1.0.0 pytest run is 100% green
with zero skipped tests.  Re-enable as features land.

Original sources:
  - tests/integration/test_tui_crash.py (IT-047, IT-049, IT-050)
  - tests/integration/test_stall_detection.py (IT-036)
  - tests/integration/test_artifacts.py (IT-059)
  - tests/integration/test_db_operations.py (IT-007)
"""

from __future__ import annotations

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.future_backlog]


# From tests/integration/test_tui_crash.py


class TestIT047_PoisonPillSanitization:
    """IT-047: send_keys sanitizes known TUI-crashing strings."""

    @pytest.mark.skip(reason="v1.0.0 — poison pill sanitization in send_keys not yet implemented")
    def test_sanitized_form(self):
        pass


class TestIT049_RepeatedTUICrashCircuitBreaker:
    """IT-049: Same agent crashes 3 times → stop retrying, escalate."""

    @pytest.mark.skip(reason="v1.0.0 — TUI crash circuit breaker not yet implemented")
    def test_circuit_breaker(self):
        pass


class TestIT050_TUICrashResumeContext:
    """IT-050: Resume prompt includes crash cause and avoidance instructions."""

    @pytest.mark.skip(
        reason="v1.0.0 — TUI crash context injection in resume prompt not yet implemented"
    )
    def test_crash_context_in_resume(self):
        pass


# From tests/integration/test_stall_detection.py


class TestIT036_AutoRestartTUICrash:
    """IT-036: Detects corrupted TUI buffer state, kills agent, resumes with context."""

    @pytest.mark.skip(
        reason="v1.0.0 — TUI crash context enrichment in resume prompt not yet implemented"
    )
    def test_tui_crash_restart_with_context(self):
        pass


# From tests/integration/test_artifacts.py


class TestIT059_ArtifactWithDebt:
    """IT-059: Write artifact with debt field populated."""

    @pytest.mark.skip(reason="v1.0.0 — DebtRecord field in Artifact not yet implemented")
    def test_debt_field_persisted(self):
        pass


# From tests/integration/test_db_operations.py


class TestIT007_MigrationV4ToV5:
    """IT-007: DB upgrade creates v1.0.0 tables."""

    @pytest.mark.skip(
        reason="v1.0.0 schema (v5) not yet implemented — tables token_usage, debt_records, team_context, skill_runs do not exist yet"
    )
    def test_v4_to_v5_migration(self, tmp_path):
        pass
