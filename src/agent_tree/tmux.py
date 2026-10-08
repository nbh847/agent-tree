"""tmux 访问层。

全部调用使用参数数组，不拼接字符串执行；字段以 ``\\x1f`` 分隔，避免路径含空格或
非 ASCII 被截断。状态采样只读取当前屏幕，不读取滚动历史。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

#: 字段分隔符。选择控制字符以兼容含空格、中文的路径。
SEP = "\x1f"

#: 侧栏实例所有权标记。写入 pane 级用户选项，用于从发现结果中排除自身；
#: 实测该标记跨 ``join-pane`` 保留。
SIDEBAR_OPTION = "@agent_tree_sidebar"

_PANE_TOKENS = (
    "pane_id",
    "session_id",
    "session_name",
    "window_id",
    "window_index",
    "window_name",
    "pane_index",
    "window_active",
    "pane_active",
    "pane_current_command",
    "pane_start_command",
    "pane_current_path",
    "pane_pid",
    "pane_tty",
    "session_attached",
)
PANE_FORMAT = SEP.join([*(f"#{{{token}}}" for token in _PANE_TOKENS), f"#{{{SIDEBAR_OPTION}}}"])


class TmuxError(RuntimeError):
    """tmux 访问失败。"""


class TmuxUnavailable(TmuxError):
    """tmux 不可用、socket 失效，或该 socket 上没有运行中的 server。"""


class TmuxCommandError(TmuxError):
    """tmux 命令返回非零退出码。"""

    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str) -> None:
        detail = stderr.strip() or "无错误输出"
        super().__init__(f"tmux {' '.join(args)} 退出码 {returncode}：{detail}")
        self.args_used = args
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True)
class PaneInfo:
    """一个 tmux pane 的元数据快照。"""

    pane_id: str
    session_id: str
    session_name: str
    window_id: str
    window_index: int
    window_name: str
    pane_index: int
    window_active: bool
    pane_active: bool
    pane_current_command: str
    pane_start_command: str
    pane_current_path: str
    pane_pid: int
    pane_tty: str
    #: 该 pane 所在 session 附着的 client 数量。0 表示 session 已断开（detached）。
    session_attached: int = 0
    sidebar_owner: str = ""

    @property
    def is_sidebar(self) -> bool:
        """该 pane 是否由某个 agent-tree 实例创建。"""
        return bool(self.sidebar_owner)


def _to_int(value: str, default: int = -1) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _to_bool(value: str) -> bool:
    return value == "1"


class Tmux:
    """指定 socket 的 tmux 访问入口。``socket=None`` 表示使用环境中的 socket。"""

    def __init__(self, socket: str | None = None, executable: str = "tmux") -> None:
        self.socket = socket
        self.executable = executable

    def _base(self) -> list[str]:
        if self.socket:
            return [self.executable, "-L", self.socket]
        return [self.executable]

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                [*self._base(), *args], capture_output=True, text=True, timeout=2
            )
        except subprocess.TimeoutExpired as exc:
            raise TmuxCommandError(args, -1, "查询超时（2 秒）") from exc
        except FileNotFoundError as exc:
            raise TmuxUnavailable(f"未找到 tmux 可执行文件：{self.executable}") from exc
        if check and completed.returncode != 0:
            raise TmuxCommandError(args, completed.returncode, completed.stderr)
        return completed

    def ensure_server(self) -> None:
        """确认该 socket 上有可用 server；否则抛出 :class:`TmuxUnavailable`。"""
        completed = self.run("display-message", "-p", "#{pid}", check=False)
        if completed.returncode != 0 or not completed.stdout.strip():
            detail = completed.stderr.strip() or "无法连接 tmux server"
            raise TmuxUnavailable(f"tmux 不可用：{detail}")

    def server_key(self) -> str:
        """宿主身份。使用 socket 路径，避免仅凭 PID 或名称识别宿主。"""
        self.ensure_server()
        return self.run("display-message", "-p", "#{socket_path}").stdout.strip()

    def mouse_enabled(self, session: str) -> bool:
        """该 session 是否启用 tmux 鼠标。

        只用于提示，不修改用户配置：tmux 未开启 mouse 时，侧栏收不到鼠标事件。
        """
        for args in (
            ("show-options", "-t", session, "-v", "mouse"),
            ("show-options", "-g", "-v", "mouse"),
        ):
            value = self.run(*args, check=False).stdout.strip()
            if value:
                return value == "on"
        return False

    def snapshot(self) -> tuple[PaneInfo, ...]:
        """读取所有 session／window 下的 pane 元数据。

        同一个 window 被链接到多个 session 时，其 pane 会被多次列出，因此按
        ``pane_id`` 去重，保证「跨 session 链接的同一 pane 不重复」。
        """
        completed = self.run("list-panes", "-a", "-F", PANE_FORMAT)
        seen: dict[str, PaneInfo] = {}
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            pane = _parse_pane(line)
            seen.setdefault(pane.pane_id, pane)
        return tuple(seen.values())

    def screen(self, pane_id: str) -> str | None:
        """只读当前屏幕；复制／历史查看模式和消失的 pane 不提供状态证据。"""
        mode = self.run("display-message", "-p", "-t", pane_id,
                        "#{pane_in_mode}", check=False)
        if mode.returncode or mode.stdout.strip() != "0":
            return None
        result = self.run("capture-pane", "-p", "-t", pane_id, check=False)
        return result.stdout if result.returncode == 0 else None


def _parse_pane(line: str) -> PaneInfo:
    fields = line.split(SEP)
    expected = len(_PANE_TOKENS) + 1
    if len(fields) != expected:
        raise TmuxCommandError(("list-panes",), -1, f"字段数异常：期望 {expected}，实际 {len(fields)}")
    return PaneInfo(
        pane_id=fields[0],
        session_id=fields[1],
        session_name=fields[2],
        window_id=fields[3],
        window_index=_to_int(fields[4]),
        window_name=fields[5],
        pane_index=_to_int(fields[6]),
        window_active=_to_bool(fields[7]),
        pane_active=_to_bool(fields[8]),
        pane_current_command=fields[9],
        pane_start_command=fields[10],
        pane_current_path=fields[11],
        pane_pid=_to_int(fields[12]),
        pane_tty=fields[13],
        session_attached=_to_int(fields[14], 0),
        sidebar_owner=fields[15],
    )
