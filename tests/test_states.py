"""当前输入区识别、历史排除与采样失败回归。"""

import subprocess
import unittest
from dataclasses import replace
from unittest.mock import patch

from agent_tree.model import AgentKind, PaneState
from agent_tree.states import detect_state
from agent_tree.tmux import Tmux
from agent_tree import discovery, tui
from test_discovery import FakeTmux, make_pane, make_proc


class StateTests(unittest.TestCase):
    def test_codex_working_and_idle(self):
        self.assertEqual(detect_state(AgentKind.CODEX,
            "• Working (17s • esc to interrupt)\n\n› \n\n  GPT-6.1-Sol low · ~/repo")[0], PaneState.WORKING)
        self.assertEqual(detect_state(AgentKind.CODEX,
            "Worked for 38s\n\n› next task\n\n GPT-6.1-Sol low · ~/repo")[0], PaneState.IDLE)
        self.assertEqual(detect_state(AgentKind.CODEX,
            "• Mapping the app (1m 03s)\n\n› \nGPT-6.1-Sol low · ~/repo")[0], PaneState.WORKING)

    def test_old_status_is_not_current(self):
        screen = "• Working (17s • esc to interrupt)\nanswer\nanswer\nanswer\nanswer\n› \nGPT-6.1-Sol low · ~/repo"
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.IDLE)
        self.assertEqual(detect_state(AgentKind.CODEX, "esc to interrupt\nDone")[0], PaneState.UNKNOWN)

    def test_codex_running_status_above_tip_and_blank_lines(self):
        for status in ("• Working (32s • esc to interrupt)", "• Mapping the app (1m 03s)"):
            for gap in ("\n  └ Tip: Use the desktop app.\n\n\n", "\n\n\n\n"):
                with self.subTest(status=status, gap=gap):
                    screen = status + gap + "› Ask Codex to do anything\n\nGPT-6.1-Sol low · ~/repo"
                    self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.WORKING)

    def test_codex_limit_notice_does_not_hide_working_status(self):
        notice = "⚠ 5h limit: 34% left · resets at 18:45 · /status"
        composer = "\n\n› Ask Codex to do anything\n\nGPT-6.1-Sol low · ~/repo"
        screen = "• Working (2m 02s • esc to interrupt)\n\n" + notice + composer
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.WORKING)
        screen = "• Working (2m 02s • esc to interrupt)\nanswer\nanswer\n" + notice + composer
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.IDLE)
        self.assertEqual(detect_state(AgentKind.CODEX, notice + composer)[0], PaneState.IDLE)

    def test_codex_low_limit_notice_does_not_hide_working_status(self):
        notice = "⚠ 5h limit: only 2% left · resets at 18:45 · /status"
        composer = "\n\n› Ask Codex to do anything\n\nGPT-6.1-Sol low · ~/repo\n← for agents · ? for shortcuts"
        screen = "• Working (29s • esc to interrupt)\n\n" + notice + composer
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.WORKING)
        screen = "• Working (29s • esc to interrupt)\nanswer\nanswer\n" + notice + composer
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.IDLE)
        self.assertEqual(detect_state(AgentKind.CODEX, notice + composer)[0], PaneState.IDLE)

    def test_codex_tip_does_not_pull_status_across_answer(self):
        screen = ("• Working (32s • esc to interrupt)\nanswer\nanswer\nanswer\n"
                  "  └ Tip: Use the desktop app.\n\n\n"
                  "› Ask Codex to do anything\n\nGPT-6.1-Sol low · ~/repo")
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.IDLE)

    def test_claude_and_codebuddy_input_and_spinner(self):
        for kind in (AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY):
            with self.subTest(kind=kind):
                self.assertEqual(detect_state(kind, "─────────\n❯ Try something\n─────────\n⏵⏵ auto mode on")[0], PaneState.IDLE)
                self.assertEqual(detect_state(kind, "✻ Thinking… (12s · esc to interrupt)\n─────────\n❯ \n─────────")[0], PaneState.WORKING)

    def test_codebuddy_star_frames_with_tip_and_bounded_composer(self):
        for frame in "✶✸✹✺✷":
            with self.subTest(frame=frame):
                screen = (f"{frame} Calling… (75s · running Bash · ⚒ 21 tokens · Task running for a while)\n"
                          "  └ Tip: Create custom slash commands\n\n"
                          "─────────\n>\n─────────\n⏵⏵ auto mode on\n\n\n\n\n\n")
                self.assertEqual(detect_state(AgentKind.CODEBUDDY, screen)[0], PaneState.WORKING)

    def test_codebuddy_old_spinner_does_not_cross_answer(self):
        screen = ("✹ Calling… (75s · running Bash)\nanswer\nanswer\nanswer\n"
                  "─────────\n> next task\n─────────\n⏵⏵ auto mode on")
        self.assertEqual(detect_state(AgentKind.CODEBUDDY, screen)[0], PaneState.IDLE)
        self.assertEqual(detect_state(AgentKind.CODEBUDDY, "✹ Calling…")[0], PaneState.UNKNOWN)
        self.assertEqual(detect_state(AgentKind.CODEBUDDY, "Calling… (75s)")[0], PaneState.UNKNOWN)

    def test_codebuddy_thinking_streaming_and_tool_execution_are_working(self):
        for phase in ("thinking", "waiting for model", "streaming", "editing", "running Bash"):
            with self.subTest(phase=phase):
                screen = (f"✹ Linking… (162s · {phase} · ↑ 296 tokens)\n\n"
                          "─────────\n>\n─────────\n⏵⏵ auto mode on")
                self.assertEqual(detect_state(AgentKind.CODEBUDDY, screen)[0], PaneState.WORKING)

    def test_dialog_requires_choices_and_controls(self):
        screen = "Would you like to run the following command?\n› 1. Yes\n  2. No\nPress enter to confirm or esc to cancel"
        self.assertEqual(detect_state(AgentKind.CODEX, screen)[0], PaneState.BLOCKED)
        for screen in ("Do you want to proceed?", "1. Yes\n2. No", "Enter to select", "❯ text without borders"):
            self.assertEqual(detect_state(AgentKind.CLAUDE_CODE, screen)[0], PaneState.UNKNOWN)

    def test_pi_only_explicit_status_and_unavailable(self):
        self.assertEqual(detect_state(AgentKind.PI, "Working (esc to interrupt)")[0], PaneState.WORKING)
        for screen in (None, "", "Completed", "Working", "No output"):
            self.assertEqual(detect_state(AgentKind.PI, screen)[0], PaneState.UNKNOWN)
        self.assertEqual(detect_state(AgentKind.SHELL, "Working (esc to interrupt)")[0], PaneState.UNKNOWN)

    def test_discovery_refresh_does_not_preserve_old_status(self):
        tmux = FakeTmux([make_pane(cmd="codex")])
        tmux.screen = lambda pane: "• Working (2s • esc to interrupt)"
        with patch("agent_tree.processes.snapshot", return_value={100: make_proc(100, 0, "codex")}):
            session = discovery.discover(tmux, "sock")[0]
            self.assertEqual(session.state, PaneState.WORKING)
            tmux.screen = lambda pane: None
            self.assertEqual(discovery.discover(tmux, "sock")[0].state, PaneState.UNKNOWN)
            for state, label in ((PaneState.WORKING, "进行中"), (PaneState.BLOCKED, "等待操作"), (PaneState.IDLE, "空闲／本轮结束")):
                self.assertEqual(tui.state_text(replace(session, state=state)), label)

    def test_historical_start_command_does_not_read_shell_screen(self):
        tmux = FakeTmux([make_pane(start="codex")])
        tmux.screen = lambda pane: self.fail("不应读取历史 Agent 的屏幕")
        with patch("agent_tree.processes.snapshot", return_value={100: make_proc(100, 0, "zsh")}):
            self.assertEqual(discovery.discover(tmux, "sock")[0].state, PaneState.UNKNOWN)

    def test_screen_rejects_copy_mode_and_capture_failure(self):
        tmux = Tmux()
        def result(text="", code=0):
            return subprocess.CompletedProcess([], code, text, "")
        with patch.object(tmux, "run", return_value=result("1\n")) as run:
            self.assertIsNone(tmux.screen("%1"))
            self.assertEqual(run.call_count, 1)
        with patch.object(tmux, "run", side_effect=[result("0\n"), result(code=1)]):
            self.assertIsNone(tmux.screen("%1"))
        with patch.object(tmux, "run", side_effect=[result("0\n"), result("screen")]) as run:
            self.assertEqual(tmux.screen("%1"), "screen")
            self.assertEqual(run.call_args.args, ("capture-pane", "-p", "-t", "%1"))
