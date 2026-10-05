"""textual 界面层的离线单元测试。

只测试行渲染这类纯函数；不启动 textual 应用循环。缺少 textual 时整体跳过，
这样没有装界面依赖的环境仍能跑其余测试。
"""

from __future__ import annotations

import unittest

from agent_tree import tui
from agent_tree.grouping import build_tree
from agent_tree.model import AgentKind, AgentSession, PaneState

try:  # pragma: no cover - 取决于运行环境
    from rich.cells import cell_len

    from agent_tree import ui

    HAVE_TEXTUAL = True
except ImportError:  # pragma: no cover
    HAVE_TEXTUAL = False


def make_session(
    pane_id: str = "%0",
    cwd: str | None = "/Users/mac/workspace/agent-tree",
    *,
    agent: AgentKind = AgentKind.CODEX,
    display: str = "Codex",
    marker: str = "O",
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
        session_name="s0",
        window_index=1,
        window_name="w",
        pane_index=1,
    )


def sample_rows():
    tree = build_tree(
        [
            make_session("%0"),
            make_session("%1", agent=AgentKind.SHELL, display="Shell", marker="$"),
        ]
    )
    return tui.visible_rows(tree, set())


@unittest.skipUnless(HAVE_TEXTUAL, "需要安装 textual")
class CurrentPaneUITests(unittest.IsolatedAsyncioTestCase):
    async def test_group_click_toggles_children_and_survives_refresh(self):
        tree = build_tree([make_session("%0", "/tmp/alpha"), make_session("%1", "/tmp/beta")])
        model = tui.SidebarModel(lambda: tree)
        navigated = []
        model.on_navigate = navigated.append
        app = ui.SidebarApp(model)
        async with app.run_test(size=(40, 20)) as pilot:
            await pilot.click("#body", offset=(0, 0))
            self.assertIn("/tmp/alpha", model.collapsed)
            self.assertEqual([row.session.backend_target for row in model.rows() if row.session], ["%1"])
            app._tick()
            await pilot.pause()
            self.assertIn("/tmp/alpha", model.collapsed)
            await pilot.click("#body", offset=(4, 0))
            self.assertNotIn("/tmp/alpha", model.collapsed)
            self.assertEqual([row.session.backend_target for row in model.rows() if row.session], ["%0", "%1"])
            self.assertEqual(navigated, [])

    async def test_arrow_keys_only_select_child_sessions(self):
        tree = build_tree([make_session("%0", "/tmp/alpha"), make_session("%1", "/tmp/beta")])
        model = tui.SidebarModel(lambda: tree)
        navigated = []
        model.on_navigate = navigated.append
        app = ui.SidebarApp(model)
        async with app.run_test(size=(40, 20)) as pilot:
            for key, target in [("down", "%0"), ("down", "%1"), ("down", "%1"), ("up", "%0"), ("up", "%0")]:
                await pilot.press(key)
                self.assertEqual(model.current_session().backend_target, target)
            self.assertEqual(navigated, [])

    async def test_group_button_creates_in_clicked_directory_without_navigation(self):
        tree = build_tree([make_session("%0", "/tmp/alpha"), make_session("%1", "/tmp/beta")])
        model = tui.SidebarModel(lambda: tree)
        created, navigated = [], []
        model.on_new_session = created.append
        model.on_navigate = navigated.append
        app = ui.SidebarApp(model)
        async with app.run_test(size=(20, 20)) as pilot:
            await pilot.pause()
            index = next(i for i, row in enumerate(model.rows()) if row.kind == "group" and row.group.display_path == "/tmp/beta")
            line = app._line_rows.index(index)
            await pilot.click("#body", offset=(18, line))
            self.assertEqual(created, ["/tmp/beta"])
            self.assertEqual(navigated, [])
            self.assertNotIn("/tmp/beta", model.collapsed)
            await pilot.click("#body", offset=(4, line))
            self.assertEqual(created, ["/tmp/beta"])
            await pilot.pause()
            self.assertIn("/tmp/beta", model.collapsed)
            await pilot.click("#body", offset=(18, line))
            self.assertEqual(created, ["/tmp/beta", "/tmp/beta"])
            self.assertIn("/tmp/beta", model.collapsed)

    async def test_mouse_click_navigates_and_ignores_tree_spacing(self):
        tree = build_tree([make_session("%0"), make_session("%1")])
        model = tui.SidebarModel(lambda: tree)
        navigated = []
        model.on_navigate = lambda session: navigated.append(session.backend_target)
        app = ui.SidebarApp(model)
        async with app.run_test(size=(40,20)) as pilot:
            await pilot.pause()
            await pilot.click("#body", offset=(8, 3))
            self.assertEqual(navigated, [])
            await pilot.click("#body", offset=(8, 4))
            self.assertEqual(navigated, ["%1"])
            self.assertEqual(model.current_session().backend_target, "%1")

    async def test_mouse_click_navigates_after_scrolling(self):
        tree = build_tree([make_session(f"%{i}") for i in range(30)])
        model = tui.SidebarModel(lambda: tree)
        navigated = []
        model.on_navigate = lambda session: navigated.append(session.backend_target)
        app = ui.SidebarApp(model)
        async with app.run_test(size=(40,12)) as pilot:
            await pilot.pause()
            model.select(len(model.rows()) - 1)
            app._paint_body()
            await pilot.pause()
            scroll = app.query_one("#scroll", ui.VerticalScroll)
            self.assertGreater(scroll.scroll_y, 0)
            # 点击可见末行；屏幕坐标经 Textual 转为 body 局部坐标。
            line = app._line_rows.index(model.selected)
            target = model.current_session().backend_target
            await pilot.click("#body", offset=(8, line))
            self.assertEqual(navigated, [target])

    async def test_followed_pane_scrolls_into_view(self):
        tree = build_tree([make_session(f"%{i}") for i in range(50)])
        model = tui.SidebarModel(lambda: tree)
        current = ["%0"]
        model.sync_host = lambda: current[0]
        app = ui.SidebarApp(model)
        async with app.run_test(size=(50, 12)) as pilot:
            await pilot.pause()
            current[0] = "%49"
            app._sync_host()
            await pilot.pause()
            self.assertEqual(model.current_session().backend_target, "%49")
            scroll = app.query_one("#scroll", ui.VerticalScroll)
            selected_line = app._line_rows.index(model.selected)
            self.assertLessEqual(scroll.scroll_y, selected_line)
            self.assertLess(selected_line, scroll.scroll_y + scroll.size.height)
            current[0] = None
            model.move(-1)
            selected = model.selected
            app._sync_host()
            self.assertEqual(model.selected, selected)


@unittest.skipUnless(HAVE_TEXTUAL, "需要安装 textual")
class RowRenderTests(unittest.TestCase):
    def test_create_button_survives_narrow_and_chinese_paths(self):
        rows = tui.visible_rows(build_tree([make_session(cwd="/tmp/很长的中文项目目录")]), set())
        for width in (8, 14, 40):
            line = ui.group_line(rows[0], set(), True, width, can_create=True)
            self.assertTrue(line.plain.endswith("[+]"))
            self.assertEqual(cell_len(line.plain), width)
        unknown = tui.visible_rows(build_tree([make_session(cwd=None)]), set())[0]
        self.assertNotIn("[+]", ui.group_line(unknown, set(), False, 40, can_create=True).plain)
        self.assertNotIn("[+]", ui.group_line(rows[0], set(), False, 40).plain)

    def test_group_line_uses_brackets_and_right_aligned_count(self):
        rows = sample_rows()
        line = ui.group_line(rows[0], set(), False, 40)
        self.assertIn("[agent-tree]", line.plain)
        self.assertTrue(line.plain.rstrip().endswith("2"), line.plain)
        self.assertLessEqual(cell_len(line.plain), 40)

    def test_group_line_shortens_home_path(self):
        rows = sample_rows()
        line = ui.group_line(rows[0], set(), False, 40)
        self.assertIn("~/workspace", line.plain)

    def test_collapsed_group_uses_collapsed_mark(self):
        rows = sample_rows()
        line = ui.group_line(rows[0], {"/Users/mac/workspace/agent-tree"}, False, 40)
        self.assertTrue(line.plain.startswith(tui.COLLAPSED_MARK))

    def test_session_lines_use_tree_connectors(self):
        rows = sample_rows()
        first = ui.session_line(rows[1], False, 40)
        last = ui.session_line(rows[2], False, 40)
        self.assertTrue(first.plain.startswith("  " + ui.CONNECTOR_MID), repr(first.plain))
        self.assertTrue(last.plain.startswith("  " + ui.CONNECTOR_LAST), repr(last.plain))

    def test_session_name_uses_normal_text_color(self):
        rows = sample_rows()
        codex = ui.session_line(rows[1], False, 40)
        shell = ui.session_line(rows[2], False, 40)
        self.assertIn(
            ui.TEXT,
            [str(span.style) for span in codex.spans if codex.plain[span.start : span.end] == "Codex"],
        )
        self.assertIn(
            ui.TEXT,
            [str(span.style) for span in shell.spans if shell.plain[span.start : span.end] == "Shell"],
        )

    def test_selected_line_fills_width_with_background(self):
        rows = sample_rows()
        line = ui.session_line(rows[1], True, 40)
        self.assertTrue(line.plain.startswith("▎ "))
        self.assertEqual(cell_len(line.plain), 40)
        self.assertTrue(any(ui.SEL_BG in str(span.style) for span in line.spans))

    def test_long_path_is_truncated_not_wrapped(self):
        # 窄侧栏下长路径必须截断（否则 rich 会折行，破坏布局）
        tree = build_tree(
            [make_session("%0", "/Users/mac/workspace/opensource/deepseek-harness/sub/dir")]
        )
        rows = tui.visible_rows(tree, set())
        for width in (14, 20, 26, 32):
            line = ui.group_line(rows[0], set(), False, width)
            self.assertLessEqual(cell_len(line.plain), width, line.plain)

    def test_missing_cwd_group_has_no_path_hint(self):
        tree = build_tree([make_session("%0", None, agent=AgentKind.UNKNOWN, display="未知", marker="?")])
        rows = tui.visible_rows(tree, set())
        line = ui.group_line(rows[0], set(), False, 40)
        self.assertIn("目录未知", line.plain)

    def test_foot_hint_degrades_with_width(self):
        self.assertEqual(ui.foot_text(True, 80), tui.HINT_NAVIGATE)
        self.assertIn("n 新建", ui.foot_text(True, 40))
        narrow = ui.foot_text(True, 30)
        self.assertLessEqual(cell_len(narrow), 30)
        self.assertEqual(ui.foot_text(True, 12), ui.FOOT_NAVIGATE_LADDER[-1])
        self.assertEqual(ui.foot_text(False, 80), tui.HINT_BROWSE)


if __name__ == "__main__":
    unittest.main()
