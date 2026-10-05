"""discovery 模块的离线单元测试。"""

from __future__ import annotations

import unittest
from unittest import mock

from agent_tree import discovery, processes
from agent_tree.model import AgentKind, PaneState
from agent_tree.tmux import PaneInfo


def make_pane(
    pane_id: str = "%0",
    *,
    cmd: str = "zsh",
    start: str = "",
    path: str = "/tmp/proj",
    pid: int = 100,
    owner: str = "",
    session: str = "s0",
    window_index: int = 1,
    pane_index: int = 1,
    active: bool = True,
    attached: int = 0,
) -> PaneInfo:
    return PaneInfo(
        pane_id=pane_id,
        session_id="$0",
        session_name=session,
        window_id="@0",
        window_index=window_index,
        window_name="w",
        pane_index=pane_index,
        window_active=True,
        pane_active=active,
        pane_current_command=cmd,
        pane_start_command=start,
        pane_current_path=path,
        pane_pid=pid,
        pane_tty="/dev/ttys000",
        session_attached=attached,
        sidebar_owner=owner,
    )


def make_proc(pid: int, ppid: int, *argv: str) -> processes.ProcInfo:
    return processes.ProcInfo(pid=pid, ppid=ppid, argv=tuple(argv))


class FakeTmux:
    """只实现 discovery 需要的 snapshot 接口。"""

    def __init__(self, panes: list[PaneInfo]) -> None:
        self._panes = panes

    def snapshot(self) -> tuple[PaneInfo, ...]:
        return tuple(self._panes)


def run_discover(
    panes: list[PaneInfo],
    procs: dict[int, processes.ProcInfo],
    *,
    only_attached: bool = False,
    keep_sessions: set[str] | None = None,
):
    with mock.patch.object(processes, "snapshot", return_value=procs):
        return discovery.discover(
            FakeTmux(panes),
            host_key="/tmp/sock",
            generation=7,
            only_attached=only_attached,
            keep_sessions=keep_sessions,
        )


class IdentifyTests(unittest.TestCase):
    def test_process_executable_is_strongest_evidence(self):
        tree = [make_proc(100, 1, "/Users/mac/.local/bin/claude")]
        signature, confidence, _ = discovery.identify("", tree)
        self.assertIsNotNone(signature)
        self.assertIs(signature.kind, AgentKind.CLAUDE_CODE)
        self.assertEqual(confidence, discovery.CONFIDENCE_HIGH)

    def test_wrapped_launch_via_path_argument(self):
        tree = [make_proc(100, 1, "node", "/opt/npm/lib/claude")]
        signature, confidence, _ = discovery.identify("", tree)
        self.assertIsNotNone(signature)
        self.assertIs(signature.kind, AgentKind.CLAUDE_CODE)
        self.assertEqual(confidence, discovery.CONFIDENCE_MEDIUM)

    def test_start_command_skips_env_assignment(self):
        signature, confidence, _ = discovery.identify("PATH=/x:$PATH codex", [])
        self.assertIsNotNone(signature)
        self.assertIs(signature.kind, AgentKind.CODEX)
        self.assertEqual(confidence, discovery.CONFIDENCE_MEDIUM)

    def test_agent_name_as_argument_not_matched(self):
        tree = [make_proc(100, 1, "grep", "codex", "file")]
        signature, _, _ = discovery.identify("grep codex file", tree)
        self.assertIsNone(signature)

    def test_relative_token_without_slash_not_matched(self):
        tree = [make_proc(100, 1, "echo", "codex")]
        signature, _, _ = discovery.identify("", tree)
        self.assertIsNone(signature)

    def test_start_command_name_normalises_path_and_login_dash(self):
        self.assertEqual(discovery.start_command_name("/usr/local/bin/claude --resume"), "claude")
        self.assertEqual(discovery.start_command_name("FOO=1 BAR=2 codex"), "codex")
        self.assertEqual(discovery.start_command_name(""), "")


class DiscoverTests(unittest.TestCase):
    def test_plain_shell_listed_as_shell_kind(self):
        panes = [make_pane("%0", cmd="zsh", pid=100)]
        procs = {100: make_proc(100, 1, "-zsh")}
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.SHELL)
        self.assertEqual(sessions[0].marker, discovery.SHELL_MARKER)
        self.assertEqual(sessions[0].display_name, discovery.SHELL_DISPLAY_NAME)

    def test_shell_fallback_when_process_snapshot_unavailable(self):
        panes = [make_pane("%0", cmd="zsh", pid=100)]
        sessions = run_discover(panes, {})
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.SHELL)

    def test_shell_with_transient_child_not_misread_as_program(self):
        # shell 启动期会短暂产生非 shell 子进程（如补全初始化），不应被误判为程序
        panes = [make_pane("%0", cmd="zsh", pid=100)]
        procs = {
            100: make_proc(100, 1, "-zsh"),
            101: make_proc(101, 100, "/bin/mv", "a", "b"),
        }
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.SHELL)

    def test_shell_running_foreground_program_is_unknown(self):
        panes = [make_pane("%0", cmd="vim", pid=100)]
        procs = {
            100: make_proc(100, 1, "-zsh"),
            101: make_proc(101, 100, "vim", "notes.txt"),
        }
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.UNKNOWN)

    def test_shell_fallback_with_login_shell_subtree(self):
        # pane 名称不可信时，子树全为 shell 也视为普通 shell
        panes = [make_pane("%0", cmd="", pid=100)]
        procs = {100: make_proc(100, 1, "-zsh")}
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.SHELL)

    def test_sidebar_owned_pane_excluded(self):
        panes = [make_pane("%0", cmd="python3", pid=100, owner="inst-1")]
        procs = {100: make_proc(100, 1, "/usr/bin/python3", "-m", "agent_tree")}
        self.assertEqual(run_discover(panes, procs), [])

    def test_only_attached_keeps_live_detached_agents(self):
        panes = [
            make_pane("%0", start="claude", pid=100, attached=1),
            make_pane("%1", start="codex", pid=200, attached=0),
        ]
        procs = {
            100: make_proc(100, 1, "/x/claude"),
            200: make_proc(200, 1, "/x/codex"),
        }
        self.assertEqual(len(run_discover(panes, procs)), 2)
        kept = run_discover(panes, procs, only_attached=True)
        self.assertEqual([session.backend_target for session in kept], ["%0", "%1"])

    def test_detached_agents_visible_after_restart_with_empty_keep(self):
        panes = [make_pane("%0", pid=100), make_pane("%1", pid=200)]
        procs = {100: make_proc(100, 1, "/x/codex"),
                 200: make_proc(200, 1, "node", "/x/claude")}
        for _ in range(2):
            keep = set()
            sessions = run_discover(panes, procs, only_attached=True, keep_sessions=keep)
            self.assertEqual([s.backend_target for s in sessions], ["%0", "%1"])
            self.assertEqual(keep, set())

    def test_detached_shell_and_stale_start_command_stay_hidden(self):
        panes = [make_pane("%0", pid=100),
                 make_pane("%1", start="codex", pid=200),
                 make_pane("%2", pid=300),
                 make_pane("%3", start="claude", pid=400)]
        procs = {100: make_proc(100, 1, "zsh"),
                 200: make_proc(200, 1, "zsh"),
                 300: make_proc(300, 1, "bash")}
        self.assertEqual(run_discover(panes, procs, only_attached=True), [])
        with mock.patch.object(processes, "snapshot", return_value={}):
            self.assertEqual(discovery.discover(FakeTmux(panes), "/sock", only_attached=True), [])

    def test_detached_agent_exit_to_shell_removes_exception(self):
        pane = make_pane("%0", start="", pid=100)
        procs = {100: make_proc(100, 1, "zsh"), 101: make_proc(101, 100, "/x/codex")}
        self.assertEqual(len(run_discover([pane], procs, only_attached=True)), 1)
        procs.pop(101)
        self.assertEqual(run_discover([pane], procs, only_attached=True), [])

    def test_detached_services_survive_restart_and_disappear_when_stopped(self):
        pane = make_pane("%0", cmd="bash", pid=100)
        procs = {100: make_proc(100, 1, "zsh"),
                 101: make_proc(101, 100, "bash"),
                 102: make_proc(102, 101, "Python"),
                 103: make_proc(103, 101, "node")}
        for _ in range(2):
            sessions = run_discover([pane], procs, only_attached=True, keep_sessions=set())
            self.assertEqual([s.backend_target for s in sessions], ["%0"])
            self.assertIs(sessions[0].agent, AgentKind.SHELL)
        pane = make_pane("%0", cmd="zsh", pid=100)
        # 后台服务也应保留，即使前台已回到 shell。
        self.assertEqual(len(run_discover([pane], procs, only_attached=True)), 1)
        self.assertEqual(run_discover([pane], {100: procs[100]}, only_attached=True), [])

    def test_keep_sessions_records_attached_and_retains_after_detach(self):
        # 第一次：a 附着、b 断开 → 存活 Agent 均可见，但只有 a 记入 keep_sessions。
        attached = [
            make_pane("%0", start="claude", pid=100, session="a", attached=1),
            make_pane("%1", start="codex", pid=200, session="b", attached=0),
        ]
        procs = {
            100: make_proc(100, 1, "/x/claude"),
            200: make_proc(200, 1, "/x/codex"),
        }
        keep: set[str] = set()
        first = run_discover(attached, procs, only_attached=True, keep_sessions=keep)
        self.assertEqual([session.session_name for session in first], ["a", "b"])
        self.assertEqual(keep, {"a"})

        # 导航后 a 变成 detached（switch-client），但它已在 keep 中，仍应显示
        detached = [
            make_pane("%0", start="claude", pid=100, session="a", attached=0),
            make_pane("%1", start="codex", pid=200, session="b", attached=1),
        ]
        second = run_discover(detached, procs, only_attached=True, keep_sessions=keep)
        self.assertEqual(sorted(session.session_name for session in second), ["a", "b"])

    def test_same_directory_different_agents_kept_separately(self):
        panes = [
            make_pane("%0", start="claude", pid=100, path="/tmp/proj"),
            make_pane("%1", start="codex", pid=200, path="/tmp/proj"),
        ]
        procs = {
            100: make_proc(100, 1, "/Users/mac/.local/bin/claude"),
            200: make_proc(200, 1, "/Users/mac/.local/bin/codex"),
        }
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(
            {session.agent for session in sessions},
            {AgentKind.CLAUDE_CODE, AgentKind.CODEX},
        )

    def test_same_agent_multiple_panes_not_merged(self):
        panes = [
            make_pane("%0", start="claude", pid=100),
            make_pane("%1", start="claude", pid=200),
        ]
        procs = {
            100: make_proc(100, 1, "/x/claude"),
            200: make_proc(200, 1, "/x/claude"),
        }
        self.assertEqual(len(run_discover(panes, procs)), 2)

    def test_unknown_program_kept_as_unknown(self):
        panes = [make_pane("%0", cmd="node", pid=100)]
        procs = {100: make_proc(100, 1, "node", "server.js")}
        sessions = run_discover(panes, procs)
        self.assertEqual(len(sessions), 1)
        self.assertIs(sessions[0].agent, AgentKind.UNKNOWN)
        self.assertEqual(sessions[0].marker, "?")

    def test_agent_exit_back_to_shell_keeps_shell_entry(self):
        # 交互式 shell 中手动启动 Agent：退出后同一 pane 回到普通 shell 条目
        panes = [make_pane("%0", cmd="zsh", start="", pid=100)]
        running = {
            100: make_proc(100, 1, "-zsh"),
            101: make_proc(101, 100, "/Users/mac/.local/bin/claude"),
        }
        exited = {100: make_proc(100, 1, "-zsh")}
        running_sessions = run_discover(panes, running)
        self.assertEqual(len(running_sessions), 1)
        self.assertIs(running_sessions[0].agent, AgentKind.CLAUDE_CODE)
        exited_sessions = run_discover(panes, exited)
        self.assertEqual(len(exited_sessions), 1)
        self.assertIs(exited_sessions[0].agent, AgentKind.SHELL)

    def test_new_and_closed_panes_reflected(self):
        procs = {
            100: make_proc(100, 1, "/x/claude"),
            200: make_proc(200, 1, "/x/codex"),
        }
        first = run_discover([make_pane("%0", start="claude", pid=100)], procs)
        second = run_discover(
            [
                make_pane("%0", start="claude", pid=100),
                make_pane("%1", start="codex", pid=200),
            ],
            procs,
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)

    def test_unreadable_cwd_degrades_to_unknown(self):
        panes = [make_pane("%0", start="claude", pid=100, path="")]
        procs = {100: make_proc(100, 1, "/x/claude")}
        session = run_discover(panes, procs)[0]
        self.assertIsNone(session.canonical_cwd)
        self.assertEqual(session.cwd_source, "unavailable")

    def test_cwd_change_updates_grouping_key(self):
        procs = {100: make_proc(100, 1, "/x/claude")}
        before = run_discover([make_pane("%0", start="claude", pid=100, path="/tmp/a")], procs)[0]
        after = run_discover([make_pane("%0", start="claude", pid=100, path="/tmp/b")], procs)[0]
        self.assertEqual(before.canonical_cwd, "/tmp/a")
        self.assertEqual(after.canonical_cwd, "/tmp/b")

    def test_state_is_unknown_not_executing(self):
        procs = {100: make_proc(100, 1, "/x/claude")}
        session = run_discover([make_pane("%0", start="claude", pid=100)], procs)[0]
        self.assertIs(session.state, PaneState.UNKNOWN)
        self.assertEqual(session.state_source, discovery.STATE_SOURCE_NONE)

    def test_session_key_contains_host_and_pane_id(self):
        procs = {100: make_proc(100, 1, "/x/claude")}
        session = run_discover([make_pane("%3", start="claude", pid=100)], procs)[0]
        self.assertEqual(session.session_key, "/tmp/sock#%3")
        self.assertEqual(session.backend_target, "%3")
        self.assertEqual(session.generation, 7)

    def test_chinese_and_space_paths_preserved(self):
        procs = {100: make_proc(100, 1, "/x/claude")}
        for path in ("/tmp/中文目录", "/tmp/a0 space"):
            session = run_discover([make_pane("%0", start="claude", pid=100, path=path)], procs)[0]
            self.assertEqual(session.canonical_cwd, path)


if __name__ == "__main__":
    unittest.main()
