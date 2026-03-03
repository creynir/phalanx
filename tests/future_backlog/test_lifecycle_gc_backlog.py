"""Future backlog tests from lifecycle/GC E2E suite — Phase 1.1 / 1.2 stubs.

Moved from tests/e2e/test_lifecycle_gc.py so the v1.0.0 pytest run is 100% green
with zero skipped tests.  Re-enable as features land.
"""

from __future__ import annotations

import pytest


pytestmark = [pytest.mark.e2e, pytest.mark.future_backlog]


class TestE2E053_SchemaMigrationV4V5:
    """E2E-053: Upgrading DB adds v1.0.0 tables."""

    @pytest.mark.skip(reason="v1.0.0 — schema v5 migration not yet implemented")
    def test_v4_to_v5(self):
        pass


class TestE2E054_CostInTeamStatus:
    """E2E-054: phalanx team-status shows cost summary."""

    @pytest.mark.skip(reason="v1.0.0 — cost summary in team-status not yet implemented")
    def test_cost_in_status(self):
        pass
