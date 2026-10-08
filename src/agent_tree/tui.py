"""侧栏的纯逻辑：可选行、折叠、选中、刷新与导航回调。

本模块不依赖任何第三方库，也不接触终端。``--snapshot`` 与离线测试只用到这里的
纯函数与 :class:`SidebarModel`；实际界面在 :mod:`agent_tree.ui` 中用 textual 实现，
这样 ``--snapshot`` 不因为界面框架而多出依赖与启动开销。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .model import AgentSession, DirectoryGroup, PaneState, Tree

#: 默认刷新间隔（秒）。
DEFAULT_REFRESH_SECONDS = 2.0

EXPANDED_MARK = "▾"
COLLAPSED_MARK = "▸"

HINT_BROWSE = "↑↓ 选择   空格 展开/折叠   q 退出"
HINT_NAVIGATE = "↑↓ 选择   Enter/→ 进入目标   n 新建   q 退出"
STATE_UNKNOWN_TEXT = "状态未知"


@dataclass(frozen=True)
class Row:
    """可选中行：目录行或会话行。

    ``last`` 表示该会话是否为其目录组内最后一项，供界面绘制 ``├─``／``└─`` 连接线。
    """

    kind: str  # "group" | "session"
    group: DirectoryGroup
    session: AgentSession | None = None
    last: bool = False


def state_text(session: AgentSession) -> str:
    """空闲与任务成功完成分别表述。"""
    return {PaneState.WORKING: "进行中", PaneState.IDLE: "空闲／本轮结束",
            PaneState.BLOCKED: "等待操作"}.get(session.state, STATE_UNKNOWN_TEXT)


def visible_rows(tree: Tree, collapsed: set[str]) -> list[Row]:
    """按折叠状态展开为可选中行序列。默认全部展开。"""
    rows: list[Row] = []
    for group in tree:
        rows.append(Row("group", group))
        if group.key not in collapsed:
            sessions = group.sessions
            for index, session in enumerate(sessions):
                rows.append(
                    Row("session", group, session, last=index == len(sessions) - 1)
                )
    return rows


def format_tree_text(tree: Tree, host_key: str = "") -> str:
    """纯文本树，用于 ``--snapshot`` 输出与离线检查。"""
    total = sum(len(group.sessions) for group in tree)
    header = f"Agent Tree · {total} 个会话"
    if host_key:
        header += f" · {host_key}"
    out = [header]
    if total == 0:
        out.append("未发现 Agent 会话")
        return "\n".join(out)
    for group in tree:
        suffix = f"  {group.display_path}" if group.display_path else ""
        out.append(f"{EXPANDED_MARK} {group.label}{suffix}")
        for session in group.sessions:
            out.append(
                f"  [{session.marker}] {session.display_name}"
                f"  {state_text(session)}  {session.backend_target}"
            )
    return "\n".join(out)


class SidebarModel:
    """侧栏状态与操作。与界面框架解耦，便于离线测试。"""

    def __init__(
        self,
        refresh: Callable[[], Tree],
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
    ) -> None:
        self._refresh = refresh
        self.refresh_seconds = refresh_seconds
        self.tree: Tree = ()
        self.collapsed: set[str] = set()
        self.selected = 0
        self.generation = 0
        self.message = ""
        self.loading = True
        self.can_navigate = False
        self.on_navigate: Callable[[AgentSession], None] | None = None
        self.on_handoff: Callable[[AgentSession], None] | None = None
        #: 在指定目录下新建会话，参数为该目录的规范化路径。
        self.on_new_session: Callable[[str], None] | None = None
        #: 侧栏 pane 当前所在的 ``(session 名, window 索引)``；宿主注入，pane 失效时为 ``None``。
        self.sidebar_window: Callable[[], tuple[str, int] | None] | None = None
        #: 树里已无可补位会话时退出侧栏；宿主负责结束界面进程。
        self.on_exit: Callable[[], None] | None = None
        self.sync_host: Callable[[], str | None] | None = None
        self.active_pane: str | None = None
        self._pending_active = False

    def fetch_tree(self) -> Tree:
        """读取快照；可在后台调用，不修改界面模型。"""
        return self._refresh()

    def reload(self, refresh: Callable[[], Tree] | None = None) -> None:
        """重新获取树。``generation`` 递增，供后续异步结果避免过期覆盖。

        单次刷新失败只显示错误信息，不终止侧栏，也不结束用户进程。
        刷新成功后检查侧栏旁的用户 pane：全部关闭时自动补位或收摊。
        """
        previous = self.tree
        self.sync_current()
        selected_row = self._current()
        try:
            self.tree = (refresh or self.fetch_tree)()
            if selected_row is not None:
                for index, row in enumerate(self.rows()):
                    if (row.kind, row.group.key, row.session.session_key if row.session else None) == (
                        selected_row.kind, selected_row.group.key,
                        selected_row.session.session_key if selected_row.session else None,
                    ):
                        self.selected = index
                        break
        except Exception as exc:  # noqa: BLE001 - 侧栏必须对宿主失败保持可用
            self.message = f"刷新失败：{exc}"
        else:
            self.message = ""
            self._replace_closed_companion(previous)
            self.sync_current()
        finally:
            self.loading = False
        self.generation += 1
        self._clamp_selection()

    def sync_current(self) -> None:
        """同步宿主当前 pane；侧栏接收输入时保留用户浏览中的高亮。"""
        if self.sync_host is None:
            return
        try:
            pane = self.sync_host()
        except Exception as exc:  # noqa: BLE001 - 跟随失败不应终止界面
            self.message = f"跟随失败：{exc}"
            return
        if pane is not None:
            self.active_pane = pane
            self._pending_active = True
        elif self.generation > 0 and not self._pending_active:
            return
        for group in self.tree:
            if any(s.backend_target == self.active_pane for s in group.sessions):
                self.collapsed.discard(group.key)
                for index, row in enumerate(self.rows()):
                    if row.session is not None and row.session.backend_target == self.active_pane:
                        self.selected = index
                        self._pending_active = False
                        return

    def rows(self) -> list[Row]:
        return visible_rows(self.tree, self.collapsed)

    def _clamp_selection(self) -> None:
        count = len(self.rows())
        self.selected = 0 if count == 0 else min(self.selected, count - 1)

    def _current(self) -> Row | None:
        rows = self.rows()
        if not rows or self.selected >= len(rows):
            return None
        return rows[self.selected]

    def select(self, index: int) -> None:
        count = len(self.rows())
        if count == 0:
            return
        self.selected = max(0, min(count - 1, index))

    def move(self, delta: int) -> None:
        indices = [index for index, row in enumerate(self.rows()) if row.kind == "session"]
        if not indices or delta == 0:
            return
        if self.selected in indices:
            position = indices.index(self.selected) + delta
        elif delta > 0:
            position = next((i for i, index in enumerate(indices) if index > self.selected), len(indices) - 1)
            position += delta - 1
        else:
            position = next((i for i in range(len(indices) - 1, -1, -1) if indices[i] < self.selected), 0)
            position += delta + 1
        self.selected = indices[max(0, min(len(indices) - 1, position))]

    def toggle_current(self) -> None:
        row = self._current()
        if row is None or row.kind != "group":
            return
        if row.group.key in self.collapsed:
            self.collapsed.discard(row.group.key)
        else:
            self.collapsed.add(row.group.key)
        self._clamp_selection()

    def collapse_current(self) -> None:
        row = self._current()
        if row is not None and row.kind == "group":
            self.collapsed.add(row.group.key)
            self._clamp_selection()

    def expand_current(self) -> None:
        row = self._current()
        if row is not None and row.kind == "group":
            self.collapsed.discard(row.group.key)

    def current_row(self) -> Row | None:
        return self._current()

    def current_session(self) -> AgentSession | None:
        """当前选中的会话；选中目录行时返回 ``None``。"""
        row = self._current()
        if row is None or row.kind != "session":
            return None
        return row.session

    def activate_current(self) -> None:
        """进入选中的会话。只由用户操作触发，刷新与排序变化不会调用。"""
        session = self.current_session()
        if session is None or self.on_navigate is None:
            return
        self.on_navigate(session)

    def handoff_current(self) -> None:
        """把输入焦点交给当前离线目标 pane。"""
        session = self.current_session()
        if session is None or self.on_handoff is None:
            return
        self.on_handoff(session)

    def current_directory(self) -> str | None:
        """当前行所属目录的可信路径；目录未知或无选中行时返回 ``None``。"""
        row = self._current()
        if row is None:
            return None
        return row.group.display_path or None

    def new_session_in_current_dir(self) -> None:
        """在选中行所属目录下新建会话。

        目录不可用时只提示、不新建，避免在错误路径下开出会话。
        """
        if self.on_new_session is None:
            return
        path = self.current_directory()
        if path is None:
            self.message = "该分组没有可用目录，无法新建会话"
            return
        try:
            self.on_new_session(path)
        except Exception as exc:  # noqa: BLE001 - 侧栏必须对宿主失败保持可用
            self.message = f"新建会话失败：{exc}"
        else:
            self.message = ""

    # ---- 补位 ----

    @staticmethod
    def _window_has_session(tree: Tree, window: tuple[str, int]) -> bool:
        name, index = window
        return any(
            session.session_name == name and session.window_index == index
            for group in tree
            for session in group.sessions
        )

    def _replace_closed_companion(self, previous: Tree) -> None:
        """侧栏旁的用户 pane 全部关闭时自动补位。

        发现逻辑会排除侧栏 pane，所以「树里没有自己所在 window 的条目」就意味着
        该 window 只剩侧栏（例如旁边的 shell 执行了 ``exit``）。补位目标按顺序取：
        同一路径分组里的第一个会话；该分组也不在了就取整个列表的第一个会话；
        列表为空则退出侧栏，让 tmux 自然收摊。
        """
        if self.sidebar_window is None or self.on_navigate is None:
            return
        window = self.sidebar_window()
        if window is None or self._window_has_session(self.tree, window):
            return
        replacement = self._replacement_for(window, previous)
        if replacement is None:
            if self.on_exit is not None:
                self.on_exit()
            return
        self.on_navigate(replacement)

    def _replacement_for(
        self, window: tuple[str, int], previous: Tree
    ) -> AgentSession | None:
        """补位目标：被关会话所在分组的第一个，否则全列表第一个；都没有则 ``None``。

        分组取自上一次刷新的树：补位那一刻被关 pane 已不在新树里，只有旧树知道它
        属于哪个路径分组。
        """
        name, index = window
        group_key = next(
            (
                group.key
                for group in previous
                for session in group.sessions
                if session.session_name == name and session.window_index == index
            ),
            None,
        )
        for group in self.tree:
            if group.key == group_key and group.sessions:
                return group.sessions[0]
        for group in self.tree:
            if group.sessions:
                return group.sessions[0]
        return None
