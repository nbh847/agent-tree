"""基于 textual 的侧栏界面。

与 :mod:`agent_tree.tui` 的纯逻辑分离：本模块只负责把 :class:`~agent_tree.tui.SidebarModel`
的行渲染成带样式的文本、处理按键与鼠标，并驱动定时刷新。

注意：textual 需要终端对它的初始化查询作出应答，因此侧栏所在的 pane 必须处于
「有 client 附着」的 session 中；这与发现范围（只看附着会话）一致。
"""

from __future__ import annotations

import os
import secrets
import sys
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import Reactive
from textual.widgets import Static

from .icons import ICON_COLUMN, ICON_HEIGHT, ICON_WIDTH, delete_sequence, image_sequence, placeholder_row
from .model import AgentKind, PaneState
from .tmux import TmuxError
from .tui import (
    COLLAPSED_MARK,
    EXPANDED_MARK,
    HINT_BROWSE,
    HINT_NAVIGATE,
    Row,
    SidebarModel,
)

# 参考图取自暗色系：近黑底、灰次要文字、青绿强调。
BG = "#111111"
PANEL = "#161616"
DIM = "#6e7681"
FAINT = "#484f58"
TEXT = "#c9d1d9"
BRIGHT = "#e6edf3"
ACCENT = "#7ee787"
SELECT_ACCENT = "#82aaff"
ERROR = "#f85149"
SEL_BG = "#21262d"

#: 树形连接线：非末项与末项。
CONNECTOR_MID = "├─ "
CONNECTOR_LAST = "└─ "

#: 底部提示按宽度逐级降级：优先完整说明，放不下再退到更短的版本。
FOOT_NAVIGATE_LADDER = (
    HINT_NAVIGATE,
    "↑↓ 选择 · Enter 进入 · n 新建 · q 退出",
    "↑↓ 选择 · Enter 进入 · q 退出",
    "q 退出",
)
FOOT_BROWSE_LADDER = (
    HINT_BROWSE,
    "↑↓ 选择 · 空格 折叠 · q 退出",
    "q 退出",
)

CSS = f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}
#title {{
    height: 3;
    background: {BG};
    color: {DIM};
    padding: 1 1;
}}
#scroll {{
    height: 1fr;
    scrollbar-size-vertical: 0;
}}
#body {{
    padding: 0;
    width: 1fr;
    /* 行已按列宽截断；换行处理会误裁图片组合标记后的行尾空格。 */
    text-wrap: nowrap;
    text-overflow: clip;
}}
#foot {{
    height: 3;
    background: {PANEL};
    color: {DIM};
    padding: 1 1;
}}
"""


def _short_path(path: str) -> str:
    """目录行的父级路径提示：家目录缩写为 ``~``，只保留父级部分。"""
    if not path:
        return ""
    home = os.path.expanduser("~")
    if home and (path == home or path.startswith(home + "/")):
        path = "~" + path[len(home) :]
    parent = path.rpartition("/")[0]
    return "" if parent == "~" else parent


def _pad(line: Text, right: str, width: int, right_style: str = DIM) -> None:
    """把行补到给定列宽，右对齐文本贴右边；放不下时截断左侧而不是折行。"""
    right_width = cell_len(right)
    budget = width - right_width - 1 if right else width
    if cell_len(line.plain) > budget:
        line.truncate(max(1, budget), overflow="ellipsis")
    gap = max(0, width - cell_len(line.plain) - right_width)
    line.append(" " * gap)
    if right:
        line.append(right, style=right_style)


def group_line(row: Row, collapsed: set[str], selected: bool, width: int, *, can_create: bool = False) -> Text:
    """目录行：折叠标记 + 方括号目录名 + 暗淡父级路径 + 右对齐会话数。"""
    group = row.group
    button = can_create and bool(group.display_path) and width >= 8
    content_width = width - 4 if button else width
    line = Text()
    mark = COLLAPSED_MARK if group.key in collapsed else EXPANDED_MARK
    line.append(f"{mark} ", style=FAINT)
    line.append(f"[{group.label}]", style=f"bold {ACCENT}")
    hint = _short_path(group.display_path)
    if hint and cell_len(line.plain) + cell_len(hint) + len(str(len(group.sessions))) + 3 <= content_width:
        line.append(f"  {hint}", style=DIM)
    _pad(line, str(len(group.sessions)), content_width)
    if button:
        line.append(" [+]", style=f"bold {SELECT_ACCENT}")
    return _highlight(line, selected, width)


def session_icon_column(row: Row, width: int) -> int | None:
    """图标紧随可见名称，窄栏为名称保留至少三列。"""
    status_width = 2 if row.session.agent not in {AgentKind.SHELL, AgentKind.UNKNOWN} else 0
    if width < ICON_COLUMN + ICON_WIDTH + 4 + status_width:
        return None
    name = Text(row.session.display_name)
    name.truncate(width - ICON_COLUMN - ICON_WIDTH - 1 - status_width, overflow="ellipsis")
    return ICON_COLUMN + cell_len(name.plain) + 1


def session_line(row: Row, selected: bool, width: int, *, image_icons: bool = False,
                 image_id: int | None = None, working_bright: bool = True) -> Text:
    """会话行：连接线 + 名称 + 右侧图标／字符标识。"""
    session = row.session
    assert session is not None
    line = Text()
    line.append("  " + (CONNECTOR_LAST if row.last else CONNECTOR_MID), style=FAINT)
    column = session_icon_column(row, width)
    name = Text(session.display_name, style=TEXT)
    if column is not None:
        name.truncate(column - ICON_COLUMN - 1, overflow="ellipsis")
    line.append_text(name)
    if column is not None:
        marker = (" " * ICON_WIDTH if image_icons and session.agent in (
            AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI, AgentKind.SHELL)
                  else session.marker.ljust(ICON_WIDTH))
        line.append(" ", style=DIM)
        if image_id is not None:
            line.append(placeholder_row(image_id, 1), style=f"#{image_id:06x} on {BG}")
        else:
            line.append(marker, style=DIM)
        if session.agent not in {AgentKind.SHELL, AgentKind.UNKNOWN}:
            color = {PaneState.WORKING: SELECT_ACCENT, PaneState.BLOCKED: "#e3b341",
                     PaneState.IDLE: ACCENT, PaneState.UNKNOWN: DIM}[session.state]
            if session.state is PaneState.WORKING and not working_bright:
                color = "#405675"
            line.append(" ", style=DIM)
            line.append("●", style=color)
    _pad(line, "", width)
    return _highlight(line, selected, width)


def session_spacer(row: Row, width: int, image_id: int | None, canvas_row: int, *, selected: bool = False) -> Text:
    line = Text("   " if canvas_row == 2 and row.last else "  │", style=FAINT)
    column = session_icon_column(row, width)
    if image_id is not None and column is not None:
        line.append(" " * max(0, column - cell_len(line.plain)))
        line.append(placeholder_row(image_id, canvas_row), style=f"#{image_id:06x} on {BG}")
    _pad(line, "", width)
    return _highlight(line, selected, width)


def _highlight(line: Text, selected: bool, width: int) -> Text:
    """选中行使用低调的浅色背景块，并把整行补满背景。"""
    if not selected:
        return line
    # 用蓝色竖线标出当前位置，保留树形连接线与整行的列宽。
    line = Text("▎", style=SELECT_ACCENT) + line[1:]
    line.stylize(f"on {SEL_BG}")
    missing = width - cell_len(line.plain)
    if missing > 0:
        line.append(" " * missing, style=f"on {SEL_BG}")
    return line


def foot_text(can_navigate: bool, width: int) -> str:
    """按可用宽度挑选底部提示：完整 → 紧凑 → 只留退出键。"""
    ladder = FOOT_NAVIGATE_LADDER if can_navigate else FOOT_BROWSE_LADDER
    for text in ladder:
        if cell_len(text) + 1 <= width:
            return text
    return ladder[-1]


class SidebarApp(App):
    """textual 侧栏：标题栏 + 树内容区 + 底部操作条。"""

    CSS = CSS
    ALLOW_SELECT = False  # 这是导航列表，普通点击不启动 Textual 文本选区。
    # 两侧 pane 切换不改变侧栏外观；保留框架焦点处理，取消整屏自动重绘。
    app_focus = Reactive(True, compute=False, repaint=False)
    BINDINGS = [
        Binding("q", "quit", "退出", show=False),
        Binding("up,k", "cursor_up", "上移", show=False),
        Binding("down,j", "cursor_down", "下移", show=False),
        Binding("enter", "activate", "切换", show=False),
        Binding("n", "new_session", "新建会话", show=False),
        Binding("space", "toggle", "展开/折叠", show=False),
        Binding("left,h", "collapse", "折叠", show=False),
        Binding("l", "expand", "展开", show=False),
        Binding("right,escape", "handoff", "进入目标", show=False),
    ]

    def __init__(self, model: SidebarModel, on_ready: Callable[[], None] | None = None,
                 *, image_origin: Callable[[], tuple[int, int, str] | None] | None = None) -> None:
        super().__init__()
        self.model = model
        # 侧栏旁的用户 pane 全部关闭且无可补位会话时，由模型回调退出。
        model.on_exit = self.action_quit
        self.on_ready = on_ready
        self._line_rows: list[int | None] = []
        self._viewport_width: int | None = None
        self.image_origin = image_origin
        self._image_origin: tuple[int, int, str] | None = None
        self._last_text: dict[str, Text] = {}
        first_id = secrets.randbelow(0xFFFFFB) + 1
        self._image_ids = {kind: first_id + index for index, kind in enumerate(
            (AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI, AgentKind.SHELL))}
        self._uploaded_images: set[AgentKind] = set()
        self._working_bright = True
        self._scan_pending = False
        self._scan_results = Queue()
        self._quitting = False

    # ---- 布局 ----

    def compose(self) -> ComposeResult:
        # 没有可点击链接；默认链接悬停会随文字样式变化重绘整个 Static。
        title, body, foot = (Static(id=name) for name in ("title", "body", "foot"))
        for widget in (title, body, foot):
            widget.auto_links = False
        yield title
        scroll = VerticalScroll(body, id="scroll")
        scroll.can_focus = False  # 按键由 App 绑定处理，无需点击时切换控件焦点。
        yield scroll
        yield foot

    def on_mount(self) -> None:
        # 先画出占位帧，再执行较慢的宿主检查与首次扫描。
        self._paint()
        if self.on_ready is not None:
            try:
                self.on_ready()
            except TmuxError as exc:
                self.model.message = str(exc)
        self._tick()
        if self.image_origin is not None:
            self._image_origin = self._read_image_origin()
        self._paint()
        self.set_interval(self.model.refresh_seconds, self._tick)
        self.set_interval(0.25, self._sync_host)
        self.set_interval(0.6, self._pulse_working)
        self.set_interval(0.05, self._finish_scan)

    def _pulse_working(self) -> None:
        """仅运行中的状态点闪动；不触发发现、导航或图片上传。"""
        if not self.is_running or self._quitting:
            return
        if any(row.session is not None and row.session.state is PaneState.WORKING
               for row in self.model.rows()):
            self._working_bright = not self._working_bright
            self._paint_body()

    def on_resize(self, event: events.Resize) -> None:
        self._viewport_width = event.size.width
        self._paint()

    # ---- 刷新 ----

    def _tick(self) -> None:
        if not self.is_running or self._quitting or self._scan_pending:
            return
        self._scan_pending = True
        Thread(target=self._scan, daemon=True).start()

    def _scan(self) -> None:
        # 后台只生成快照；选中、导航和绘制仍在界面线程处理。
        try:
            tree = self.model.fetch_tree()
        except Exception as exc:
            self._scan_results.put((None, exc))
        else:
            self._scan_results.put((tree, None))

    def _finish_scan(self) -> None:
        if not self.is_running or self._quitting:
            return
        try:
            tree, error = self._scan_results.get_nowait()
        except Empty:
            return
        self._scan_pending = False
        def result():
            if error is not None:
                raise error
            return tree
        self.model.reload(result)
        if self.is_running and not self._quitting:
            self._paint()

    def _sync_host(self) -> None:
        if not self.is_running or self._quitting:
            return
        previous = (self.model.selected, set(self.model.collapsed), self.model.message)
        self.model.sync_current()
        old_origin = self._image_origin
        if self.image_origin is not None:
            self._image_origin = self._read_image_origin()
        if previous != (self.model.selected, self.model.collapsed, self.model.message) or old_origin != self._image_origin:
            self._paint()
            return  # 图片缓存随文本帧准备，位置变化由标记重绘。
        # PNG 每个实例只上传一次，宿主重绘保留图片位置标记。
        self._paint_images()

    def _read_image_origin(self) -> tuple[int, int, str] | None:
        try:
            return self.image_origin()
        except TmuxError as exc:
            self.model.message = f"图片宿主查询失败：{exc}"
            return None

    def _display(self, screen, renderable) -> None:
        """先准备 PNG 缓存，再由普通文本帧绘制位置标记。"""
        self._paint_images()
        super()._display(screen, renderable)

    def _paint_images(self) -> None:
        if self._image_origin is None or self._driver is None or self.is_headless:
            return
        pending = self._image_ids.keys() - self._uploaded_images
        for kind in pending:
            self._driver.write(image_sequence(kind, self._image_ids[kind]))
            self._uploaded_images.add(kind)
        if pending:
            self._driver.flush()

    def _release_images(self) -> None:
        if self._driver is not None and not self.is_headless:
            for kind in self._uploaded_images:
                self._driver.write(delete_sequence(self._image_ids[kind]))
            self._driver.flush()
        self._uploaded_images.clear()

    def action_quit(self) -> None:
        self._quitting = True
        self._release_images()
        self.exit()

    def _width(self) -> int:
        return max(1, self._viewport_width or self.size.width or 32)

    def _paint(self) -> None:
        self._paint_title()
        self._paint_body()
        self._paint_foot()

    def _update_text(self, widget_id: str, text: Text) -> None:
        # Static.update 即使内容相同也会重绘；快照未变化时不提交新帧。
        if self._last_text.get(widget_id) != text:
            self._last_text[widget_id] = text
            self.query_one(widget_id, Static).update(text)

    def _paint_title(self) -> None:
        total = sum(len(group.sessions) for group in self.model.tree)
        text = Text()
        text.append("会话", style=f"bold {DIM}")
        _pad(text, str(total), max(1, self.size.width - 2))
        self._update_text("#title", text)

    def _paint_foot(self) -> None:
        if self.model.message:
            self._update_text("#foot", Text(self.model.message, style=ERROR))
            return
        hint = foot_text(self.model.can_navigate, max(1, self._width() - 2))
        self._update_text("#foot", Text(hint, style=DIM))

    def _paint_body(self) -> None:
        width = self._width()
        body = Text()
        self._line_rows = []

        if self.model.loading:
            body.append(" 正在扫描会话…\n", style=DIM)
            self._line_rows.append(None)
        elif not self.model.tree:
            body.append(" 未发现 Agent 会话\n", style=DIM)
            body.append(" 侧栏自身不计入\n", style=DIM)
            self._line_rows.extend([None, None])
        else:
            rows = self.model.rows()
            for index, row in enumerate(rows):
                if row.kind == "group":
                    if self._line_rows:
                        body.append("\n")  # 目录之间留白
                        self._line_rows.append(None)
                    line = group_line(
                        row, self.model.collapsed, index == self.model.selected, width,
                        can_create=self.model.on_new_session is not None,
                    )
                else:
                    image_id = (self._image_ids.get(row.session.agent)
                                if self._image_origin is not None and session_icon_column(row, width) is not None
                                else None)
                    body.append_text(session_spacer(row, width, image_id, 0,
                                                   selected=index == self.model.selected))
                    body.append("\n")
                    self._line_rows.append(index if self._image_origin is not None else None)
                    line = session_line(row, index == self.model.selected, width,
                                        image_icons=self._image_origin is not None, image_id=image_id,
                                        working_bright=self._working_bright)
                body.append_text(line)
                body.append("\n")
                self._line_rows.append(index)
                if row.kind == "session":
                    body.append_text(session_spacer(row, width, image_id, 2,
                                                   selected=index == self.model.selected))
                    body.append("\n")
                    self._line_rows.append(index if self._image_origin is not None else None)

        self._update_text("#body", body)
        if self.model.selected in self._line_rows:
            line = self._line_rows.index(self.model.selected)
            scroll = self.query_one("#scroll", VerticalScroll)
            selected_height = ICON_HEIGHT if self._image_origin is not None else 1
            if line < scroll.scroll_y or line + selected_height > scroll.scroll_y + scroll.size.height:
                scroll.scroll_to(y=max(0, line - scroll.size.height // 2), animate=False)

    # ---- 交互 ----

    def _select(self, index: int) -> None:
        self.model.select(index)
        self._paint_body()
        self.model.activate_current()
        self._paint_foot()

    def action_cursor_up(self) -> None:
        # 只移动高亮，不切换：浏览列表时不应把用户从当前窗口拽走。
        self.model.move(-1)
        self._paint_body()

    def action_cursor_down(self) -> None:
        self.model.move(1)
        self._paint_body()

    def action_activate(self) -> None:
        """Enter：进入选中会话并将焦点交给目标 pane。"""
        self.model.activate_current()
        self._paint_foot()

    def action_new_session(self) -> None:
        """n：在选中行所属目录下新建会话。"""
        self.model.new_session_in_current_dir()
        self._paint_body()
        self._paint_foot()

    def action_toggle(self) -> None:
        self.model.toggle_current()
        self._paint_body()

    def action_collapse(self) -> None:
        self.model.collapse_current()
        self._paint_body()

    def action_expand(self) -> None:
        self.model.expand_current()
        self._paint_body()

    def action_handoff(self) -> None:
        self.model.handoff_current()
        self._paint_body()
        self._paint_foot()

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        if widget is None or widget.id != "body":
            return
        # Textual 鼠标事件已转换为接收控件的局部坐标，包括滚动后的内容位置。
        offset = event.y
        if 0 <= offset < len(self._line_rows):
            index = self._line_rows[offset]
            if index is not None:
                row = self.model.rows()[index]
                width = self._width()
                if (row.kind == "group" and row.group.display_path
                        and self.model.on_new_session is not None and width >= 8
                        and width - 3 <= event.x < width):
                    self.model.select(index)
                    self.action_new_session()
                    event.stop()
                elif row.kind == "group":
                    self.model.select(index)
                    self.action_toggle()
                    event.stop()
                else:
                    self._select(index)


def run_sidebar(model: SidebarModel, on_ready: Callable[[], None] | None = None,
                *, image_origin: Callable[[], tuple[int, int, str] | None] | None = None) -> None:
    """在调用者终端中运行侧栏，直到用户退出。"""
    app = SidebarApp(model, on_ready, image_origin=image_origin)
    try:
        app.run()
    finally:
        # 异常退出时 driver 已停止；仍在本实例 pane 内回收剩余缓存。
        for kind in app._uploaded_images:
            sys.stdout.write(delete_sequence(app._image_ids[kind]))
        if app._uploaded_images:
            sys.stdout.flush()
