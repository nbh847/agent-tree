"""tui 纯逻辑的离线单元测试。不依赖 textual，也不启动终端界面。"""

from __future__ import annotations

import unittest

from agent_tree import tui
from agent_tree.grouping import build_tree
from agent_tree.model import AgentKind, AgentSession, PaneState


def make_session(
    pane_id: str = "%0",
    cwd: str | None = "/tmp/proj",
    *,
    agent: AgentKind = AgentKind.CLAUDE_CODE,
    display: str = "Claude Code",
    marker: str = "C",
    window_index: int = 1,
    pane_index: int = 1,
    session_name: str = "s0",
) -> AgentSession:
    return AgentSession(
        session_key=f"/sock#{pane_id}",
        host_key="/sock",
        backend="tmux",
        backend_target=pane_id,
        cwd=cwd,
        canonical_cwd=cwd,
        cwd_source="pane_current_path" if cwd else "unavailable",
        agent=agent,
        display_name=display,
        marker=marker,
        state=PaneState.UNKNOWN,
        state_source="not-implemented",
        confidence="high",
        observed_at=0.0,
        generation=1,
        is_active=True,
        pane_pid=100,
        session_name=session_name,
        window_index=window_index,
        window_name="w",
        pane_index=pane_index,
    )


def sample_tree():
    return build_tree(
        [
            make_session("%0", "/tmp/alpha"),
            make_session("%1", "/tmp/alpha", agent=AgentKind.CODEX, display="Codex", marker="O"),
            make_session("%2", None, agent=AgentKind.UNKNOWN, display="未知", marker="?"),
        ]
    )


class VisibleRowsTests(unittest.TestCase):
    def test_default_all_expanded(self):
        rows = tui.visible_rows(sample_tree(), set())
        self.assertEqual([row.kind for row in rows], ["group", "session", "session", "group", "session"])

    def test_collapsed_group_hides_its_sessions(self):
        rows = tui.visible_rows(sample_tree(), {"/tmp/alpha"})
        self.assertEqual([row.kind for row in rows], ["group", "group", "session"])

    def test_group_row_carries_session_count(self):
        rows = tui.visible_rows(sample_tree(), set())
        self.assertEqual(len(rows[0].group.sessions), 2)

    def test_last_session_in_group_is_marked(self):
        rows = tui.visible_rows(sample_tree(), set())
        sessions = [row for row in rows if row.kind == "session"]
        self.assertEqual(
            [row.last for row in sessions],
            [False, True, True],
        )


class FormatTextTests(unittest.TestCase):
    def test_text_tree_contains_groups_and_sessions(self):
        text = tui.format_tree_text(sample_tree(), host_key="/tmp/sock")
        self.assertIn("Agent Tree", text)
        self.assertIn("/tmp/sock", text)
        self.assertIn("alpha", text)
        self.assertIn("[C] Claude Code", text)
        self.assertIn("[O] Codex", text)
        self.assertIn("目录未知", text)

    def test_text_tree_empty_state(self):
        text = tui.format_tree_text(build_tree([]))
        self.assertIn("未发现 Agent 会话", text)


class SidebarModelTests(unittest.TestCase):
    def test_current_pane_expands_group_and_updates_selection(self):
        model = tui.SidebarModel(sample_tree)
        model.sync_host = lambda: "%1"
        model.collapsed.add("/tmp/alpha")
        model.reload()
        self.assertEqual(model.current_session().backend_target, "%1")
        self.assertNotIn("/tmp/alpha", model.collapsed)
        model.sync_host = lambda: None  # 用户返回侧栏浏览，不应被刷新强行拉回。
        model.move(-1)
        selected = model.selected
        model.reload()
        self.assertEqual(model.selected, selected)

    def test_current_pane_missing_from_tree_waits_for_discovery(self):
        model = tui.SidebarModel(sample_tree)
        model.sync_host = lambda: "%missing"
        model.reload()
        self.assertIsNone(model.current_session())
        model.sync_host = lambda: None  # 新建后侧栏仍聚焦，目标要等下一轮发现。
        model._refresh = lambda: build_tree([make_session("%missing", "/tmp/new")])
        model.reload()
        self.assertEqual(model.current_session().backend_target, "%missing")

    def test_sync_failure_keeps_tree_and_selection(self):
        model = self._model()
        def fail():
            raise RuntimeError("socket gone")
        model.sync_host = fail
        model.sync_current()
        self.assertIn("socket gone", model.message)
        self.assertEqual(model.tree, sample_tree())

    def test_selection_tracks_identity_after_rows_reorder(self):
        model = self._model()
        model.select(2)
        model._refresh = lambda: build_tree([
            make_session("%new", "/tmp/aaa"),
            *[s for g in sample_tree() for s in g.sessions],
        ])
        model.reload()
        self.assertEqual(model.current_session().backend_target, "%1")

    def _model(self, tree=None):
        tree = sample_tree() if tree is None else tree
        model = tui.SidebarModel(lambda: tree)
        model.reload()
        return model

    def test_loading_true_until_first_reload(self):
        model = tui.SidebarModel(sample_tree)
        self.assertTrue(model.loading)
        model.reload()
        self.assertFalse(model.loading)

    def test_reload_increments_generation_and_clamps(self):
        model = self._model()
        self.assertEqual(model.generation, 1)
        model.selected = 99
        model.reload()
        self.assertEqual(model.generation, 2)
        self.assertEqual(model.selected, len(model.rows()) - 1)

    def test_move_clamps_at_both_ends(self):
        model = self._model()
        model.move(-10)
        self.assertEqual(model.selected, 1)
        model.move(10)
        self.assertEqual(model.selected, len(model.rows()) - 1)

    def test_move_skips_group_rows_in_both_directions(self):
        model = self._model()
        for delta, expected in [(1, 1), (1, 2), (1, 4), (-1, 2), (-1, 1), (-1, 1)]:
            model.move(delta)
            self.assertEqual(model.selected, expected)
            self.assertIsNotNone(model.current_session())

    def test_move_from_group_selects_session_in_requested_direction(self):
        model = self._model()
        model.select(3)
        model.move(-1)
        self.assertEqual(model.selected, 2)
        model.select(3)
        model.move(1)
        self.assertEqual(model.selected, 4)

    def test_move_skips_collapsed_groups_and_handles_no_visible_sessions(self):
        model = self._model()
        model.collapsed.add("/tmp/alpha")
        model.move(1)
        self.assertEqual(model.current_session().backend_target, "%2")
        model.collapsed.update(group.key for group in model.tree)
        model.select(0)
        model.move(1)
        self.assertEqual(model.selected, 0)
        model = self._model(build_tree([]))
        model.move(-1)
        self.assertIsNone(model.current_row())

    def test_select_clamps(self):
        model = self._model()
        model.select(99)
        self.assertEqual(model.selected, len(model.rows()) - 1)
        model.select(-5)
        self.assertEqual(model.selected, 0)

    def test_toggle_group_row_collapses_and_expands(self):
        model = self._model()
        model.toggle_current()
        self.assertIn("/tmp/alpha", model.collapsed)
        model.toggle_current()
        self.assertNotIn("/tmp/alpha", model.collapsed)

    def test_toggle_on_session_row_does_nothing(self):
        model = self._model()
        model.move(1)
        model.toggle_current()
        self.assertEqual(model.collapsed, set())

    def test_collapse_and_expand_current_only_apply_to_groups(self):
        model = self._model()
        model.expand_current()
        self.assertEqual(model.collapsed, set())
        model.collapse_current()
        self.assertIn("/tmp/alpha", model.collapsed)

    def test_reload_failure_surfaces_message_without_crashing(self):
        def boom():
            raise RuntimeError("socket 已断开")

        model = tui.SidebarModel(boom)
        model.reload()
        self.assertEqual(model.tree, ())
        self.assertIn("刷新失败", model.message)
        self.assertFalse(model.loading)

    def test_selection_stays_valid_when_tree_shrinks(self):
        model = self._model()
        model.move(4)
        self.assertEqual(model.selected, 4)
        model._refresh = lambda: build_tree([make_session("%0", "/tmp/alpha")])
        model.reload()
        self.assertLess(model.selected, len(model.rows()))

    def test_current_session_none_on_group_row(self):
        model = self._model()
        self.assertIsNone(model.current_session())


class NavigationCallbackTests(unittest.TestCase):
    """选中即切换只由用户操作触发；刷新与排序变化不产生导航。"""

    def _model(self):
        model = tui.SidebarModel(sample_tree)
        model.can_navigate = True
        model.navigated = []
        model.handed = []
        model.on_navigate = model.navigated.append
        model.on_handoff = model.handed.append
        model.reload()
        return model

    def test_move_then_activate_triggers_navigation(self):
        model = self._model()
        model.move(1)
        model.activate_current()
        self.assertEqual(len(model.navigated), 1)
        self.assertEqual(model.navigated[0].backend_target, "%0")

    def test_move_alone_does_not_navigate(self):
        # ↑↓ 只移动高亮；进入目标必须由 Enter／→ 显式触发
        model = self._model()
        model.move(1)
        model.move(1)
        model.move(-1)
        self.assertEqual(model.navigated, [])

    def test_activate_on_group_row_does_not_navigate(self):
        model = self._model()
        model.activate_current()
        self.assertEqual(model.navigated, [])

    def test_reload_never_navigates(self):
        model = self._model()
        model.reload()
        model.reload()
        self.assertEqual(model.navigated, [])

    def test_handoff_only_for_session_rows(self):
        model = self._model()
        model.handoff_current()  # 目录行
        self.assertEqual(model.handed, [])
        model.move(1)
        model.handoff_current()
        self.assertEqual(len(model.handed), 1)

    def test_hint_reflects_navigation_ability(self):
        browse = tui.SidebarModel(sample_tree)
        browse.reload()
        navigating = self._model()
        self.assertEqual((browse.can_navigate, navigating.can_navigate), (False, True))


class NewSessionTests(unittest.TestCase):
    """按 n 在当前行所属目录下新建会话。"""

    def _model(self):
        model = tui.SidebarModel(sample_tree)
        model.created = []
        model.on_new_session = model.created.append
        model.reload()
        return model

    def test_creates_in_selected_group_directory(self):
        model = self._model()
        model.new_session_in_current_dir()  # 第一行是 /tmp/alpha 目录行
        self.assertEqual(model.created, ["/tmp/alpha"])

    def test_session_row_uses_its_group_directory(self):
        model = self._model()
        model.move(1)
        model.new_session_in_current_dir()
        self.assertEqual(model.created, ["/tmp/alpha"])

    def test_unknown_directory_is_refused_without_creating(self):
        model = self._model()
        model.select(len(model.rows()) - 1)  # 「目录未知」组
        model.new_session_in_current_dir()
        self.assertEqual(model.created, [])
        self.assertIn("没有可用目录", model.message)

    def test_failure_is_surfaced_as_message(self):
        model = self._model()

        def boom(_path):
            raise RuntimeError("cwd 不存在")

        model.on_new_session = boom
        model.new_session_in_current_dir()
        self.assertIn("新建会话失败", model.message)

    def test_no_callback_configured_is_a_noop(self):
        model = tui.SidebarModel(sample_tree)
        model.reload()
        model.new_session_in_current_dir()
        self.assertEqual(model.message, "")


class CompanionExitTests(unittest.TestCase):
    """侧栏旁的用户 pane 全部关闭时自动补位：同组第一个 → 全列表第一个 → 退出。"""

    def _model(self, trees, window=("s0", 1)):
        supply = iter(trees)
        model = tui.SidebarModel(lambda: next(supply))
        model.sidebar_window = lambda: window
        model.navigated = []
        model.exited = []
        model.on_navigate = model.navigated.append
        model.on_exit = lambda: model.exited.append(True)
        return model

    def test_replaces_with_first_session_of_same_group(self):
        before = build_tree(
            [
                make_session("%0", "/tmp/alpha", session_name="s0", window_index=1),
                make_session("%1", "/tmp/alpha", agent=AgentKind.SHELL,
                             display="Shell", marker="$", session_name="s1", window_index=1),
            ]
        )
        after = build_tree(
            [make_session("%1", "/tmp/alpha", agent=AgentKind.SHELL,
                          display="Shell", marker="$", session_name="s1", window_index=1)]
        )
        model = self._model([before, after])
        model.reload()  # 旁 pane 还在：不动作
        self.assertEqual(model.navigated, [])
        model.reload()  # 旁 pane 关闭：补位到同组第一个
        self.assertEqual([s.backend_target for s in model.navigated], ["%1"])
        self.assertEqual(model.exited, [])

    def test_same_session_other_window_is_a_valid_replacement(self):
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0", window_index=1)])
        after = build_tree([make_session("%2", "/tmp/alpha", session_name="s0", window_index=2)])
        model = self._model([before, after])
        model.reload()
        model.reload()
        self.assertEqual([s.backend_target for s in model.navigated], ["%2"])

    def test_falls_back_to_first_session_of_whole_tree(self):
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0", window_index=1)])
        after = build_tree(
            [make_session("%3", "/tmp/beta", session_name="s9", window_index=1)]
        )
        model = self._model([before, after])
        model.reload()
        model.reload()
        self.assertEqual([s.backend_target for s in model.navigated], ["%3"])

    def test_exits_when_nothing_left_to_replace_with(self):
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0", window_index=1)])
        after = build_tree([])
        model = self._model([before, after])
        model.reload()
        model.reload()
        self.assertEqual(model.navigated, [])
        self.assertEqual(model.exited, [True])

    def test_replacement_picks_first_displayed_session_of_group(self):
        # 组内排序 Agent 在前：补位目标取展示顺序的第一个，而不是随机一个
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0", window_index=1)])
        after = build_tree(
            [
                make_session("%5", "/tmp/alpha", agent=AgentKind.SHELL,
                             display="Shell", marker="$", session_name="s2", window_index=1),
                make_session("%6", "/tmp/alpha", agent=AgentKind.CODEX,
                             display="Codex", marker="O", session_name="s1", window_index=1),
            ]
        )
        model = self._model([before, after])
        model.reload()
        model.reload()
        self.assertEqual([s.backend_target for s in model.navigated], ["%6"])

    def test_unknown_origin_falls_back_to_first_in_tree(self):
        # 上一轮树里找不到被关 pane（如首帧前就关了）：退回全列表第一个
        empty = build_tree([])
        after = build_tree([make_session("%3", "/tmp/beta", session_name="s9")])
        model = self._model([empty, after])
        model.reload()
        model.reload()
        self.assertEqual([s.backend_target for s in model.navigated], ["%3"])

    def test_no_action_when_sidebar_window_unknown(self):
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0")])
        after = build_tree([])
        model = self._model([before, after], window=None)
        model.reload()
        model.reload()
        self.assertEqual(model.navigated, [])
        self.assertEqual(model.exited, [])

    def test_no_action_without_callbacks(self):
        model = tui.SidebarModel(lambda: build_tree([]))
        model.sidebar_window = lambda: ("s0", 1)
        model.reload()  # 无 on_navigate／on_exit 也不应崩溃
        self.assertEqual(model.tree, ())

    def test_refresh_failure_does_not_trigger_replacement(self):
        before = build_tree([make_session("%0", "/tmp/alpha", session_name="s0")])
        failed = {"now": False}

        def refresh():
            if failed["now"]:
                raise RuntimeError("socket 已断开")
            failed["now"] = True
            return before

        model = tui.SidebarModel(refresh)
        model.sidebar_window = lambda: ("s0", 1)
        model.navigated = []
        model.on_navigate = model.navigated.append
        model.reload()
        model.reload()  # 刷新失败：沿用旧树，不补位
        self.assertEqual(model.navigated, [])


if __name__ == "__main__":
    unittest.main()
