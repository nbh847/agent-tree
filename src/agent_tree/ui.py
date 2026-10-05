"""基于 textual 的侧栏界面。

与 :mod:`agent_tree.tui` 的纯逻辑分离：本模块只负责把 :class:`~agent_tree.tui.SidebarModel`
的行渲染成带样式的文本、处理按键与鼠标，并驱动定时刷新。

注意：textual 需要终端对它的初始化查询作出应答，因此侧栏所在的 pane 必须处于
「有 client 附着」的 session 中；这与发现范围（只看附着会话）一致。
"""

from __future__ import annotations

import os
from typing import Callable

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from .model import AgentKind
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

#: 各 Agent 种类的名称配色（表示「种类」，不是执行状态）。
KIND_COLOR = {
    AgentKind.CLAUDE_CODE: "#d2a8ff",
    AgentKind.CODEX: "#7ee787",
    AgentKind.SHELL: "#79c0ff",
    AgentKind.UNKNOWN: "#e3b341",
}

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


def group_line(row: Row, collapsed: set[str], selected: bool, width: int) -> Text:
    """目录行：折叠标记 + 方括号目录名 + 暗淡父级路径 + 右对齐会话数。"""
    group = row.group
    line = Text()
    mark = COLLAPSED_MARK if group.key in collapsed else EXPANDED_MARK
    line.append(f"{mark} ", style=FAINT)
    line.append(f"[{group.label}]", style=f"bold {ACCENT}")
    hint = _short_path(group.display_path)
    if hint and cell_len(line.plain) + cell_len(hint) + len(str(len(group.sessions))) + 3 <= width:
        line.append(f"  {hint}", style=DIM)
    _pad(line, str(len(group.sessions)), width)
    return _highlight(line, selected, width)


def session_line(row: Row, selected: bool, width: int) -> Text:
    """会话行：连接线 + 按种类着色的名称。"""
    session = row.session
    assert session is not None
    line = Text()
    line.append("  " + (CONNECTOR_LAST if row.last else CONNECTOR_MID), style=FAINT)
    line.append(session.display_name, style=KIND_COLOR.get(session.agent, TEXT))
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

    def __init__(self, model: SidebarModel, on_ready: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.model = model
        # 侧栏旁的用户 pane 全部关闭且无可补位会话时，由模型回调退出。
        model.on_exit = self.exit
        self.on_ready = on_ready
        self._line_rows: list[int | None] = []

    # ---- 布局 ----

    def compose(self) -> ComposeResult:
        yield Static(id="title")
        yield VerticalScroll(Static(id="body"), id="scroll")
        yield Static(id="foot")

    def on_mount(self) -> None:
        # 先画出占位帧，再执行较慢的宿主检查与首次扫描。
        self._paint()
        if self.on_ready is not None:
            self.on_ready()
        self.model.reload()
        self._paint()
        self.set_interval(self.model.refresh_seconds, self._tick)
        self.set_interval(0.25, self._sync_host)

    def on_resize(self, _event: events.Resize) -> None:
        self._paint()

    # ---- 刷新 ----

    def _tick(self) -> None:
        self.model.reload()
        self._paint()

    def _sync_host(self) -> None:
        previous = (self.model.selected, set(self.model.collapsed), self.model.message)
        self.model.sync_current()
        if previous != (self.model.selected, self.model.collapsed, self.model.message):
            self._paint()

    def _width(self) -> int:
        body = self.query_one("#body", Static)
        size = body.content_size
        return max(1, size.width or self.size.width or 32)

    def _paint(self) -> None:
        self._paint_title()
        self._paint_body()
        self._paint_foot()

    def _paint_title(self) -> None:
        total = sum(len(group.sessions) for group in self.model.tree)
        text = Text()
        text.append("会话", style=f"bold {DIM}")
        _pad(text, str(total), max(1, self.size.width - 2))
        self.query_one("#title", Static).update(text)

    def _paint_foot(self) -> None:
        foot = self.query_one("#foot", Static)
        if self.model.message:
            foot.update(Text(self.model.message, style=ERROR))
            return
        hint = foot_text(self.model.can_navigate, max(1, self._width() - 2))
        foot.update(Text(hint, style=DIM))

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
                        row, self.model.collapsed, index == self.model.selected, width
                    )
                else:
                    body.append("  │\n", style=FAINT)
                    self._line_rows.append(None)
                    line = session_line(row, index == self.model.selected, width)
                body.append_text(line)
                body.append("\n")
                self._line_rows.append(index)

        self.query_one("#body", Static).update(body)
        if self.model.selected in self._line_rows:
            line = self._line_rows.index(self.model.selected)
            scroll = self.query_one("#scroll", VerticalScroll)
            if line < scroll.scroll_y or line >= scroll.scroll_y + scroll.size.height:
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
                self._select(index)


def run_sidebar(model: SidebarModel, on_ready: Callable[[], None] | None = None) -> None:
    """在调用者终端中运行侧栏，直到用户退出。"""
    SidebarApp(model, on_ready).run()
