"""Tests for the phalanx server CLI command.

Covers all acceptance criteria:
- phalanx server command exists in the CLI
- --host and --port options are supported with defaults 0.0.0.0 and 8000
- Running phalanx server starts uvicorn serving phalanx.api:app
- Command is documented in the CLI help text
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from phalanx.cli import cli


class TestServerCommandExists:
    """Test that the server command exists and is documented."""

    def test_server_command_exists(self):
        """Test that the server command is registered with the CLI."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "server" in result.output

    def test_server_command_in_help_text(self):
        """Test that the server command appears in the help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "server" in result.output
        # Check for the description
        assert "uvicorn" in result.output or "Start" in result.output

    def test_server_command_help(self):
        """Test that the server command has help documentation."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "phalanx.api:app" in result.output or "uvicorn" in result.output


class TestServerCommandOptions:
    """Test the --host and --port options."""

    def test_server_command_default_host(self):
        """Test that the default host is 0.0.0.0."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--help"])
        assert result.exit_code == 0
        assert "0.0.0.0" in result.output

    def test_server_command_default_port(self):
        """Test that the default port is 8000."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--help"])
        assert result.exit_code == 0
        assert "8000" in result.output

    @patch("uvicorn.run")
    def test_server_command_with_custom_host(self, mock_uvicorn):
        """Test that --host option is passed to uvicorn."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--host", "127.0.0.1"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with the correct host
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "127.0.0.1"

    @patch("uvicorn.run")
    def test_server_command_with_custom_port(self, mock_uvicorn):
        """Test that --port option is passed to uvicorn."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--port", "9000"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with the correct port
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 9000

    @patch("uvicorn.run")
    def test_server_command_with_both_options(self, mock_uvicorn):
        """Test that both --host and --port options work together."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--host", "192.168.1.1", "--port", "5000"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with correct parameters
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "192.168.1.1"
        assert kwargs["port"] == 5000

    @patch("uvicorn.run")
    def test_server_command_with_default_options(self, mock_uvicorn):
        """Test that default host and port are used when not specified."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with default parameters
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8000


class TestServerCommandUvicornIntegration:
    """Test the integration with uvicorn."""

    @patch("uvicorn.run")
    def test_server_starts_uvicorn_with_app(self, mock_uvicorn):
        """Test that uvicorn.run is called with phalanx.api:app."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with the correct app module
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert args[0] == "phalanx.api:app"

    @patch("uvicorn.run")
    def test_server_provides_user_feedback(self, mock_uvicorn):
        """Test that the server command provides user feedback."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--host", "127.0.0.1", "--port", "8080"])
        assert result.exit_code == 0
        # Check for feedback message (should contain host and port info)
        assert (
            "Starting" in result.output
            or "Phalanx" in result.output
            or "127.0.0.1" in result.output
        )

    @patch("uvicorn.run")
    def test_server_command_port_as_integer(self, mock_uvicorn):
        """Test that port is converted to integer correctly."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--port", "3000"])
        assert result.exit_code == 0
        # Verify port is an integer, not a string
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert isinstance(kwargs["port"], int)
        assert kwargs["port"] == 3000


class TestServerEdgeCases:
    """Test edge cases for the server command."""

    @patch("uvicorn.run")
    def test_server_command_invalid_port_type(self, mock_uvicorn):
        """Test that invalid port values are rejected by Click."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--port", "invalid"])
        # Click should reject non-integer port values
        assert result.exit_code != 0

    @patch("uvicorn.run")
    def test_server_command_with_zero_port(self, mock_uvicorn):
        """Test server command with port 0 (let OS choose)."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--port", "0"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with port 0
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 0

    @patch("uvicorn.run")
    def test_server_command_with_high_port_number(self, mock_uvicorn):
        """Test server command with high port number."""
        mock_uvicorn.return_value = None
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--port", "65535"])
        assert result.exit_code == 0
        # Verify uvicorn.run was called with high port number
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 65535
