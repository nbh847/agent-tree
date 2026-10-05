"""sidebar 模块的离线单元测试。用假 tmux 记录调用，不接触真实会话。"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from agent_tree.sidebar import (
    ClientContext,
    Location,
    SidebarError,
    SidebarManager,
    list_clients,
    new_instance_id,
)
from agent_tree.tmux import SEP, SIDEBAR_OPTION, TmuxCommandError


class FakeTmux:
    """按命令返回可预期的输出，并记录全部调用。"""

    socket = "sock"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.width = "120"
        self.panes: dict[str, str] = {}
        self.locations: dict[str, tuple[str, int]] = {}
        self.clients: list[tuple[str, str, int, str, int]] = []
        self.start_commands: dict[str, str] = {}
        self.mouse = "on"
        self.session_pane: dict[str, tuple[int, str]] = {}
        self.new_session_cwd = ""
        self.new_session_size: tuple[str, str] | None = None
        #: 按 window 索引的 pane 列表，供「侧栏是否独占 window」的查询应答。
        self.window_panes: dict[str, list[str]] = {}

    # ---- 便利方法 ----

    def called(self, command: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call and call[0] == command]

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        self.calls.append(args)
        stdout, code = self._respond(args)
        if check and code != 0:
            raise TmuxCommandError(args, code, "fake error")
        return subprocess.CompletedProcess(list(args), code, stdout, "")

    def _respond(self, args: tuple[str, ...]) -> tuple[str, int]:
        command = args[0]
        target = args[args.index("-t") + 1] if "-t" in args else None

        if command == "display-message":
            fmt = args[-1]
            if fmt == "#{window_width}":
                return self.width, 0
            if fmt == f"#{{{SIDEBAR_OPTION}}}":
                owner = self.panes.get(target or "")
                return (owner, 0) if owner else ("", 1)
            if fmt == "#{pane_id}":
                return (target, 0) if target in self.panes else ("", 1)
            if fmt == "#{pane_start_command}":
                return self.start_commands.get(target or "", ""), 0
            if fmt == "#{session_name}" + SEP + "#{window_index}":
                location = self.locations.get(target or "")
                if location is None:
                    return "", 1
                return f"{location[0]}{SEP}{location[1]}", 0
            if fmt == "#{window_width}" + SEP + "#{window_height}":
                return f"{self.width}{SEP}40", 0
            if fmt == "#{window_index}" + SEP + "#{pane_id}":
                info = self.session_pane.get(target or "")
                if info is None:
                    return "", 1
                return f"{info[0]}{SEP}{info[1]}", 0
        if command == "new-session":
            self.new_session_cwd = args[args.index("-c") + 1]
            if "-x" in args:
                self.new_session_size = (
                    args[args.index("-x") + 1],
                    args[args.index("-y") + 1],
                )
            self.session_pane["sNEW"] = (1, "%NEWSESS")
            self.panes["%NEWSESS"] = ""
            self.locations["%NEWSESS"] = ("sNEW", 1)
            return "sNEW\n", 0
        if command == "list-panes":
            if "-t" in args:
                panes = self.window_panes.get(target)
                if panes is not None:
                    return "".join(f"{pane}\n" for pane in panes), 0
            return (
                "".join(
                    f"{pane}{SEP}{owner}\n" for pane, owner in self.panes.items() if owner
                ),
                0,
            )
        if command == "list-clients":
            return (
                "".join(
                    f"{name}{SEP}{session}{SEP}{window}{SEP}{pane}{SEP}{activity}\n"
                    for name, session, window, pane, activity in self.clients
                ),
                0,
            )
        if command == "split-window":
            self.panes["%NEW"] = ""
            return "%NEW\n", 0
        if command == "set-option":
            self.panes[target or ""] = args[-1]
            return "", 0
        if command == "show-options":
            return self.mouse, 0
        return "", 0


def make_manager(tmux: FakeTmux, pane_id: str | None = "%9", instance: str = "inst") -> SidebarManager:
    tmux.panes.setdefault("%9", instance)
    tmux.locations.setdefault("%9", ("s0", 1))
    return SidebarManager(tmux, instance, pane_id=pane_id)


class ClientListingTests(unittest.TestCase):
    def test_list_clients_parses_control_clients(self):
        tmux = FakeTmux()
        tmux.clients = [("client-1", "s0", 1, "%9", 42), ("client-2", "s1", 2, "%8", 7)]
        clients = list_clients(tmux)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0], ClientContext("client-1", "s0", 1, "%9", 42))
        self.assertEqual(clients[1].activity, 7)


class ImageHostTests(unittest.TestCase):
    def test_passthrough_only_changes_owned_pane(self):
        tmux = FakeTmux()
        manager = make_manager(tmux)
        self.assertTrue(manager.enable_images())
        self.assertEqual(tmux.called("set-option"), [
            ("set-option", "-p", "-t", "%9", "allow-passthrough", "on")])
        tmux.panes["%9"] = "someone-else"
        self.assertFalse(manager.enable_images())
        self.assertEqual(len(tmux.called("set-option")), 1)

    def test_geometry_accounts_for_top_status_and_rejects_hidden_zoomed_or_cropped(self):
        tmux = FakeTmux()
        manager = make_manager(tmux)
        manager.client_name = "owner"
        fields = ["s0", "s0", "1", "0", "3", "2", "120", "42", "120", "40", "top", "2", "@1"]
        def answer(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, SEP.join(fields), "")
        with patch.object(tmux, "run", side_effect=answer):
            self.assertEqual(manager.image_origin(), (3, 4, "@1"))
            fields[10] = "bottom"
            self.assertEqual(manager.image_origin(), (3, 2, "@1"))
            for position, value in [(0, "other"), (2, "0"), (3, "1"), (6, "80"), (7, "20"), (4, "invalid")]:
                old = fields[position]
                fields[position] = value
                self.assertIsNone(manager.image_origin())
                fields[position] = old

    def test_launch_passes_terminal_protocol_explicitly(self):
        tmux = FakeTmux()
        manager = make_manager(tmux, pane_id=None)
        with patch.dict("os.environ", {"TERM_PROGRAM": "iTerm.app"}):
            manager.launch("s0:0")
        self.assertIn("AGENT_TREE_IMAGE_PROTOCOL=iterm", tmux.called("split-window")[0])


class FollowClientTests(unittest.TestCase):
    def setUp(self):
        self.tmux = FakeTmux()
        self.manager = make_manager(self.tmux)
        self.manager.client_name = "owner"
        self.tmux.panes["%1"] = ""
        self.tmux.locations["%1"] = ("s1", 2)
        self.tmux.clients = [("owner", "s1", 2, "%1", 1),
                             ("other", "s0", 1, "%9", 100)]

    def test_follows_bound_client_without_switching_clients_or_focus(self):
        self.assertEqual(self.manager.follow_client(), "%1")
        self.assertEqual(self.tmux.called("join-pane"), [
            ("join-pane", "-d", "-b", "-h", "-s", "%9", "-t", "%1", "-l", "24%")])
        self.assertEqual(self.tmux.called("switch-client"), [])
        self.assertEqual(self.tmux.called("select-pane"), [])
        self.assertEqual(self.tmux.called("select-window"), [])

    def test_disconnected_client_does_not_adopt_other_client(self):
        self.tmux.clients = self.tmux.clients[1:]
        self.assertIsNone(self.manager.follow_client())
        self.assertEqual(self.tmux.called("join-pane"), [])

    def test_same_window_only_updates_active_pane(self):
        self.tmux.clients = [("owner", "s0", 1, "%1", 1)]
        self.assertEqual(self.manager.follow_client(), "%1")
        self.assertEqual(self.tmux.called("join-pane"), [])

    def test_sidebar_focus_preserves_browsing_selection(self):
        self.tmux.clients = [("owner", "s0", 1, "%9", 1)]
        self.assertIsNone(self.manager.follow_client())

    def test_new_target_syncs_once_even_when_sidebar_has_focus(self):
        self.tmux.clients = [("owner", "s0", 1, "%9", 1)]
        self.manager.last_target = "%1"
        self.assertEqual(self.manager.follow_client(), "%1")
        self.assertIsNone(self.manager.follow_client())

    def test_foreign_sidebar_and_narrow_window_are_rejected(self):
        self.tmux.panes["%2"] = "other"
        self.tmux.locations["%2"] = ("s1", 2)
        with self.assertRaisesRegex(SidebarError, "其他侧栏"):
            self.manager.follow_client()
        self.tmux.panes.pop("%2")
        self.tmux.width = "40"
        with self.assertRaisesRegex(SidebarError, "过窄"):
            self.manager.follow_client()
        self.assertEqual(self.tmux.called("join-pane"), [])

    def test_dead_target_and_join_failure_leave_sidebar_alive(self):
        self.tmux.panes.pop("%1")
        with self.assertRaisesRegex(SidebarError, "已失效"):
            self.manager.follow_client()
        self.tmux.panes["%1"] = ""
        original = self.tmux.run
        def fail_join(*args, **kwargs):
            if args[0] == "join-pane":
                raise TmuxCommandError(args, 1, "gone")
            return original(*args, **kwargs)
        with patch.object(self.tmux, "run", side_effect=fail_join):
            with self.assertRaisesRegex(SidebarError, "跟随窗口失败"):
                self.manager.follow_client()
        self.assertEqual(self.tmux.called("kill-pane"), [])

    def test_manual_session_switch_cancels_previous_restore(self):
        self.manager._borrowed_client = ("owner", "origin", "s0")
        self.manager.follow_client()
        self.manager.restore_client()
        self.assertEqual(self.tmux.called("switch-client"), [])

    def test_launch_passes_client_target_and_width_to_child(self):
        self.tmux.clients = [("owner", "s0", 1, "%1", 1)]
        self.manager.width = "35%"
        self.manager.pane_id = None
        self.tmux.panes.pop("%9")
        self.manager.launch("s0:1")
        call = self.tmux.called("split-window")[0]
        self.assertEqual(call[call.index("--client") + 1], "owner")
        self.assertEqual(call[call.index("--target-pane") + 1], "%1")
        self.assertEqual(call[call.index("--width") + 1], "35%")


class OwnershipTests(unittest.TestCase):
    def test_owned_panes_only_lists_marked_panes(self):
        tmux = FakeTmux()
        tmux.panes = {"%1": "", "%9": "inst", "%5": "other"}
        self.assertEqual(sorted(SidebarManager(tmux, "inst").owned_panes()), ["%5", "%9"])

    def test_is_mine_only_true_for_own_instance(self):
        tmux = FakeTmux()
        tmux.panes = {"%1": "", "%9": "inst", "%5": "other"}
        manager = SidebarManager(tmux, "inst")
        self.assertTrue(manager.is_mine("%9"))
        self.assertFalse(manager.is_mine("%5"))
        self.assertFalse(manager.is_mine("%1"))

    def test_teardown_never_kills_foreign_or_user_panes(self):
        tmux = FakeTmux()
        tmux.panes = {"%1": "", "%5": "other"}
        SidebarManager(tmux, "inst", pane_id="%5").teardown()
        SidebarManager(tmux, "inst", pane_id="%1").teardown()
        self.assertEqual(tmux.called("kill-pane"), [])

    def test_teardown_kills_own_pane(self):
        tmux = FakeTmux()
        manager = make_manager(tmux)
        manager.teardown()
        self.assertEqual(tmux.called("kill-pane"), [("kill-pane", "-t", "%9")])
        self.assertIsNone(manager.pane_id)


class ClaimPaneTests(unittest.TestCase):
    """--in-pane 只能接管 agent-tree 自己创建的 pane，避免误伤用户 pane。"""

    def _manager(self, tmux, pane="%7", instance="inst"):
        return SidebarManager(tmux, instance, pane_id=pane)

    def test_accepts_pane_started_by_agent_tree(self):
        tmux = FakeTmux()
        tmux.panes = {"%7": ""}
        tmux.start_commands = {"%7": "/usr/bin/python3 -m agent_tree --in-pane --instance x"}
        self._manager(tmux).claim_pane("%7")
        self.assertEqual(tmux.panes["%7"], "inst")

    def test_accepts_pane_already_owned_by_this_instance(self):
        tmux = FakeTmux()
        tmux.panes = {"%7": "inst"}
        self._manager(tmux).claim_pane("%7")
        self.assertEqual(tmux.panes["%7"], "inst")

    def test_refuses_pane_of_another_instance(self):
        tmux = FakeTmux()
        tmux.panes = {"%7": "other"}
        with self.assertRaises(SidebarError):
            self._manager(tmux).claim_pane("%7")
        self.assertEqual(tmux.panes["%7"], "other")

    def test_refuses_user_shell_pane(self):
        # 用户在交互式 shell 里手动运行 --in-pane：该 pane 不是 agent-tree 创建的
        tmux = FakeTmux()
        tmux.panes = {"%7": ""}
        tmux.start_commands = {"%7": "-zsh"}
        with self.assertRaises(SidebarError):
            self._manager(tmux).claim_pane("%7")
        self.assertEqual(tmux.panes["%7"], "")


class LaunchTests(unittest.TestCase):
    def test_rejects_too_narrow_window(self):
        tmux = FakeTmux()
        tmux.width = "40"
        with self.assertRaises(SidebarError):
            make_manager(tmux, pane_id=None).launch("s0:1")
        self.assertEqual(tmux.called("split-window"), [])

    def test_rejects_duplicate_sidebar_in_same_window(self):
        tmux = FakeTmux()
        tmux.panes = {"%9": "inst"}
        tmux.locations = {"%9": ("s0", 1)}
        with self.assertRaises(SidebarError):
            make_manager(tmux, pane_id=None).launch("s0:1")
        self.assertEqual(tmux.called("split-window"), [])

    def test_allows_sidebar_in_other_window(self):
        tmux = FakeTmux()
        tmux.panes = {"%9": "inst"}
        tmux.locations = {"%9": ("s0", 1)}
        pane_id = make_manager(tmux, pane_id=None).launch("s0:2")
        self.assertEqual(pane_id, "%NEW")

    def test_launch_marks_ownership_and_returns_pane(self):
        tmux = FakeTmux()
        manager = SidebarManager(tmux, "inst")
        pane_id = manager.launch("s0:1")
        self.assertEqual(pane_id, "%NEW")
        self.assertEqual(tmux.panes["%NEW"], "inst")
        self.assertEqual(manager.pane_id, "%NEW")
        self.assertEqual(tmux.called("split-window")[0][:3], ("split-window", "-b", "-h"))


class NavigateTests(unittest.TestCase):
    def setUp(self):
        self.tmux = FakeTmux()
        self.tmux.panes = {"%9": "inst", "%1": "", "%2": ""}
        self.tmux.locations = {"%9": ("s0", 1), "%1": ("s0", 1), "%2": ("s1", 1)}
        self.tmux.clients = [("client-1", "s0", 1, "%9", 100)]
        self.manager = SidebarManager(self.tmux, "inst", pane_id="%9")

    def test_navigation_migrates_sidebar_and_keeps_focus(self):
        self.manager.navigate("s1", 1, "%2")
        self.assertEqual(len(self.tmux.called("join-pane")), 1)
        self.assertEqual(len(self.tmux.called("switch-client")), 1)
        selects = self.tmux.called("select-pane")
        self.assertEqual(selects[-1][-1], "%9")

    def test_same_session_window_switch_uses_select_window(self):
        # 同一 session 内换 window：不切 client，用 select-window 让视图跟过去
        self.tmux.locations["%9"] = ("s1", 1)
        self.manager.navigate("s1", 2, "%2")
        self.assertEqual(self.tmux.called("switch-client"), [])
        self.assertEqual(self.tmux.called("select-window")[-1][-1], "s1:2")
        self.assertEqual(self.tmux.called("select-pane")[-1][-1], "%9")

    def test_same_window_does_not_migrate(self):
        self.manager.navigate("s0", 1, "%1")
        self.assertEqual(self.tmux.called("join-pane"), [])
        self.assertEqual(self.tmux.called("switch-client"), [])
        self.assertEqual(self.tmux.called("select-pane")[-1][-1], "%9")

    def test_handoff_focuses_target_pane(self):
        self.manager.navigate("s0", 1, "%1", focus_target=True)
        self.assertEqual(self.tmux.called("select-pane")[-1][-1], "%1")
        self.assertEqual(self.manager.last_target, "%1")

    def test_stale_target_raises_without_migrating(self):
        with self.assertRaises(SidebarError):
            self.manager.navigate("s1", 1, "%404")
        self.assertEqual(self.tmux.called("join-pane"), [])

    def test_alone_sidebar_switches_client_before_migrating(self):
        # 侧栏独占原 window 时先切 client 再 join：若先 join，原 window 因没有
        # 剩余 pane 被销毁，client 所在 session 消亡，client 会被直接断开。
        self.tmux.window_panes = {"s0:1": ["%9"]}
        self.manager.navigate("s1", 1, "%2")
        calls = [call[0] for call in self.tmux.calls]
        self.assertLess(calls.index("switch-client"), calls.index("join-pane"))
        self.assertEqual(len(self.tmux.called("join-pane")), 1)
        self.assertEqual(len(self.tmux.called("switch-client")), 1)  # 没有重复切换
        self.assertEqual(self.tmux.called("select-pane")[-1][-1], "%9")

    def test_shared_window_keeps_join_before_switch(self):
        # 原 window 还有用户 pane：保持原有顺序，join 失败时视图不改变
        self.tmux.window_panes = {"s0:1": ["%9", "%1"]}
        self.manager.navigate("s1", 1, "%2")
        calls = [call[0] for call in self.tmux.calls]
        self.assertLess(calls.index("join-pane"), calls.index("switch-client"))

    def test_missing_sidebar_raises(self):
        self.manager.pane_id = "%404"
        with self.assertRaises(SidebarError):
            self.manager.navigate("s0", 1, "%1")

    def test_initiating_client_prefers_most_recent(self):
        self.tmux.clients = [("a", "s0", 1, "%9", 10), ("b", "s0", 1, "%9", 99)]
        client = self.manager.initiating_client()
        self.assertEqual(client.name, "b")

    def test_initiating_client_none_when_window_unwatched(self):
        self.tmux.clients = [("a", "s9", 9, "%9", 10)]
        self.assertIsNone(self.manager.initiating_client())

    def test_location_of_unknown_pane_is_none(self):
        self.assertIsNone(self.manager.location_of("%404"))

    def test_location_window_string(self):
        self.assertEqual(Location("s0", 3).window, "s0:3")


class NewSessionTests(unittest.TestCase):
    """n 键新建会话：在指定目录建 session，并只迁移自建侧栏 pane。"""

    def setUp(self):
        self.tmux = FakeTmux()
        self.tmux.panes = {"%9": "inst", "%1": ""}
        self.tmux.locations = {"%9": ("s0", 1), "%1": ("s0", 1)}
        self.tmux.clients = [("client-1", "s0", 1, "%9", 100)]
        self.manager = SidebarManager(self.tmux, "inst", pane_id="%9")

    def test_creates_session_in_selected_directory(self):
        name = self.manager.new_session("/Users/mac/workspace/kzz-radar")
        self.assertEqual(name, "sNEW")
        self.assertEqual(self.tmux.new_session_cwd, "/Users/mac/workspace/kzz-radar")

    def test_creates_session_at_current_window_size(self):
        # new-session 默认 80x24 会让 join-pane 的 30% 按 80 列算，client 切过去
        # 重排后侧栏被摊宽；必须按侧栏当前窗口尺寸创建。
        self.tmux.width = "178"
        self.manager.new_session("/tmp/proj")
        self.assertEqual(self.tmux.new_session_size, ("178", "40"))

    def test_brings_sidebar_and_client_to_new_session(self):
        self.manager.new_session("/tmp/proj")
        self.assertEqual(len(self.tmux.called("join-pane")), 1)
        switch = self.tmux.called("switch-client")
        self.assertEqual(len(switch), 1)
        self.assertEqual(switch[0][-1], "sNEW:1")
        # 焦点仍留在侧栏自身，未向新 pane 发送输入
        self.assertEqual(self.tmux.called("select-pane")[-1][-1], "%9")
        self.assertEqual(self.tmux.called("send-keys"), [])

    def test_missing_session_name_raises(self):
        self.tmux.session_pane = {}

        def run(*args, check=True):
            # 只模拟 new-session 返回空；尺寸查询按正常窗口应答
            fmt = "#{window_width}" + SEP + "#{window_height}"
            stdout = f"{self.tmux.width}{SEP}40" if args[-1] == fmt else ""
            return subprocess.CompletedProcess(list(args), 0, stdout, "")

        self.tmux.run = run  # type: ignore[assignment]
        with self.assertRaises(SidebarError):
            self.manager.new_session("/tmp/proj")


class RestoreClientTests(unittest.TestCase):
    """导航借走的 client 必须在退出时送回原 session，否则原 session 会一直 detached。"""

    def setUp(self):
        self.tmux = FakeTmux()
        self.tmux.panes = {"%9": "inst", "%1": "", "%2": ""}
        self.tmux.locations = {"%9": ("s0", 1), "%1": ("s0", 1), "%2": ("s1", 1)}
        self.tmux.clients = [("client-1", "s0", 1, "%9", 100)]
        self.manager = SidebarManager(self.tmux, "inst", pane_id="%9")

    def test_restore_sends_client_back_to_origin(self):
        self.manager.navigate("s1", 1, "%2")  # 借走 client
        self.tmux.clients = [("client-1", "s1", 1, "%9", 100)]  # 它现在停在 s1
        self.manager.restore_client()
        switch = self.tmux.called("switch-client")
        self.assertEqual(switch[-1], ("switch-client", "-c", "client-1", "-t", "s0"))

    def test_restore_keeps_original_origin_across_multiple_hops(self):
        self.manager.navigate("s1", 1, "%2")
        # 侧栏已迁到 s1，client 也跟着到 s1
        self.tmux.locations["%9"] = ("s1", 1)
        self.tmux.clients = [("client-1", "s1", 1, "%9", 100)]
        self.manager.navigate("s2", 1, "%2")
        self.tmux.clients = [("client-1", "s2", 1, "%9", 100)]
        self.manager.restore_client()
        self.assertEqual(self.tmux.called("switch-client")[-1][-1], "s0")

    def test_restore_does_nothing_when_user_moved_on(self):
        self.manager.navigate("s1", 1, "%2")
        self.tmux.clients = [("client-1", "s9", 1, "%9", 100)]  # 用户自己又切走了
        before = len(self.tmux.called("switch-client"))
        self.manager.restore_client()
        self.assertEqual(len(self.tmux.called("switch-client")), before)

    def test_restore_without_navigation_is_noop(self):
        self.manager.restore_client()
        self.assertEqual(self.tmux.called("switch-client"), [])

    def test_restore_is_idempotent(self):
        self.manager.navigate("s1", 1, "%2")
        self.tmux.clients = [("client-1", "s1", 1, "%9", 100)]
        self.manager.restore_client()
        count = len(self.tmux.called("switch-client"))
        self.manager.restore_client()
        self.assertEqual(len(self.tmux.called("switch-client")), count)

    def test_same_session_navigation_never_borrows_client(self):
        self.manager.navigate("s0", 1, "%1")
        self.tmux.clients = [("client-1", "s0", 1, "%9", 100)]
        self.manager.restore_client()
        self.assertEqual(self.tmux.called("switch-client"), [])


class InstanceIdTests(unittest.TestCase):
    def test_instance_ids_are_unique_and_short(self):
        first, second = new_instance_id(), new_instance_id()
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 12)


if __name__ == "__main__":
    unittest.main()
