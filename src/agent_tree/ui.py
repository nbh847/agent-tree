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
from collections import deque
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Callable

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import Reactive
from textual.widgets import Static

from .icons import (ICON_COLUMN, ICON_HEIGHT, ICON_WIDTH, LOGO_HEIGHT, LOGO_WIDTH,
                    delete_sequence, image_sequence, logo_sequence, placeholder_row)
from .icons import decoration_sequence
from .model import AgentKind, PaneState
from .sidebar import MouseQueryTimeout
from .tui import (
    COLLAPSED_MARK,
    EXPANDED_MARK,
    HINT_BROWSE,
    HINT_NAVIGATE,
    Row,
    SidebarModel,
)

# 参考图取自暗色系：近黑底、灰次要文字、青绿强调。
BG = "#171726"
PANEL = "#232333"
DIM = "#9fa6bf"
FAINT = "#666b80"
TEXT = "#cbd2ec"
BRIGHT = "#eff5f3"
ACCENT = "#a2df9c"
SELECT_ACCENT = "#8db4fa"
ERROR = "#f85149"
SEL_BG = "#323244"
BRANCH_BG = "#382938"
BRANCH_TEXT = "#ef91b0"

#: 树形连接线：非末项与末项。
CONNECTOR_MID = "├──┬ "
CONNECTOR_LAST = "└──┬ "

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
#brand {{
    height: auto;
    background: {BG};
    text-wrap: nowrap;
    text-overflow: clip;
}}
#title {{
    height: 2;
    background: {BG};
    color: {DIM};
    padding: 0 1;
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
    height: 2;
    background: {BG};
    color: {DIM};
    padding: 0 1;
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


def group_line(row: Row, collapsed: set[str], selected: bool, width: int, *, can_create: bool = False,
               folder_id: int | None = None, branch_id: int | None = None) -> Text:
    """目录行：折叠标记 + 方括号目录名 + 暗淡父级路径 + 右对齐会话数。"""
    group = row.group
    button = can_create and bool(group.display_path) and width >= 8
    content_width = width - 4 if button else width
    line = Text()
    mark = COLLAPSED_MARK if group.key in collapsed else EXPANDED_MARK
    line.append(f" {mark}  ", style=FAINT)
    if content_width >= 16:
        if folder_id is not None:
            line.append(placeholder_row(folder_id, 0, 2), style=f"#{folder_id:06x} on {BG}")
        else:
            line.append("▣ ", style=DIM)
        line.append(" ")
    line.append(f"[{group.label}]", style=f"bold {ACCENT}")
    branch = None
    if group.branch:
        branch = Text("◖", style=f"{BRANCH_BG} on {BG}")
        if branch_id is not None:
            branch.append(placeholder_row(branch_id, 0, 2), style=f"#{branch_id:06x} on {BRANCH_BG}")
        else:
            branch.append("Y ", style=f"{BRANCH_TEXT} on {BRANCH_BG}")
        branch.append(f" {group.branch} ", style=f"bold {BRANCH_TEXT} on {BRANCH_BG}")
        branch.append("◗", style=f"{BRANCH_BG} on {BG}")
    if branch is not None and cell_len(line.plain) + cell_len(branch.plain) + 3 <= content_width:
        line.append(" ")
        line.append_text(branch)
    hint = _short_path(group.display_path)
    if content_width >= 55 and hint and cell_len(line.plain) + cell_len(hint) + len(str(len(group.sessions))) + 3 <= content_width:
        line.append(f"  {hint}", style=DIM)
    _pad(line, str(len(group.sessions)), content_width)
    if button:
        line.append(" [+]", style=f"bold {SELECT_ACCENT}")
    return _highlight(line, selected, width)


def session_icon_column(row: Row, width: int) -> int | None:
    """图标位于名称左侧；窄栏优先保留名称与状态。"""
    status_width = 2 if row.session.agent not in {AgentKind.SHELL, AgentKind.UNKNOWN} else 0
    if width < ICON_COLUMN + ICON_WIDTH + 4 + status_width:
        return None
    return ICON_COLUMN


def session_line(row: Row, selected: bool, width: int, *, image_icons: bool = False,
                 image_id: int | None = None, working_bright: bool = True,
                 current: bool | None = None, card_ids: tuple[int, int] | None = None) -> Text:
    """会话行：连接线 + 左侧图标／字符标识 + 名称与状态。"""
    session = row.session
    assert session is not None
    line = Text()
    line.append("   " + (CONNECTOR_LAST if row.last else CONNECTOR_MID), style=FAINT)
    column = session_icon_column(row, width)
    if column is not None:
        marker = (" " * ICON_WIDTH if image_icons and session.agent in (
            AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI, AgentKind.SHELL)
                  else session.marker.ljust(ICON_WIDTH))
        if image_id is not None:
            line.append(placeholder_row(image_id, 0), style=f"#{image_id:06x} on {BG}")
        else:
            line.append(marker, style=DIM)
        line.append(" ", style=DIM)
    status_width = 2 if session.agent not in {AgentKind.SHELL, AgentKind.UNKNOWN} else 0
    name = Text(session.display_name, style=f"bold {TEXT}")
    name.truncate(max(1, width - cell_len(line.plain) - status_width), overflow="ellipsis")
    line.append_text(name)
    if status_width and cell_len(line.plain) + 2 <= width:
        color = {PaneState.WORKING: SELECT_ACCENT, PaneState.BLOCKED: "#e3b341",
                 PaneState.IDLE: ACCENT, PaneState.UNKNOWN: DIM}[session.state]
        if session.state is PaneState.WORKING and not working_bright:
            color = "#405675"
        line.append(" ", style=DIM)
        line.append("●", style=color)
        state_label = {PaneState.WORKING: "Working", PaneState.BLOCKED: "Waiting",
                       PaneState.IDLE: "Ready", PaneState.UNKNOWN: "Unknown"}[session.state]
        if cell_len(line.plain) + len(state_label) + 1 <= width:
            line.append(" " + state_label, style=DIM)
    _pad(line, "", width)
    return _highlight(line, selected, width, current=current, edge=1, card_ids=card_ids)


def session_spacer(row: Row, width: int, image_id: int | None, canvas_row: int, *, selected: bool = False,
                   current: bool | None = None, card_ids: tuple[int, int] | None = None) -> Text:
    line = Text("   │" if canvas_row == 0 or not row.last else "    ", style=FAINT)
    column = session_icon_column(row, width)
    if canvas_row == 2:
        line.append("  └─── ", style=FAINT)
        start = ICON_COLUMN + ICON_WIDTH + 1 if column is not None else ICON_COLUMN
        # 第二行复用真实 tmux 标识，不伪造创建时间或任务历史。
        line.append(" " * max(0, start - cell_len(line.plain)))
        detail = Text(f"{row.session.session_name} · {row.session.window_name}", style=DIM)
        detail.truncate(max(0, width - cell_len(line.plain)), overflow="ellipsis")
        line.append_text(detail)
    _pad(line, "", width)
    return _highlight(line, selected, width, current=current, edge=canvas_row, card_ids=card_ids)


def _highlight(line: Text, selected: bool, width: int, *, current: bool | None = None,
               edge: int | None = None, card_ids: tuple[int, int] | None = None) -> Text:
    """选中行使用低调的浅色背景块，并把整行补满背景。"""
    if not selected and not current:
        return line
    active = selected if current is None else current
    background = SEL_BG if active else PANEL
    # 用蓝色竖线标出当前位置，保留树形连接线与整行的列宽。
    line = Text("▎" if active else "›", style=SELECT_ACCENT if active else DIM) + line[1:]
    line.stylize(f"on {background}")
    missing = width - cell_len(line.plain)
    if missing > 0:
        line.append(" " * missing, style=f"on {background}")
    if active and card_ids is not None and edge is not None and width >= 3 and line.plain.endswith("  "):
        # 两侧仅占空白列；PNG 圆角和连续蓝线随文本标记重绘。
        left, right = card_ids
        line = (Text(placeholder_row(left, edge, 1), style=f"#{left:06x} on {BG}")
                + line[1:-2]
                + Text(placeholder_row(right, edge, 1), style=f"#{right:06x} on {BG}")
                + Text(" ", style=f"on {BG}"))
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

    def __init__(self, model: SidebarModel, on_ready: Callable[[], str | None] | None = None,
                 *, image_origin: Callable[[], tuple[int, int, str] | None] | None = None,
                 mouse_guard: Callable[[Event], bool] | None = None,
                 stopping: Event | None = None) -> None:
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
        first_id = secrets.randbelow(0xFFFFF6) + 1
        self._image_ids = {kind: first_id + index for index, kind in enumerate(
            (AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI, AgentKind.SHELL))}
        self._uploaded_images: set[AgentKind] = set()
        self._logo_id = first_id + 5
        self._logo_uploaded = False
        self._logo_visible = False
        self._decoration_ids = {"folder": first_id + 6, "branch": first_id + 7,
                                "card-left": first_id + 8, "card-right": first_id + 9}
        self._uploaded_decorations = set()
        self._working_bright = True
        self._scan_pending = False
        self._scan_results = Queue()
        self._quitting = False
        self.mouse_guard = mouse_guard
        self._mouse_pending = False
        self._mouse_results = Queue()
        self._mouse_stopping = Event()
        self._mouse_error = ""
        self._mouse_retry_at = 0.0
        # 观察和布局操作共用单个在途任务，宿主回调不修改界面模型。
        self._stopping = stopping or Event()
        self._host_sync = model.sync_host
        self._host_window = model.sidebar_window
        self._cached_window = None
        self._host_pane = None
        self._host_error = ""
        self._operation_error = ""
        self._jobs = deque()
        self._job_results = Queue()
        self._job_thread = None
        self._job_pending = False
        self._intent = 0
        self._navigating = None
        if self._host_sync is not None:
            model.sync_host = self._cached_host
        if self._host_window is not None:
            model.sidebar_window = lambda: self._cached_window
        for name in ("on_navigate", "on_handoff", "on_new_session"):
            callback = getattr(model, name)
            if callback is not None:
                kind = "new" if name == "on_new_session" else "navigate"
                setattr(model, name, lambda target, callback=callback, kind=kind:
                        self._enqueue_operation(kind, callback, target))

    # ---- 布局 ----

    def compose(self) -> ComposeResult:
        # 没有可点击链接；默认链接悬停会随文字样式变化重绘整个 Static。
        brand, title, body, foot = (Static(id=name) for name in ("brand", "title", "body", "foot"))
        for widget in (brand, title, body, foot):
            widget.auto_links = False
        yield brand
        yield title
        scroll = VerticalScroll(body, id="scroll")
        scroll.can_focus = False  # 按键由 App 绑定处理，无需点击时切换控件焦点。
        yield scroll
        yield foot

    def on_mount(self) -> None:
        # 先画出占位帧，再执行较慢的宿主检查与首次扫描。
        self._paint()
        if self.on_ready is not None:
            self._jobs.append(("ready", self.on_ready, None, self._intent))
        self._sync_host()
        self._tick()
        self._paint()
        self.set_interval(self.model.refresh_seconds, self._tick)
        self.set_interval(0.25, self._sync_host)
        self.set_interval(0.6, self._pulse_working)
        self.set_interval(0.05, self._finish_scan)
        if self.mouse_guard is not None:
            self._check_mouse_host()
            self.set_interval(5, self._check_mouse_host)

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
        Thread(target=self._scan, args=(self._intent,), daemon=True).start()

    def _scan(self, intent: int) -> None:
        # 后台只生成快照；选中、导航和绘制仍在界面线程处理。
        try:
            tree = self.model.fetch_tree()
        except Exception as exc:
            self._scan_results.put((None, exc, intent))
        else:
            self._scan_results.put((tree, None, intent))

    def _finish_scan(self) -> None:
        if not self.is_running or self._quitting:
            return
        self._finish_mouse_check()
        self._finish_job()
        try:
            tree, error, intent = self._scan_results.get_nowait()
        except Empty:
            return
        self._scan_pending = False
        if intent != self._intent:
            self._tick()
            return  # 旧发现结果不能依据新窗口位置触发关闭补位。
        def result():
            if error is not None:
                raise error
            return tree
        self.model.reload(result)
        if self.is_running and not self._quitting:
            self._paint()

    def _check_mouse_host(self) -> None:
        if (not self.is_running or self._quitting or self._mouse_pending
                or self.mouse_guard is None or monotonic() < self._mouse_retry_at):
            return
        self._mouse_pending = True
        Thread(target=self._check_mouse_worker, daemon=True).start()

    def _check_mouse_worker(self) -> None:
        try:
            self.mouse_guard(self._mouse_stopping)
        except Exception as exc:
            self._mouse_results.put(exc)
        else:
            self._mouse_results.put(None)

    def _finish_mouse_check(self) -> None:
        try:
            error = self._mouse_results.get_nowait()
        except Empty:
            return
        self._mouse_pending = False
        if isinstance(error, MouseQueryTimeout):
            self._mouse_retry_at = monotonic() + 30
            self._mouse_error = f"{error}；30 秒后重试，键盘操作可用"
            self._paint_foot()
        elif error is not None:
            self.mouse_guard = None
            self._mouse_error = f"{error}；已停用自动恢复，键盘操作可用"
            self._paint_foot()
        else:
            self._mouse_retry_at = 0.0
            if self._mouse_error:
                self._mouse_error = ""
                self._paint_foot()

    def _sync_host(self) -> None:
        if not self.is_running or self._quitting or self._job_pending:
            return
        if self._jobs:
            job = self._jobs.popleft()
        elif self._host_sync or self.image_origin or self._host_window:
            job = ("host", self._observe_host, None, self._intent)
        else:
            return
        self._job_pending = True
        self._job_thread = Thread(target=self._run_job, args=(job,), daemon=True)
        self._job_thread.start()

    def _cached_host(self) -> str | None:
        pane, self._host_pane = self._host_pane, None
        return pane

    def _observe_host(self):
        pane = self._host_sync() if self._host_sync else None
        origin = self.image_origin() if self.image_origin else None
        window = self._host_window() if self._host_window else None
        return pane, origin, window

    def _enqueue_operation(self, kind, callback, target) -> None:
        if self._quitting or self._stopping.is_set():
            return
        self._intent += 1
        self._operation_error = ""
        self.model.message = ""
        self._cached_window = None  # 操作期间不按旧位置触发关闭补位。
        if kind == "navigate":
            # 只合并连续待处理导航；新建操作是独立的显式用户意图。
            if self._jobs and self._jobs[-1][0] == "navigate":
                self._jobs.pop()
            self._navigating = target.backend_target
        self._jobs.append((kind, callback, target, self._intent))
        self._paint_foot()
        self._sync_host()

    def _run_job(self, job) -> None:
        kind, callback, target, intent = job
        result, error = None, None
        try:
            if not self._stopping.is_set():
                result = callback() if kind in {"host", "ready"} else callback(target)
        except Exception as exc:
            error = exc
        self._job_results.put((kind, target, intent, result, error))

    def _finish_job(self) -> None:
        try:
            kind, target, intent, result, error = self._job_results.get_nowait()
        except Empty:
            return
        self._job_pending = False
        if self._quitting or not self.is_running:
            return
        if kind == "host":
            if intent == self._intent:
                self._host_error = f"宿主同步失败：{error}" if error else ""
                if error:
                    self._image_origin = None
                else:
                    self._host_pane, self._image_origin, self._cached_window = result
                    self.model.sync_current()
        elif kind == "ready":
            if error:
                self._host_error = str(error)
            elif result:
                self._host_error = result
        else:
            # 操作期间启动的扫描也可能不含最终布局；失败可能已部分生效。
            self._intent += 1
            self._cached_window = None
            if kind == "navigate":
                if not error:
                    self.model.active_pane = target.backend_target
                pending = [job[2].backend_target for job in self._jobs if job[0] == "navigate"]
                self._navigating = pending[-1] if pending else None
            self.model.message = f"操作失败：{error}" if error else ""
            self._operation_error = self.model.message
            if not error:
                self._tick()
        self._paint()
        if self._jobs:
            self._sync_host()

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
        upload_logo = self._logo_visible and not self._logo_uploaded
        if upload_logo:
            self._driver.write(logo_sequence(self._logo_id))
            self._logo_uploaded = True
        decorations = self._decoration_ids.keys() - self._uploaded_decorations
        for kind in decorations:
            self._driver.write(decoration_sequence(kind, self._decoration_ids[kind]))
            self._uploaded_decorations.add(kind)
        if pending or upload_logo or decorations:
            self._driver.flush()

    def _release_images(self) -> None:
        if self._driver is not None and not self.is_headless:
            for kind in self._uploaded_images:
                self._driver.write(delete_sequence(self._image_ids[kind]))
            if self._logo_uploaded:
                self._driver.write(delete_sequence(self._logo_id))
                self._logo_uploaded = False
            for kind in self._uploaded_decorations:
                self._driver.write(delete_sequence(self._decoration_ids[kind]))
            self._driver.flush()
        self._uploaded_images.clear()
        self._uploaded_decorations.clear()

    def action_quit(self) -> None:
        self._quitting = True
        self._stopping.set()
        self._jobs.clear()
        self._mouse_stopping.set()
        self._release_images()
        self.exit()

    def on_unmount(self) -> None:
        self._quitting = True
        self._stopping.set()
        self._mouse_stopping.set()
        self._jobs.clear()

    def _width(self) -> int:
        return max(1, self._viewport_width or self.size.width or 32)

    def _paint(self) -> None:
        self._paint_brand()
        self._paint_title()
        self._paint_body()
        self._paint_foot()

    def _update_text(self, widget_id: str, text: Text) -> None:
        # Static.update 即使内容相同也会重绘；快照未变化时不提交新帧。
        if self._last_text.get(widget_id) != text:
            self._last_text[widget_id] = text
            self.query_one(widget_id, Static).update(text)

    def _paint_brand(self) -> None:
        width = self._width()
        tall = self.size.height >= 24 and width >= LOGO_WIDTH + 2
        self._logo_visible = tall and self._image_origin is not None
        text = Text()
        def center(line: Text):
            line.truncate(width, overflow="ellipsis")
            text.append(" " * max(0, (width - cell_len(line.plain)) // 2))
            text.append_text(line)
        if tall:
            text.append("\n")
        if self._logo_visible:
            for row in range(LOGO_HEIGHT):
                center(Text(placeholder_row(self._logo_id, row, LOGO_WIDTH), style=f"#{self._logo_id:06x} on {BG}"))
                text.append("\n")
        else:
            if tall:
                text.append("\n")
            center(Text("❯▪ One", style=f"bold {BRIGHT}"))
            if tall:
                text.append("\n\n")
        if self.size.height >= 18:
            if not tall:
                text.append("\n")
            center(Text("All agents in one.", style=DIM))
        if tall:
            text.append("\n")
        self._update_text("#brand", text)

    def _paint_title(self) -> None:
        total = sum(len(group.sessions) for group in self.model.tree)
        text = Text()
        text.append(f"当前任务  {total}", style=f"bold {TEXT}")
        width = max(1, self.size.width - 2)
        if cell_len(text.plain) + 3 < width:
            text.append("  " + "─" * (width - cell_len(text.plain) - 2), style=FAINT)
        text.truncate(width, overflow="ellipsis")
        self._update_text("#title", text)

    def _paint_foot(self) -> None:
        message = self.model.message or self._operation_error or self._host_error or self._mouse_error
        if message:
            self._update_text("#foot", Text(message, style=ERROR))
            return
        if self._navigating is not None:
            self._update_text("#foot", Text("正在切换会话…", style=DIM))
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
                        folder_id=self._decoration_ids["folder"] if self._image_origin is not None else None,
                        branch_id=self._decoration_ids["branch"] if self._image_origin is not None else None,
                    )
                else:
                    image_id = (self._image_ids.get(row.session.agent)
                                if self._image_origin is not None and session_icon_column(row, width) is not None
                                else None)
                    card_ids = ((self._decoration_ids["card-left"], self._decoration_ids["card-right"])
                                if self._image_origin is not None and session_icon_column(row, width) is not None
                                else None)
                    current = row.session.backend_target == self.model.active_pane
                    # 无宿主的离线浏览保留原有单选样式。
                    current = current if self._host_sync or self.model.can_navigate else None
                    body.append_text(session_spacer(row, width, image_id, 0,
                                                   selected=index == self.model.selected, current=current, card_ids=card_ids))
                    body.append("\n")
                    self._line_rows.append(index if self._image_origin is not None else None)
                    line = session_line(row, index == self.model.selected, width,
                                        image_icons=self._image_origin is not None, image_id=image_id,
                                        working_bright=self._working_bright, current=current, card_ids=card_ids)
                body.append_text(line)
                body.append("\n")
                self._line_rows.append(index)
                if row.kind == "session":
                    body.append_text(session_spacer(row, width, image_id, 2,
                                                   selected=index == self.model.selected, current=current, card_ids=card_ids))
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


def run_sidebar(model: SidebarModel, on_ready: Callable[[], str | None] | None = None,
                *, image_origin: Callable[[], tuple[int, int, str] | None] | None = None,
                mouse_guard: Callable[[Event], bool] | None = None,
                stopping: Event | None = None) -> None:
    """在调用者终端中运行侧栏，直到用户退出。"""
    app = SidebarApp(model, on_ready, image_origin=image_origin, mouse_guard=mouse_guard,
                     stopping=stopping)
    try:
        app.run()
    finally:
        app._stopping.set()
        app._mouse_stopping.set()
        # 恢复 client 必须等在途操作收尾；界面已经退出，不阻塞输入处理。
        if app._job_thread is not None:
            app._job_thread.join()
        # 异常退出时 driver 已停止；仍在本实例 pane 内回收剩余缓存。
        for kind in app._uploaded_images:
            sys.stdout.write(delete_sequence(app._image_ids[kind]))
        if app._logo_uploaded:
            sys.stdout.write(delete_sequence(app._logo_id))
        for kind in app._uploaded_decorations:
            sys.stdout.write(delete_sequence(app._decoration_ids[kind]))
        if app._uploaded_images or app._logo_uploaded or app._uploaded_decorations:
            sys.stdout.flush()
