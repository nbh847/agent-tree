"""tmux 访问层的离线单元测试。只验证解析与错误语义，不连接真实 server。"""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from agent_tree.tmux import (
    PANE_FORMAT,
    SEP,
    Tmux,
    TmuxCommandError,
    TmuxUnavailable,
    _parse_pane,
)


def _pane_line(owner: str = "", attached: str = "2") -> str:
    return SEP.join(
        [
            "%3",
            "$0",
            "s0",
            "@0",
            "1",
            "w0",
            "1",
            "1",
            "1",
            "2.1.285",
            "claude",
            "/tmp/proj",
            "1234",
            "/dev/ttys003",
            attached,
            owner,
        ]
    )


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ParseTests(unittest.TestCase):
    def test_parse_pane_maps_all_fields(self):
        pane = _parse_pane(_pane_line())
        self.assertEqual(pane.pane_id, "%3")
        self.assertEqual(pane.session_name, "s0")
        self.assertEqual(pane.window_index, 1)
        self.assertTrue(pane.window_active)
        self.assertTrue(pane.pane_active)
        self.assertEqual(pane.pane_current_command, "2.1.285")
        self.assertEqual(pane.pane_start_command, "claude")
        self.assertEqual(pane.pane_current_path, "/tmp/proj")
        self.assertEqual(pane.pane_pid, 1234)
        self.assertEqual(pane.session_attached, 2)
        self.assertFalse(pane.is_sidebar)

    def test_parse_pane_marks_sidebar_owner(self):
        pane = _parse_pane(_pane_line("inst-9"))
        self.assertTrue(pane.is_sidebar)
        self.assertEqual(pane.sidebar_owner, "inst-9")

    def test_field_count_mismatch_raises(self):
        with self.assertRaises(TmuxCommandError):
            _parse_pane("only|two")

    def test_format_uses_unit_separator_and_owner_option(self):
        self.assertIn(SEP, PANE_FORMAT)
        self.assertIn("#{pane_id}", PANE_FORMAT)
        self.assertIn("#{@agent_tree_sidebar}", PANE_FORMAT)


class SnapshotTests(unittest.TestCase):
    def test_duplicate_linked_window_panes_are_deduped(self):
        # 同一个 window 链接到多个 session 时，同一 pane 会被多次列出
        output = "\n".join([_pane_line(), _pane_line(), ""])
        with mock.patch.object(Tmux, "run", return_value=_completed(output)):
            panes = Tmux().snapshot()
        self.assertEqual(len(panes), 1)
        self.assertEqual(panes[0].pane_id, "%3")

    def test_blank_lines_ignored(self):
        output = "\n\n" + _pane_line() + "\n\n"
        with mock.patch.object(Tmux, "run", return_value=_completed(output)):
            self.assertEqual(len(Tmux().snapshot()), 1)


class ErrorSemanticsTests(unittest.TestCase):
    def test_ensure_server_raises_when_socket_missing(self):
        with mock.patch.object(
            Tmux, "run", return_value=_completed(returncode=1, stderr="no server")
        ):
            with self.assertRaises(TmuxUnavailable):
                Tmux(socket="does-not-exist").ensure_server()

    def test_ensure_server_passes_when_pid_present(self):
        with mock.patch.object(Tmux, "run", return_value=_completed("4321")):
            Tmux().ensure_server()

    def test_non_zero_exit_raises_command_error(self):
        with mock.patch(
            "agent_tree.tmux.subprocess.run",
            return_value=_completed(returncode=2, stderr="boom"),
        ):
            with self.assertRaises(TmuxCommandError):
                Tmux().run("list-panes")

    def test_check_false_returns_completed_process_without_raising(self):
        with mock.patch(
            "agent_tree.tmux.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ):
            completed = Tmux().run("select-pane", "-t", "%9999", check=False)
        self.assertEqual(completed.returncode, 1)

    def test_missing_executable_raises_unavailable(self):
        with mock.patch(
            "agent_tree.tmux.subprocess.run", side_effect=FileNotFoundError("tmux")
        ):
            with self.assertRaises(TmuxUnavailable):
                Tmux(executable="tmux-not-here").run("list-panes")


if __name__ == "__main__":
    unittest.main()