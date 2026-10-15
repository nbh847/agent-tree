"""textual 界面层的离线单元测试。

只测试行渲染这类纯函数；不启动 textual 应用循环。缺少 textual 时整体跳过，
这样没有装界面依赖的环境仍能跑其余测试。
"""

from __future__ import annotations

import unittest
import asyncio
import time
from threading import Event
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

from agent_tree.icons import PLACEHOLDER
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
    async def test_logo_is_cached_once_and_falls_back_without_affecting_navigation(self):
        model = tui.SidebarModel(lambda: build_tree([make_session()]))
        navigated = Mock()
        model.on_navigate = navigated
        app = ui.SidebarApp(model, image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(40, 30)) as pilot:
            await pilot.pause()
            self.assertEqual(app._last_text["#brand"].plain.count(PLACEHOLDER), 72)
            self.assertIn("All agents in one.", app._last_text["#brand"].plain)
            lines = app._last_text["#brand"].plain.count("\n")
            app._image_origin = None
            app._paint_brand()
            self.assertEqual(app._last_text["#brand"].plain.count("\n"), lines)
            app._image_origin = (0, 0, "@0")
            app._paint_brand()
            await pilot.click("#brand", offset=(10, 1))
            navigated.assert_not_called()
            driver = Mock()
            with (patch.object(app, "_driver", driver),
                  patch.object(ui.SidebarApp, "is_headless", new_callable=PropertyMock, return_value=False)):
                app._paint_images()
                self.assertEqual(driver.write.call_count, 10)
                app._paint_images()
                self.assertEqual(driver.write.call_count, 10)
                app._release_images()
                self.assertIn(ui.delete_sequence(app._logo_id), [call.args[0] for call in driver.write.call_args_list])
                self.assertFalse(app._logo_uploaded)
            await pilot.resize_terminal(12, 12)
            self.assertIn("One", app._last_text["#brand"].plain)
            self.assertNotIn(PLACEHOLDER, app._last_text["#brand"].plain)
            self.assertGreater(app.query_one("#scroll").size.height, 0)

    def test_layout_completion_invalidates_scans_even_after_partial_failure(self):
        for kind, error in (("navigate", None), ("navigate", RuntimeError("partial")),
                            ("new", RuntimeError("partial"))):
            with self.subTest(kind=kind, error=error):
                model = tui.SidebarModel(lambda: ())
                app = ui.SidebarApp(model)
                app._intent = 3  # 后续用户意图已排队，不得退回已完成任务的旧版本。
                app._cached_window = ("old", 1)
                app._job_results.put((kind, make_session(), 1, None, error))
                with (patch.object(ui.SidebarApp, "is_running", new_callable=PropertyMock, return_value=True),
                      patch.object(app, "_tick"), patch.object(app, "_paint")):
                    app._finish_job()
                self.assertGreater(app._intent, 3)
                self.assertIsNone(app._cached_window)

    def test_scan_started_during_new_session_cannot_trigger_replacement_after_completion(self):
        old_tree = build_tree([make_session("%0")])
        new_session = replace(make_session("%new"), session_name="new", window_index=1)
        new_tree = build_tree([make_session("%0"), new_session])
        model = tui.SidebarModel(lambda: new_tree)
        model.tree = old_tree
        model.loading = False
        navigated = Mock()
        model.on_navigate = navigated
        model.sync_host = lambda: "%new"
        model.sidebar_window = lambda: ("new", 1)
        app = ui.SidebarApp(model)
        # 操作已排队，扫描拿到新建前的树，但携带最新意图版本。
        app._intent = 1
        app._scan_pending = True
        app._job_results.put(("new", "/project", 1, "new", None))
        with (patch.object(ui.SidebarApp, "is_running", new_callable=PropertyMock, return_value=True),
              patch.object(app, "_tick") as rescan,
              patch.object(app, "_sync_host"),
              patch.object(app, "_paint_foot"),
              patch.object(app, "_paint")):
            app._finish_job()
            # 新建完成后，宿主观察先返回新窗口，旧扫描随后到达。
            app._job_results.put(("host", None, app._intent, ("%new", None, ("new", 1)), None))
            app._finish_job()
            app._scan_results.put((old_tree, None, 1))
            app._finish_scan()
            self.assertEqual(model.generation, 0)
            self.assertEqual(model.tree, old_tree)
            self.assertFalse(app._jobs)
            self.assertEqual(app._cached_window, ("new", 1))
            navigated.assert_not_called()
            self.assertGreaterEqual(rescan.call_count, 2)
            # 完成后的新扫描才可用于判断补位，并能接受新会话。
            app._scan_pending = True
            app._scan_results.put((new_tree, None, app._intent))
            app._finish_scan()
            self.assertEqual(model.tree, new_tree)
            self.assertEqual(model.active_pane, "%new")
            self.assertFalse(app._jobs)
            navigated.assert_not_called()

    def test_old_scan_after_operation_cannot_replace_new_tree_or_trigger_exit(self):
        tree = build_tree([make_session()])
        model = tui.SidebarModel(lambda: tree)
        model.tree = tree
        model.loading = False
        model.sidebar_window = lambda: ("s0", 1)
        model.on_navigate = Mock()
        app = ui.SidebarApp(model)
        app._cached_window = ("s0", 1)
        app._scan_pending = True
        app._intent = 1
        app._scan_results.put(((), None, 0))
        with (patch.object(ui.SidebarApp, "is_running", new_callable=PropertyMock, return_value=True),
              patch.object(app, "_tick") as rescan,
              patch.object(app, "action_quit") as quit_app):
            app._finish_scan()
            rescan.assert_called_once()
            quit_app.assert_not_called()
        self.assertEqual(model.tree, tree)
        self.assertEqual(model.generation, 0)
        self.assertFalse(app._quitting)

    async def test_slow_host_keeps_browsing_responsive_and_discards_old_observation(self):
        entered, release = Event(), Event()
        tree = build_tree([make_session("%0"), make_session("%1")])
        def host():
            entered.set()
            release.wait(5)
            return "%0"
        model = tui.SidebarModel(lambda: tree, 60)
        model.sync_host = host
        model.active_pane = "%0"
        calls = []
        model.on_navigate = lambda session: calls.append(session.backend_target)
        app = ui.SidebarApp(model)
        try:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                self.assertTrue(entered.is_set())
                model.select(1)
                start = time.perf_counter()
                app.action_cursor_down()
                app.action_activate()
                self.assertLess(time.perf_counter() - start, 0.1)
                self.assertEqual(model.current_session().backend_target, "%1")
                self.assertEqual(model.active_pane, "%0")
                app._sync_host()
                self.assertEqual(calls, [])
                release.set()
                for _ in range(100):
                    app._finish_job()
                    if calls:
                        break
                    await asyncio.sleep(0.01)
                for _ in range(100):
                    app._finish_job()
                    if model.active_pane == "%1":
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(calls, ["%1"])
                self.assertEqual(model.active_pane, "%1")
                self.assertEqual(model.current_session().backend_target, "%1")
        finally:
            release.set()

    async def test_navigation_is_serial_and_coalesces_pending_clicks(self):
        entered, release = Event(), Event()
        tree = build_tree([make_session(f"%{i}") for i in range(3)])
        calls = []
        def navigate(session):
            calls.append(session.backend_target)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
        model = tui.SidebarModel(lambda: tree, 60)
        model.on_navigate = navigate
        model.can_navigate = True
        model.active_pane = "%2"
        app = ui.SidebarApp(model)
        try:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                model.select(1)
                app.action_activate()
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(0.01)
                self.assertTrue(entered.is_set())
                model.select(2)
                app.action_activate()
                model.select(3)
                app.action_activate()
                self.assertEqual(calls, ["%0"])
                self.assertEqual(model.active_pane, "%2")
                self.assertEqual(len(app._jobs), 1)
                release.set()
                for _ in range(100):
                    app._finish_job()
                    if not app._job_pending and not app._jobs: break
                    await asyncio.sleep(0.01)
                self.assertEqual(calls, ["%0", "%2"])
                self.assertEqual(model.active_pane, "%2")
                self.assertIsNone(app._navigating)
        finally:
            release.set()

    async def test_failed_navigation_preserves_current_and_quit_cancels_pending(self):
        entered, release = Event(), Event()
        def navigate(session):
            entered.set()
            release.wait(5)
            raise RuntimeError("target closed")
        callback = Mock(side_effect=navigate)
        model = tui.SidebarModel(lambda: build_tree([make_session("%0"), make_session("%1")]), 60)
        model.on_navigate = callback
        model.active_pane = "%0"
        app = ui.SidebarApp(model)
        try:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                model.select(2)
                app.action_activate()
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(0.01)
                release.set()
                for _ in range(100):
                    app._finish_job()
                    if not app._job_pending: break
                    await asyncio.sleep(0.01)
                self.assertEqual(model.active_pane, "%0")
                self.assertIn("target closed", app._operation_error)
                self.assertIn("target closed", app._last_text["#foot"].plain)
                release.clear()
                entered.clear()
                app.action_activate()
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(0.01)
                self.assertTrue(entered.is_set())
                model.select(1)
                app.action_activate()
                app.action_quit()
                release.set()
                app._job_thread.join(2)
                self.assertEqual(callback.call_count, 2)
                self.assertFalse(app._jobs)
                self.assertTrue(app._stopping.is_set())
        finally:
            release.set()

    def test_current_highlight_is_independent_of_browsing_and_focus(self):
        row = sample_rows()[1]
        opened = ui.session_line(row, False, 30, current=True)
        browsed = ui.session_line(row, True, 30, current=False)
        self.assertTrue(opened.plain.startswith("▎"))
        self.assertTrue(browsed.plain.startswith("›"))
        self.assertNotEqual(opened, browsed)

    async def test_mouse_timeout_retries_after_delay_and_clears_notice(self):
        guard = Mock(side_effect=[ui.MouseQueryTimeout("查询超时"),
                                  ui.MouseQueryTimeout("查询超时"), False])
        model = tui.SidebarModel(lambda: build_tree([make_session()]))
        app = ui.SidebarApp(model, mouse_guard=guard)
        with patch("agent_tree.ui.monotonic", return_value=100) as clock:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                self.assertIs(app.mouse_guard, guard)
                self.assertIn("30 秒后重试", app._mouse_error)
                model.reload()
                app._paint_foot()
                self.assertIn("30 秒后重试", app._last_text["#foot"].plain)
                clock.return_value = 129
                app._check_mouse_host()
                self.assertEqual(guard.call_count, 1)
                clock.return_value = 130
                app._check_mouse_host()
                await pilot.pause()
                self.assertEqual(guard.call_count, 2)
                self.assertEqual(app._mouse_retry_at, 160)
                clock.return_value = 160
                app._check_mouse_host()
                await pilot.pause()
                self.assertEqual(guard.call_count, 3)
                self.assertEqual(app._mouse_error, "")
                self.assertEqual(app._mouse_retry_at, 0)
                self.assertNotIn("查询超时", app._last_text["#foot"].plain)

    async def test_blocked_mouse_host_keeps_input_responsive_and_stops_on_quit(self):
        entered, release = Event(), Event()
        def check(stopping):
            entered.set()
            release.wait(30)
            return not stopping.is_set()
        guard = Mock(side_effect=check)
        model = tui.SidebarModel(lambda: build_tree([make_session()]))
        app = ui.SidebarApp(model, mouse_guard=guard)
        try:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                self.assertTrue(entered.is_set())
                app._check_mouse_host()
                app._check_mouse_host()
                self.assertEqual(guard.call_count, 1)
                await pilot.press("down")
                self.assertEqual(model.selected, 1)
                await pilot.press("q")
                self.assertTrue(app._mouse_stopping.is_set())
                self.assertFalse(release.is_set())
                app._mouse_results.put(RuntimeError("late failure"))
                app._finish_scan()
                self.assertEqual(app._mouse_error, "")
        finally:
            release.set()

    async def test_mouse_host_permission_failure_disables_retries_and_keeps_notice(self):
        guard = Mock(side_effect=RuntimeError("脚本访问失败"))
        model = tui.SidebarModel(lambda: build_tree([make_session()]))
        app = ui.SidebarApp(model, mouse_guard=guard)
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            self.assertIsNone(app.mouse_guard)
            self.assertIn("已停用自动恢复", app._mouse_error)
            model.reload()
            app._paint_foot()
            self.assertIn("已停用自动恢复", app._last_text["#foot"].plain)
            app._check_mouse_host()
            self.assertEqual(guard.call_count, 1)

    def test_timers_ignore_scan_results_after_app_stops(self):
        loader = Mock(return_value=build_tree([make_session()]))
        model = tui.SidebarModel(loader)
        app = ui.SidebarApp(model)
        app._scan_results.put((loader.return_value, None))
        app._finish_scan()
        app._tick()
        app._sync_host()
        app._pulse_working()
        loader.assert_not_called()
        self.assertEqual(model.tree, ())
        self.assertEqual(model.generation, 0)

    async def test_blocked_scan_keeps_input_responsive_and_never_overlaps(self):
        entered, release = Event(), Event()
        tree = build_tree([make_session()])
        def load():
            entered.set()
            release.wait(30)
            return tree
        loader = Mock(side_effect=load)
        model = tui.SidebarModel(loader)
        model.tree = tree
        model.loading = False
        app = ui.SidebarApp(model)
        try:
            async with app.run_test(size=(30, 16)) as pilot:
                await pilot.pause()
                self.assertTrue(entered.is_set())
                app._tick()
                app._tick()
                self.assertEqual(loader.call_count, 1)
                await pilot.press("down")
                self.assertEqual(model.selected, 1)
                model.select(0)
                await pilot.press("space")
                self.assertTrue(model.collapsed)
                await pilot.press("q")
                self.assertFalse(release.is_set())
        finally:
            release.set()

    async def test_failed_scan_retains_tree_and_recovers(self):
        tree = build_tree([make_session()])
        # 周期扫描可发生多次：首轮失败，此后保持可恢复的稳定快照。
        attempts = iter([RuntimeError("scan failed")])
        def load():
            result = next(attempts, tree)
            if isinstance(result, Exception):
                raise result
            return result
        loader = Mock(side_effect=load)
        model = tui.SidebarModel(loader)
        model.tree = tree
        app = ui.SidebarApp(model)
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            self.assertEqual(model.tree, tree)
            self.assertIn("scan failed", model.message)
            app._tick()
            await pilot.pause()
            self.assertEqual(model.message, "")
            self.assertEqual(model.tree, tree)

    async def test_only_working_dot_pulses_without_navigation_or_reload(self):
        session = replace(make_session(), state=PaneState.WORKING)
        loader = Mock(side_effect=lambda: build_tree([session]))
        model = tui.SidebarModel(loader)
        app = ui.SidebarApp(model)
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            model.select(1)
            calls = loader.call_count
            before = app._working_bright
            app._pulse_working()
            self.assertNotEqual(app._working_bright, before)
            self.assertEqual(loader.call_count, calls)
            self.assertEqual(model.selected, 1)
            row = model.rows()[1]
            bright = ui.session_line(row, True, 30, working_bright=True)
            dim = ui.session_line(row, True, 30, working_bright=False)
            self.assertEqual(bright.plain, dim.plain)
            self.assertNotEqual(bright.spans, dim.spans)
            for state in (PaneState.IDLE, PaneState.BLOCKED, PaneState.UNKNOWN):
                session = replace(session, state=state)
                model.reload()
                before = app._working_bright
                app._pulse_working()
                self.assertEqual(app._working_bright, before)
                row = model.rows()[1]
                self.assertEqual(ui.session_line(row, True, 30, working_bright=True),
                                 ui.session_line(row, True, 30, working_bright=False))

    async def test_state_refresh_keeps_selection_and_image_columns(self):
        session = make_session()
        model = tui.SidebarModel(lambda: build_tree([session]))
        app = ui.SidebarApp(model, image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            model.select(1)
            column = ui.session_icon_column(model.rows()[1], 30)
            for state in (PaneState.WORKING, PaneState.BLOCKED, PaneState.IDLE, PaneState.UNKNOWN):
                session = replace(session, state=state)
                model.reload()
                app._paint_body()
                await pilot.pause()
                self.assertEqual(model.selected, 1)
                self.assertIn("●", app.query_one("#body").render().plain)
                row = model.rows()[1]
                line = ui.session_line(row, True, 30, image_id=123)
                self.assertEqual(cell_len(line.plain.split("●")[0]), column + ui.ICON_WIDTH + 2 + cell_len(row.session.display_name))
                from rich.console import Console
                color = {PaneState.WORKING: ui.SELECT_ACCENT, PaneState.BLOCKED: "#e3b341",
                         PaneState.IDLE: ui.ACCENT, PaneState.UNKNOWN: ui.DIM}[state]
                self.assertEqual(line.get_style_at_offset(Console(), line.plain.index("●")).color.triplet.hex, color)
                self.assertNotIn("●", ui.session_spacer(row, 30, 123, 0).plain)
                self.assertEqual(ui.session_icon_column(model.rows()[1], 30), column)

    async def test_selected_image_row_background_covers_all_three_full_width_lines(self):
        model = tui.SidebarModel(lambda: build_tree([
            make_session(agent=AgentKind.CODEBUDDY, display="CodeBuddy", marker="B"),
            make_session("%1"),
        ]))
        app = ui.SidebarApp(model, image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(40, 16)) as pilot:
            await pilot.pause()
            model.select(1)
            app._paint_body()
            await pilot.pause()
            body = app.query_one("#body")
            start = app._line_rows.index(model.selected)
            for y in range(start, start + 3):
                strip = body.render_line(y)
                self.assertEqual(strip.cell_length, 40)
                x = 0
                for segment in strip:
                    length = cell_len(segment.text)
                    rounded_edge = x == 0 or x >= 38
                    self.assertEqual(segment.style.bgcolor.name, ui.BG if rounded_edge else ui.SEL_BG)
                    if PLACEHOLDER in segment.text:
                        self.assertIn(segment.style.color.get_truecolor(),
                                      [(i >> 16, (i >> 8) & 255, i & 255)
                                       for i in (*app._image_ids.values(), *app._decoration_ids.values())])
                    x += length
            self.assertNotEqual(list(body.render_line(start + 3))[-1].style.bgcolor.name,
                                ui.SEL_BG)

    async def test_host_focus_does_not_redraw_text_or_upload_png_again(self):
        app = ui.SidebarApp(tui.SidebarModel(lambda: build_tree([make_session()])),
                            image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            frames = []
            display = app._display
            driver = Mock()
            paint_images = app._paint_images

            def write_images():
                with patch.object(app, "_driver", driver), patch.object(
                    ui.SidebarApp, "is_headless", new_callable=PropertyMock, return_value=False
                ):
                    paint_images()

            def record(screen, frame):
                if frame is not None:
                    frames.append(frame)
                display(screen, frame)

            write_images()
            self.assertEqual(driver.write.call_count, 9)
            driver.reset_mock()
            with patch.object(app, "_paint_images", side_effect=write_images), patch.object(
                app, "_display", side_effect=record
            ):
                for focus in (False, True, False, True):
                    app.post_message(ui.events.AppFocus() if focus else ui.events.AppBlur())
                    await pilot.pause()
                    self.assertEqual(app.app_focus, focus)
            driver.write.assert_not_called()
            self.assertEqual(frames, [], "宿主焦点变化不需要应用文字重绘")
            await pilot.press("j")
            self.assertIsNotNone(app.model.rows()[app.model.selected].session)

    async def test_mouse_hover_does_not_redraw_icons(self):
        app = ui.SidebarApp(tui.SidebarModel(lambda: build_tree([make_session()])),
                            image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(30, 16)) as pilot:
            await pilot.pause()
            frames = []
            display = app._display

            def record(screen, frame):
                if frame is not None:
                    frames.append(frame)
                display(screen, frame)

            with patch.object(app, "_display", side_effect=record):
                for x, y in [(8, 0), (2, 1), (8, 2), (12, 2), (8, 3),
                             (8, 5), (8, 3), (12, 2), (8, 2), (8, 0)]:
                    await pilot.hover("#body", offset=(x, y))
                    await pilot.pause(0.05)
                await pilot.hover("#foot", offset=(2, 1))
                await pilot.hover("#body", offset=(8, 2))
                await pilot.pause()
            self.assertEqual(frames, [], "鼠标悬停不应触发文字重绘")

    async def test_png_is_uploaded_before_first_frame_and_never_resent_on_redraw(self):
        app = ui.SidebarApp(tui.SidebarModel(lambda: build_tree([make_session()])),
                            image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(30, 12)) as pilot:
            await pilot.pause()
            driver = Mock()
            with patch.object(app, "_driver", driver), patch.object(ui.SidebarApp, "is_headless", new_callable=PropertyMock, return_value=False):
                frame = SimpleNamespace(spans=[(5, 0, 30)])
                with patch.object(ui.App, "_display", side_effect=lambda *args: driver.write("TEXT_FRAME")):
                    app._display(app.screen, frame)
                    writes = [call.args[0] for call in driver.write.call_args_list]
                    self.assertEqual(len(writes), 10)
                    self.assertTrue(all("a=t,f=100" in write for write in writes[:9]))
                    self.assertEqual(writes[9], "TEXT_FRAME")
                    driver.reset_mock()
                    app._display(app.screen, frame)
                    self.assertEqual([call.args[0] for call in driver.write.call_args_list], ["TEXT_FRAME"])

    async def test_image_positions_follow_scroll_fold_visibility_and_narrow_width(self):
        tree = build_tree([make_session(f"%{i}") for i in range(30)])
        model = tui.SidebarModel(lambda: tree)
        origin = [(4, 2, "@0")]
        app = ui.SidebarApp(model, image_origin=lambda: origin[0])
        async with app.run_test(size=(30, 12)) as pilot:
            await pilot.pause()
            text = app._last_text["#body"]
            self.assertEqual(text.plain.count(PLACEHOLDER), 30 * 2 + 2)
            lines = text.split("\n")
            self.assertEqual(cell_len(lines[2].plain.split(PLACEHOLDER)[0]), ui.ICON_COLUMN)
            self.assertNotIn(PLACEHOLDER, lines[1].plain)
            self.assertNotIn(PLACEHOLDER, lines[3].plain)
            self.assertIn("Codex", lines[2].plain)
            model.select(len(model.rows()) - 1)
            app._paint_body()
            await pilot.pause()
            self.assertGreater(app.query_one("#scroll").scroll_y, 0)
            model.collapsed.add(model.tree[0].key)
            app._paint_body()
            await pilot.pause()
            self.assertEqual(app._last_text["#body"].plain.count(PLACEHOLDER), 2)
            model.collapsed.clear()
            app._paint_body()
            origin[0] = None
            app._sync_host()
            await pilot.pause()
            self.assertNotIn(ui.placeholder_row(1, 0)[0], app._last_text["#body"].plain)
            origin[0] = (0, 0, "@1")
            app._sync_host()
            await pilot.pause()
            self.assertIn(ui.placeholder_row(1, 0)[0], app._last_text["#body"].plain)
            await pilot.resize_terminal(8, 12)
            self.assertNotIn(ui.placeholder_row(1, 0)[0], app._last_text["#body"].plain)

    async def test_png_cache_survives_idle_move_and_only_owned_ids_are_released(self):
        app = ui.SidebarApp(tui.SidebarModel(lambda: build_tree([make_session()])),
                            image_origin=lambda: (0, 0, "@0"))
        async with app.run_test(size=(30, 12)) as pilot:
            await pilot.pause()
            driver = Mock()
            with patch.object(app, "_driver", driver), patch.object(ui.SidebarApp, "is_headless", new_callable=PropertyMock, return_value=False):
                app._paint_images()
                self.assertEqual(driver.write.call_count, 9)
                app._paint_images()
                app._image_origin = (0, 1, "@0")
                app._paint_images()
                app._image_origin = (0, 1, "@1")
                app._paint_images()
                self.assertEqual(driver.write.call_count, 9)
                driver.reset_mock()
                app._release_images()
                self.assertEqual(driver.write.call_count, 9)
                for call in driver.write.call_args_list:
                    self.assertIn("a=d,d=I,i=", call.args[0])
                self.assertEqual(app._uploaded_images, set())

    async def test_unchanged_snapshot_does_not_invalidate_text_frame(self):
        model = tui.SidebarModel(lambda: build_tree([make_session()]))
        app = ui.SidebarApp(model)
        async with app.run_test(size=(30, 12)) as pilot:
            await pilot.pause()
            body = app.query_one("#body")
            with patch.object(body, "update", wraps=body.update) as update:
                app._tick()
                update.assert_not_called()

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
            await pilot.pause()
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
            await pilot.click("#body", offset=(8, 5))
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
    def test_tree_spine_and_detail_branch_are_continuous_and_last_child_ends(self):
        rows = sample_rows()
        for row in rows[1:]:
            top = ui.session_spacer(row, 40, 42, 0).plain
            main = ui.session_line(row, False, 40, image_id=42).plain
            bottom = ui.session_spacer(row, 40, 42, 2).plain
            self.assertEqual(top[3], "│")
            self.assertEqual(main[3], "└" if row.last else "├")
            self.assertIn("└─── ", bottom)
            self.assertEqual(bottom[3], " " if row.last else "│")
            self.assertNotIn(PLACEHOLDER, top)
            self.assertNotIn(PLACEHOLDER, bottom)

    def test_group_uses_image_folder_and_branch_without_font_surrogates(self):
        row = replace(sample_rows()[0], group=replace(sample_rows()[0].group, branch="master"))
        line = ui.group_line(row, set(), False, 50, folder_id=41, branch_id=42)
        self.assertEqual(line.plain.count(PLACEHOLDER), 4)
        self.assertIn("◖", line.plain)
        self.assertIn("◗", line.plain)
        self.assertNotIn("▱", line.plain)
        self.assertNotIn("⑂", line.plain)
        self.assertIn("master", line.plain)

    def test_codebuddy_image_and_character_fallback(self):
        rows = tui.visible_rows(build_tree([make_session(agent=AgentKind.CODEBUDDY,
                                                  display="CodeBuddy", marker="B")]), set())
        line = ui.session_line(rows[1], False, 30)
        self.assertIn("CodeBuddy", line.plain)
        self.assertIn(" B", line.plain)
        self.assertNotIn(PLACEHOLDER, line.plain)
        image = ui.session_line(rows[1], False, 30, image_icons=True, image_id=42)
        self.assertEqual(image.plain.count(PLACEHOLDER), 2)
        self.assertIn("CodeBuddy", image.plain)

    def test_pi_image_and_character_fallback(self):
        rows = tui.visible_rows(build_tree([make_session(agent=AgentKind.PI,
                                                  display="Pi", marker="P")]), set())
        line = ui.session_line(rows[1], False, 30)
        self.assertIn("Pi", line.plain)
        self.assertIn(" P", line.plain)
        self.assertNotIn(PLACEHOLDER, line.plain)
        image = ui.session_line(rows[1], False, 30, image_icons=True, image_id=42)
        self.assertEqual(image.plain.count(PLACEHOLDER), 2)
        self.assertIn("Pi", image.plain)

    def test_five_image_ids_stay_within_protocol_limit(self):
        with patch.object(ui.secrets, "randbelow", side_effect=lambda limit: limit - 1):
            app = ui.SidebarApp(tui.SidebarModel(lambda: build_tree([])))
        self.assertIn(AgentKind.CODEBUDDY, app._image_ids)
        self.assertEqual(len(set(app._image_ids.values())), 5)
        self.assertEqual(max(app._image_ids.values()), 0xFFFFFA)
        self.assertEqual(app._logo_id, 0xFFFFFB)
        self.assertEqual(max(app._decoration_ids.values()), 0xFFFFFF)
        self.assertNotIn(app._logo_id, app._image_ids.values())

    def test_image_placeholder_is_four_cells_and_keeps_id_color_when_selected(self):
        row = sample_rows()[1]
        image_id = 0x123456
        from rich.console import Console
        for selected in (False, True):
            line = ui.session_line(row, selected, 20, image_icons=True, image_id=image_id)
            self.assertEqual(line.plain.count(PLACEHOLDER), 2)
            self.assertEqual(cell_len(line.plain), 20)
            style = line.get_style_at_offset(Console(), line.plain.index(PLACEHOLDER))
            self.assertEqual(style.color.get_truecolor(), (0x12, 0x34, 0x56))
        self.assertNotIn(PLACEHOLDER, ui.session_line(row, False, 8, image_icons=True,
                                                   image_id=image_id).plain)

    def test_image_slots_and_character_fallback_preserve_names_and_width(self):
        rows = sample_rows()
        for row in rows[1:]:
            image = ui.session_line(row, True, 20, image_icons=True)
            fallback = ui.session_line(row, False, 20)
            column = ui.session_icon_column(row, 20)
            self.assertEqual(image.plain[column:column + ui.ICON_WIDTH], " " * ui.ICON_WIDTH)
            self.assertTrue(image.plain[ui.ICON_COLUMN + ui.ICON_WIDTH + 1:].startswith(row.session.display_name))
            self.assertIn(row.session.marker, fallback.plain[column:column + ui.ICON_WIDTH])
            self.assertIn(row.session.display_name, image.plain)
            self.assertEqual(cell_len(image.plain), 20)
        unknown = tui.visible_rows(build_tree([make_session(agent=AgentKind.UNKNOWN, display="未知", marker="?")]), set())[1]
        self.assertIn("?", ui.session_line(unknown, False, 20, image_icons=True).plain)

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
        line = ui.group_line(rows[0], set(), False, 65)
        self.assertIn("~/workspace", line.plain)

    def test_collapsed_group_uses_collapsed_mark(self):
        rows = sample_rows()
        line = ui.group_line(rows[0], {"/Users/mac/workspace/agent-tree"}, False, 40)
        self.assertTrue(line.plain.startswith(" " + tui.COLLAPSED_MARK))

    def test_session_lines_use_tree_connectors(self):
        rows = sample_rows()
        first = ui.session_line(rows[1], False, 40)
        last = ui.session_line(rows[2], False, 40)
        self.assertTrue(first.plain.startswith("   " + ui.CONNECTOR_MID), repr(first.plain))
        self.assertTrue(last.plain.startswith("   " + ui.CONNECTOR_LAST), repr(last.plain))

    def test_session_name_uses_normal_text_color(self):
        rows = sample_rows()
        codex = ui.session_line(rows[1], False, 40)
        shell = ui.session_line(rows[2], False, 40)
        self.assertIn(
            "bold " + ui.TEXT,
            [str(span.style) for span in codex.spans if codex.plain[span.start : span.end] == "Codex"],
        )
        self.assertIn(
            "bold " + ui.TEXT,
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
