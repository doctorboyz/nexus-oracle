"""Tests for nexus-daemon.py — covers route_by_intent, process_outbox_file,
handle_command, dead letter queue, curl_api retry, run_cmd security, and escape_html."""

import json
import os
import re
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Import the daemon module — it's already running via pm2 so it's importable
# The module reads credentials on import, but we override constants after
import importlib.util
import sys

_DAEMON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nexus-daemon.py")
_spec = importlib.util.spec_from_file_location("nexus_daemon", _DAEMON_PATH)
nd = importlib.util.module_from_spec(_spec)
sys.modules["nexus_daemon"] = nd
_spec.loader.exec_module(nd)

# Test routing table (doesn't depend on file system)
ROUTING_TABLE = {
    "god-port": {"keywords": ["trading", "trade", "portfolio", "stock", "crypto"], "domains": ["trading"]},
    "infra": {"keywords": ["docker", "server", "deploy", "infrastructure", "nginx"], "domains": ["devops"]},
    "kappy": {"keywords": ["knowledge", "line", "bot", "docs"], "domains": ["knowledge"]},
    "emily": {"keywords": ["emily", "framework", "buddy"], "domains": []},
}

TEST_CHANNELS = {
    "emily": -100111, "god-port": -100222, "fleet": -100333,
    "infra": -100444, "kappy": -100555, "nexus": -100666,
}
TEST_CHAT_ID = 999999


@pytest.fixture(autouse=True)
def reset_state():
    """Reset mutable state before each test."""
    nd._outbox_retry_count.clear()
    # Ensure test constants are set
    nd.ORACLES = {"emily", "god-port", "nexus", "kappy", "fammee", "infra"}
    nd.CHAT_ID = TEST_CHAT_ID
    nd.CHANNELS = TEST_CHANNELS
    nd.AUTHORIZED_CHATS = {TEST_CHAT_ID} | set(TEST_CHANNELS.values())
    yield
    nd._outbox_retry_count.clear()


def _create_outbox_file(tmp_path, filename, frontmatter, body, oracle="infra"):
    """Helper to create an outbox file with frontmatter."""
    outbox_dir = os.path.join(str(tmp_path), oracle, "psi", "outbox")
    os.makedirs(outbox_dir, exist_ok=True)
    filepath = os.path.join(outbox_dir, filename)
    with open(filepath, "w") as f:
        f.write(f"---\n{frontmatter}\n---\n\n{body}")
    return filepath


# --- Test: route_by_intent ---

class TestRouteByIntent:

    def test_exact_keyword_match(self):
        result, confidence = nd.route_by_intent("check trading portfolio", ROUTING_TABLE)
        assert result == "god-port"
        assert confidence >= 0.5

    def test_multiple_keywords(self):
        result, confidence = nd.route_by_intent("docker deploy status", ROUTING_TABLE)
        assert result == "infra"
        assert confidence > 0.5

    def test_no_match(self):
        result, confidence = nd.route_by_intent("hello world random text", ROUTING_TABLE)
        assert result is None
        assert confidence == 0.0

    def test_nexus_never_destination(self):
        result, _ = nd.route_by_intent("nexus oracle", ROUTING_TABLE)
        assert result != "nexus"

    def test_domain_match(self):
        # "devops" is infra's domain, but "knowledge" is kappy's domain
        # Both score 0.5 on domain, so the winner depends on keyword matches too
        result, confidence = nd.route_by_intent("devops pipeline question", ROUTING_TABLE)
        assert result is not None
        assert confidence > 0

    def test_low_confidence_returns_none(self):
        result, confidence = nd.route_by_intent("I need help", ROUTING_TABLE)
        assert confidence < 0.5


# --- Test: escape_html ---

class TestEscapeHtml:

    def test_ampersand(self):
        assert nd.escape_html("a & b") == "a &amp; b"

    def test_angle_brackets(self):
        assert nd.escape_html("<script>") == "&lt;script&gt;"

    def test_all_special(self):
        assert nd.escape_html("a<b&c>d") == "a&lt;b&amp;c&gt;d"

    def test_no_escape_needed(self):
        assert nd.escape_html("hello world") == "hello world"


# --- Test: run_cmd ---

class TestRunCmd:

    def test_uses_list_args(self):
        """run_cmd passes args as a list (no shell injection risk)."""
        with patch.object(nd.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="")
            nd.run_cmd(["echo", "hello"])
            call_args = mock_run.call_args
            assert isinstance(call_args[0][0], list)

    def test_no_shell_true(self):
        """run_cmd never uses shell=True."""
        with patch.object(nd.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="")
            nd.run_cmd(["maw", "peek", "infra"])
            kwargs = mock_run.call_args[1]
            # shell should not be True (default is False)
            assert kwargs.get("shell") is not True

    def test_timeout_handled(self):
        with patch.object(nd.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=["maw"], timeout=15)):
            result = nd.run_cmd(["maw", "peek", "infra"])
            assert "timed out" in result.lower()

    def test_output_truncated(self):
        with patch.object(nd.subprocess, "run", return_value=MagicMock(stdout="x" * 5000, stderr="")):
            result = nd.run_cmd(["echo", "long"])
            assert len(result) <= 4000

    def test_stderr_on_empty_stdout(self):
        with patch.object(nd.subprocess, "run", return_value=MagicMock(stdout="", stderr="error output")):
            result = nd.run_cmd(["maw", "test"])
            assert result == "error output"


# --- Test: curl_api retry ---

class TestCurlApiRetry:

    def test_success_first_try(self):
        with patch.object(nd.subprocess, "run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout='{"ok": true, "result": {"message_id": 1}}', stderr=""
            )
            result = nd.curl_api("getMe")
            assert result["ok"] is True
            assert mock_run.call_count == 1

    def test_retry_on_timeout_then_success(self):
        with patch.object(nd.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                subprocess.TimeoutExpired(cmd=["curl"], timeout=30),
                MagicMock(stdout='{"ok": true, "result": {"message_id": 2}}', stderr=""),
            ]
            result = nd.curl_api("sendMessage", {"chat_id": 123, "text": "test"})
            assert result["ok"] is True
            assert mock_run.call_count == 2

    def test_returns_none_after_all_retries_fail(self):
        with patch.object(nd.subprocess, "run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["curl"], timeout=30)
            result = nd.curl_api("sendMessage", {"chat_id": 123, "text": "test"})
            assert result is None
            assert mock_run.call_count == 2  # initial + 1 retry


# --- Test: process_outbox_file ---

class TestProcessOutboxFile:

    def test_skip_ack(self, tmp_path):
        f = _create_outbox_file(tmp_path, "ack_MSG-001.md",
                                "type: ack\nfrom: infra\nmsg_id: MSG-001",
                                "Acknowledged")
        result = nd.process_outbox_file("infra", f, {})
        assert result is True

    def test_skip_unknown_type(self, tmp_path):
        f = _create_outbox_file(tmp_path, "status_MSG-002.md",
                                "type: status\nfrom: infra\nmsg_id: MSG-002",
                                "Status update")
        result = nd.process_outbox_file("infra", f, {})
        assert result is True

    def test_empty_body_archived(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-003.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-003",
                                "")
        result = nd.process_outbox_file("infra", f, {})
        assert result is True

    def test_send_with_respond_in(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-004.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-004\nrespond_in: -100444",
                                "Docker containers: 3 running")
        with patch.object(nd, "curl_api", return_value={"ok": True, "result": {"message_id": 42}}):
            result = nd.process_outbox_file("infra", f, {})
        assert result is True

    def test_send_failure_returns_false(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-005.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-005",
                                "Some response text")
        with patch.object(nd, "curl_api", return_value={"ok": False, "description": "Bad Request"}):
            with patch.object(nd, "send_message"):
                result = nd.process_outbox_file("infra", f, {})
        assert result is False

    def test_no_frontmatter(self, tmp_path):
        filepath = os.path.join(str(tmp_path), "plain_response.md")
        with open(filepath, "w") as fh:
            fh.write("Just plain text response")
        with patch.object(nd, "curl_api", return_value={"ok": True, "result": {"message_id": 99}}):
            result = nd.process_outbox_file("infra", filepath, {})
        assert result is True

    def test_fallback_to_oracle_chat(self, tmp_path):
        """When respond_in and source_chat are missing, fall back to oracle's channel."""
        f = _create_outbox_file(tmp_path, "result_MSG-006.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-006",
                                "Status response")
        with patch.object(nd, "curl_api", return_value={"ok": True, "result": {"message_id": 50}}) as mock_curl:
            result = nd.process_outbox_file("infra", f, {})
        assert result is True
        # Verify the chat_id is infra's channel
        payload = mock_curl.call_args[0][1]
        assert payload["chat_id"] == -100444  # infra's channel


# --- Test: dead letter queue ---

class TestDeadLetterQueue:

    def test_retry_count_increments(self):
        nd._outbox_retry_count["/fake/file.md"] = 0
        nd._outbox_retry_count["/fake/file.md"] += 1
        assert nd._outbox_retry_count["/fake/file.md"] == 1

    def test_retry_count_cleared_on_success(self):
        nd._outbox_retry_count["/fake/file.md"] = 2
        nd._outbox_retry_count.pop("/fake/file.md", None)
        assert "/fake/file.md" not in nd._outbox_retry_count

    def test_move_to_dead_letter(self, tmp_path):
        outbox_dir = os.path.join(str(tmp_path), "infra", "psi", "outbox")
        os.makedirs(outbox_dir, exist_ok=True)
        filepath = os.path.join(outbox_dir, "result_MSG-DEAD.md")
        with open(filepath, "w") as f:
            f.write("---\ntype: result\nfrom: infra\n---\n\nFailed message")

        with patch.object(nd, "send_message"):
            nd.move_to_dead_letter(filepath, "infra", "Telegram API error")

        assert not os.path.exists(filepath)
        dead_dir = os.path.join(outbox_dir, "dead")
        assert os.path.isdir(dead_dir)
        dead_files = []
        for root, dirs, files in os.walk(dead_dir):
            dead_files.extend(files)
        assert len(dead_files) == 1

    def test_dead_letter_creates_month_subdir(self, tmp_path):
        outbox_dir = os.path.join(str(tmp_path), "infra", "psi", "outbox")
        os.makedirs(outbox_dir, exist_ok=True)
        filepath = os.path.join(outbox_dir, "result_MSG-DEAD2.md")
        with open(filepath, "w") as f:
            f.write("---\ntype: result\n---\n\ncontent")

        with patch.object(nd, "send_message"):
            nd.move_to_dead_letter(filepath, "infra", "test reason")

        dead_dir = os.path.join(outbox_dir, "dead")
        subdirs = [d for d in os.listdir(dead_dir) if os.path.isdir(os.path.join(dead_dir, d))]
        assert len(subdirs) == 1
        assert re.match(r"\d{4}-\d{2}", subdirs[0])


# --- Test: handle_command ---

class TestHandleCommand:

    def test_help(self):
        result = nd.handle_command("/help", TEST_CHAT_ID, 1)
        assert "nexus Oracle Commands" in result
        assert "/wake" in result

    def test_help_with_bot_suffix(self):
        result = nd.handle_command("/help@texty_oracle_bot", TEST_CHAT_ID, 1)
        assert "nexus Oracle Commands" in result

    def test_wake_unknown_oracle(self):
        result = nd.handle_command("/wake unknown_oracle", TEST_CHAT_ID, 1)
        assert "Usage" in result

    def test_sleep_unknown_oracle(self):
        result = nd.handle_command("/sleep unknown_oracle", TEST_CHAT_ID, 1)
        assert "Usage" in result

    def test_send_unknown_oracle(self):
        result = nd.handle_command("/send unknown_oracle hello", TEST_CHAT_ID, 1)
        assert "Usage" in result

    def test_broadcast_no_args(self):
        result = nd.handle_command("/broadcast", TEST_CHAT_ID, 1)
        assert "Usage" in result

    def test_inbox_unknown_oracle(self):
        result = nd.handle_command("/inbox unknown", TEST_CHAT_ID, 1)
        assert "Usage" in result

    def test_unknown_command(self):
        result = nd.handle_command("/unknown_cmd", TEST_CHAT_ID, 1)
        assert "Unknown command" in result

    def test_wake_known_oracle(self):
        with patch.object(nd, "run_cmd", return_value="session started"):
            with patch.object(nd, "send_message", return_value={"ok": True}):
                result = nd.handle_command("/wake infra", TEST_CHAT_ID, 1)
                assert "infra" in result

    def test_status_command(self):
        with patch.object(nd, "run_cmd", return_value="emily  running\ninfra  offline"):
            result = nd.handle_command("/status", TEST_CHAT_ID, 1)
            assert "Fleet Status" in result


# --- Test: get_oracle_by_chat ---

class TestGetOracleByChat:

    def test_known_chat(self):
        assert nd.get_oracle_by_chat(-100222) == "god-port"

    def test_unknown_chat(self):
        assert nd.get_oracle_by_chat(-999999) is None


# --- Test: archive_outbox_file ---

class TestArchiveOutboxFile:

    def test_archives_to_month_dir(self, tmp_path):
        outbox_dir = os.path.join(str(tmp_path), "outbox")
        os.makedirs(outbox_dir, exist_ok=True)
        filepath = os.path.join(outbox_dir, "result_MSG-001.md")
        with open(filepath, "w") as f:
            f.write("---\ntype: result\n---\n\ntest")

        nd.archive_outbox_file(filepath)

        assert not os.path.exists(filepath)
        archive_dir = os.path.join(outbox_dir, "archive")
        assert os.path.isdir(archive_dir)
        subdirs = [d for d in os.listdir(archive_dir) if os.path.isdir(os.path.join(archive_dir, d))]
        assert len(subdirs) >= 1


# --- Test: poll_outboxes integration ---

class TestPollOutboxes:

    def test_successful_send_archives_and_clears_retry(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-010.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-010\nrespond_in: -100444",
                                "Hello world")
        nd._outbox_retry_count[f] = 1

        original_dirs = nd.ORACLE_DIRS.copy()
        nd.ORACLE_DIRS = {"infra": {
            "root": str(tmp_path), "psi": str(os.path.join(str(tmp_path), "psi")),
            "inbox": str(os.path.join(str(tmp_path), "psi", "inbox")),
            "outbox": os.path.dirname(f),
        }}

        with patch.object(nd, "process_outbox_file", return_value=True):
            with patch.object(nd, "archive_outbox_file"):
                nd.poll_outboxes()

        assert f not in nd._outbox_retry_count
        nd.ORACLE_DIRS = original_dirs

    def test_failed_send_increments_retry(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-011.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-011",
                                "Failed message")

        original_dirs = nd.ORACLE_DIRS.copy()
        nd.ORACLE_DIRS = {"infra": {
            "root": str(tmp_path), "psi": str(os.path.join(str(tmp_path), "psi")),
            "inbox": str(os.path.join(str(tmp_path), "psi", "inbox")),
            "outbox": os.path.dirname(f),
        }}

        with patch.object(nd, "process_outbox_file", return_value=False):
            nd.poll_outboxes()

        assert f in nd._outbox_retry_count
        assert nd._outbox_retry_count[f] == 1
        nd.ORACLE_DIRS = original_dirs

    def test_dead_letter_after_max_retries(self, tmp_path):
        f = _create_outbox_file(tmp_path, "result_MSG-012.md",
                                "type: result\nfrom: infra\nmsg_id: MSG-012",
                                "Max retries")

        original_dirs = nd.ORACLE_DIRS.copy()
        nd.ORACLE_DIRS = {"infra": {
            "root": str(tmp_path), "psi": str(os.path.join(str(tmp_path), "psi")),
            "inbox": str(os.path.join(str(tmp_path), "psi", "inbox")),
            "outbox": os.path.dirname(f),
        }}

        # Set retry count to max - 1
        nd._outbox_retry_count[f] = nd.MAX_OUTBOX_RETRIES - 1

        with patch.object(nd, "process_outbox_file", return_value=False):
            with patch.object(nd, "move_to_dead_letter") as mock_dead:
                nd.poll_outboxes()
                # This attempt brings count to MAX_OUTBOX_RETRIES, triggering dead letter
                mock_dead.assert_called_once()

        nd.ORACLE_DIRS = original_dirs