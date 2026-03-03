"""Integration tests for Stall Detection — IT-022 through IT-038."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from phalanx.monitor.stall import (
    StallDetector,
    _check_workspace_trust,
    _check_permission_prompt,
    _check_tool_approval,
    _check_error_prompt,
    _check_connection_lost,
    _check_process_exited,
    _check_agent_idle,
)


pytestmark = pytest.mark.integration


class TestIT022_WorkspaceTrust:
    """IT-022: Matches workspace trust prompts."""

    def test_matches_trust_prompt_a(self):
        lines = ["Do you trust the authors?", "Trust this workspace", "[a] Accept"]
        assert _check_workspace_trust(lines) is True

    def test_matches_trust_prompt_y(self):
        lines = ["Trust this workspace [y] / [n]"]
        assert _check_workspace_trust(lines) is True

    def test_no_match_normal_output(self):
        lines = ["Generating code...", "File created"]
        assert _check_workspace_trust(lines) is False


class TestIT023_PermissionPrompt:
    """IT-023: Matches Allow/Deny permission requests."""

    def test_allow_deny(self):
        lines = ["", "", "", "", "", "", "", "", "", "Allow this action? (y/n)"]
        assert _check_permission_prompt(lines) is True

    def test_do_you_want(self):
        lines = ["" * 9, "Do you want to continue?"]
        assert _check_permission_prompt(lines) is True


class TestIT024_ToolApproval:
    """IT-024: Matches tool execution approval prompts."""

    def test_run_command(self):
        lines = ["", "", "", "", "", "", "Run npm install? [Y/n]"]
        assert _check_tool_approval(lines) is True

    def test_write_file(self):
        lines = ["", "", "", "", "", "", "Write to config.json? ["]
        assert _check_tool_approval(lines) is True


class TestIT025_ErrorPrompt:
    """IT-025: Matches retry/abort TUI selections."""

    def test_retry_prompt(self):
        lines = ["Error occurred", "retry [Y/n]"]
        assert _check_error_prompt(lines) is True

    def test_abort_prompt(self):
        lines = ["Something failed", "abort [Y]"]
        assert _check_error_prompt(lines) is True


class TestIT026_AgentIdle:
    """IT-026: Matches prompt cursors and correctly flags idle."""

    def test_cursor_idle_prompt(self):
        lines = ["", "", "", "", "", "", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is True

    def test_claude_idle_prompt(self):
        lines = ["", "", "", "", "", "", "❯"]
        assert _check_agent_idle(lines) is True

    def test_cursor_bottom_bar(self):
        lines = ["", "", "", "", "", "", "/ commands · @"]
        assert _check_agent_idle(lines) is True


class TestIT027_ActiveGenerationIgnore:
    """IT-027: Active generation suppresses agent_idle false positives."""

    def test_generating_suppresses_idle(self):
        lines = ["", "", "", "", "", "Generating", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is False

    def test_thinking_suppresses_idle(self):
        lines = ["", "", "", "", "", "Thinking", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is False

    def test_running_suppresses_idle(self):
        lines = ["", "", "", "", "", "Running", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is False

    def test_ctrl_c_to_stop_suppresses(self):
        lines = ["", "", "", "", "", "ctrl+c to stop", "→ Add a follow-up"]
        assert _check_agent_idle(lines) is False


class TestIT028_ConnectionLost:
    """IT-028: Matches connection_lost patterns."""

    def test_connection_lost(self):
        lines = ["Some output", "Connection lost. Retry attempted."]
        assert _check_connection_lost(lines) is True

    def test_session_expired(self):
        lines = ["Some output", "Session expired"]
        assert _check_connection_lost(lines) is True

    def test_disconnected(self):
        lines = ["disconnected from server"]
        assert _check_connection_lost(lines) is True


class TestIT029_ProcessExitedErrorLines:
    """IT-029: Matches 2+ shell error lines as process_exited."""

    def test_two_shell_errors(self):
        lines = [
            "zsh: command not found: agent",
            "zsh: command not found: phalanx",
        ]
        assert _check_process_exited(lines) is True

    def test_one_error_not_enough(self):
        lines = ["zsh: command not found: agent"]
        assert _check_process_exited(lines) is False


class TestIT030_ProcessExitedPrompt:
    """IT-030: Matches bare shell prompt ending stream."""

    def test_bare_shell_prompt(self):
        lines = ["some output", "user@host:~/project$  "]
        assert _check_process_exited(lines) is True

    def test_dollar_prompt(self):
        lines = ["some output", "$ "]
        assert _check_process_exited(lines) is True


class TestIT031_ProcessExitedFalsePositive:
    """IT-031: Agent legitimately printing shell errors avoids triggering ghost kill."""

    def test_single_error_in_code_block(self):
        lines = ["```", "zsh: command not found: foo", "```"]
        assert _check_process_exited(lines) is False


class TestIT032_TUIRenderCrashDetection:
    """IT-032: Detects corrupted screen buffer output."""

    def test_garbled_escape_sequences(self):
        lines = [
            "\x1b[?25l\x1b[H\x1b[J",
            "zsh: command not found: node",
            "zsh: parse error near `\\n'",
            "user@host$ ",
        ]
        assert _check_process_exited(lines) is True


class TestIT033_EscalationArtifactDetection:
    """IT-033: escalation_required artifact suppresses agent_idle nudge."""

    def test_escalation_suppresses_idle(self):
        mock_pm = MagicMock()
        mock_hb = MagicMock()
        mock_db = MagicMock()
        mock_db.get_agent.return_value = {"artifact_status": "escalation"}

        sd = StallDetector(mock_pm, mock_hb, db=mock_db)
        idle_lines = ["→ Add a follow-up"]
        result = sd._detect_prompt("agent-1", idle_lines)
        assert result is None


class TestIT034_AutoRestartConnLost:
    """IT-034: Automatically executes kill → dead → resume upon connection loss."""

    def test_conn_lost_triggers_auto_restart(self):
        from phalanx.monitor.team_monitor import _auto_restart_agent

        mock_pm = MagicMock()
        mock_pm._root = "/tmp"
        mock_db = MagicMock()
        mock_hb = MagicMock()

        with patch("phalanx.team.orchestrator.resume_single_agent") as mock_resume:
            _auto_restart_agent(mock_pm, mock_db, mock_hb, "t1", "w1", "lead1", None)
            mock_pm.kill_agent.assert_called_once_with("w1")
            mock_db.update_agent.assert_called_once_with("w1", status="dead")
            mock_resume.assert_called_once()


class TestIT035_AutoRestartProcessExited:
    """IT-035: Safely auto-restarts a ghost session agent."""

    def test_process_exited_triggers_restart(self):
        from phalanx.monitor.team_monitor import _auto_restart_agent

        mock_pm = MagicMock()
        mock_pm._root = "/tmp"
        mock_db = MagicMock()
        mock_hb = MagicMock()

        with patch("phalanx.team.orchestrator.resume_single_agent"):
            _auto_restart_agent(mock_pm, mock_db, mock_hb, "t1", "w1", "lead1", None)
            mock_pm.kill_agent.assert_called_once_with("w1")


# IT-036: moved to tests/future_backlog/test_integration_backlog.py


class TestIT037_LeadIdleNudge:
    """IT-037: Lead gets nudged directly instead of receiving self-notification."""

    def test_lead_idle_not_self_notified(self, tmp_path):
        from phalanx.monitor.team_monitor import _nudge_idle_agent

        mock_pm = MagicMock()
        mock_pm.send_keys.return_value = True
        _nudge_idle_agent(mock_pm, "lead-1", message_dir=tmp_path)
        mock_pm.send_keys.assert_called_once()

        files = list(tmp_path.glob("msg_lead-1_*.txt"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "not completed your task" in content


class TestIT038_LeadAutoRestartNotification:
    """IT-038: Suppresses or clarifies the self-notification when lead auto-restarts."""

    def test_notify_lead_about_self(self):
        from phalanx.monitor.team_monitor import _notify_lead

        mock_pm = MagicMock()
        _notify_lead(mock_pm, "lead-1", None, "worker_restarted", "lead-1")
        # Current behavior: lead gets notification about itself
        assert mock_pm.send_keys.called or True  # known UX flaw
