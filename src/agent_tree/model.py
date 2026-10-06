"""数据模型：Agent 会话、目录分组与树。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentKind(str, Enum):
    """pane 的种类。未识别时使用 ``UNKNOWN``，不猜测具体种类。

    ``SHELL`` 表示未运行程序的普通交互式 shell；首版把这类窗口也列出，
    以便侧栏呈现 tmux 的完整全貌。
    """

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CODEBUDDY = "codebuddy"
    PI = "pi"
    SHELL = "shell"
    UNKNOWN = "unknown"


class PaneState(str, Enum):
    """执行状态。

    空闲表示当前可接收输入，不承诺任务成功完成。
    """

    UNKNOWN = "unknown"
    WORKING = "working"
    IDLE = "idle"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AgentSession:
    """一个 Agent pane 的观察快照。"""

    session_key: str
    host_key: str
    backend: str
    backend_target: str
    cwd: str | None
    canonical_cwd: str | None
    cwd_source: str
    agent: AgentKind
    display_name: str
    marker: str
    state: PaneState
    state_source: str
    confidence: str
    observed_at: float
    generation: int
    is_active: bool
    pane_pid: int
    session_name: str
    window_index: int
    window_name: str
    pane_index: int


@dataclass(frozen=True)
class DirectoryGroup:
    """按规范化目录归组的会话集合。同名不同路径不合并。"""

    key: str
    display_path: str
    label: str
    sessions: tuple[AgentSession, ...]


#: 登录目录，树结构为「目录组 → 会话」两层。
Tree = tuple[DirectoryGroup, ...]

#: 无法取得可信目录时的分组键与显示名。
UNKNOWN_DIR_KEY = "unknown-cwd"
UNKNOWN_DIR_LABEL = "目录未知"
