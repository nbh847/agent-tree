"""身份识别与会话发现。

身份只依据可信的进程证据：pane 启动命令与 pane 进程子树。不使用屏幕文本，
也不把 ``pane_current_command`` 单独作为身份依据（实测 ``claude`` 会显示为版本号）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import processes
from .model import AgentKind, AgentSession, PaneState
from .tmux import PaneInfo, Tmux

#: 普通 shell 名称。这些进程不作为 Agent 展示。
SHELL_NAMES = frozenset(
    {
        "zsh",
        "bash",
        "sh",
        "dash",
        "ksh",
        "mksh",
        "tcsh",
        "csh",
        "fish",
        "nu",
        "xonsh",
        "elvish",
        "pwsh",
        "powershell",
    }
)

#: ``state_source`` 取值：本阶段不实现状态识别。
STATE_SOURCE_NONE = "not-implemented"


@dataclass(frozen=True)
class AgentSignature:
    """一种 Agent 的识别签名。"""

    kind: AgentKind
    display_name: str
    marker: str
    names: frozenset[str]


AGENT_SIGNATURES: tuple[AgentSignature, ...] = (
    AgentSignature(AgentKind.CLAUDE_CODE, "Claude Code", "C", frozenset({"claude", "claude-code"})),
    AgentSignature(AgentKind.CODEX, "Codex", "O", frozenset({"codex"})),
    AgentSignature(AgentKind.CODEBUDDY, "CodeBuddy", "B", frozenset({"codebuddy", "cbc", "codebuddy-code"})),
)

UNKNOWN_DISPLAY_NAME = "未知"
UNKNOWN_MARKER = "?"

#: 普通 shell 条目的显示名与标识。
SHELL_DISPLAY_NAME = "Shell"
SHELL_MARKER = "$"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_NONE = "none"


def _match_signature(name: str) -> AgentSignature | None:
    if not name:
        return None
    for signature in AGENT_SIGNATURES:
        if name in signature.names:
            return signature
    return None


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def start_command_name(start_command: str) -> str:
    """取出启动命令的实际命令名，跳过 ``VAR=VALUE`` 形式的环境赋值前缀。

    只取命令名而不扫描其参数，避免把 ``grep codex file`` 这类参数误判为 Agent。
    """
    for token in start_command.split():
        head = token.split("=", 1)[0]
        if "=" in token and head.isidentifier():
            continue
        return _basename(token)
    return ""


def identify(
    start_command: str, procs_in_tree: list[processes.ProcInfo]
) -> tuple[AgentSignature | None, str, str]:
    """识别 Agent 身份。

    证据强度依次为：进程子树中可执行文件名（最强）、进程参数中的明确路径
    （包装启动，如 ``node /path/claude``）、启动命令名。识别不到时返回
    ``(None, "none", "")``，由调用方降级为「未知」。
    """
    for proc in procs_in_tree:
        signature = _match_signature(proc.exe_name)
        if signature is not None:
            return signature, CONFIDENCE_HIGH, f"进程 {proc.argv[0]}"

    for proc in procs_in_tree:
        for token in proc.argv[1:]:
            if "/" not in token:
                continue
            signature = _match_signature(_basename(token))
            if signature is not None:
                return signature, CONFIDENCE_MEDIUM, f"进程参数 {token}"

    signature = _match_signature(start_command_name(start_command))
    if signature is not None:
        return signature, CONFIDENCE_MEDIUM, f"启动命令 {start_command.strip()}"

    return None, CONFIDENCE_NONE, ""


def _normalise_command(name: str) -> str:
    return name[1:] if name.startswith("-") else name


def is_plain_shell(pane: PaneInfo, procs_in_tree: list[processes.ProcInfo]) -> bool:
    """判断该 pane 是否只是普通 shell（未运行其他程序）。

    以 tmux 的前台进程名为主：它反映当前占用输入的进程，不受 shell 启动期短暂子进程
    影响（例如补全初始化会瞬时产生非 shell 子进程）。进程名不可信时再退回子树判断：
    子树全为 shell 同样视为普通 shell。shell 前台运行其他程序（如 ``vim``）不算普通
    shell，会降级为「未知」条目。
    """
    if _normalise_command(pane.pane_current_command) in SHELL_NAMES:
        return True
    names = {proc.exe_name for proc in procs_in_tree if proc.argv}
    return bool(names) and names <= SHELL_NAMES


def discover(
    tmux: Tmux,
    host_key: str,
    generation: int = 0,
    only_attached: bool = False,
    keep_sessions: set[str] | None = None,
) -> list[AgentSession]:
    """发现当前 server 内所有 pane（含普通 shell）。

    自建侧栏 pane 会被排除；其余 pane 都保留：已识别的 Agent 标为对应种类，
    普通 shell 标为 ``SHELL``，无法可靠识别的非 shell 进程标为 ``UNKNOWN``。
    这样侧栏能呈现 tmux 的完整全貌，也能看出哪个窗口正跑着 Agent。

    ``only_attached=True`` 时保留附着会话，以及进程树中仍有非 shell 程序的 detached
    pane（含 Agent 与普通服务）。空闲 detached shell 不因此纳入；历史启动命令不能证明程序仍存活。

    但侧栏导航会 ``switch-client``，把 client 从原 session 移走使其变成 detached；
    若原 session 就此从列表消失，用户会觉得「刚才那个窗口没了」。因此
    ``keep_sessions`` 记录本次侧栏运行期间**曾**附着过的 session 名，这些 session
    即使当前已断开也继续显示；传入的集合会被就地更新。
    """
    panes = tmux.snapshot()
    procs = processes.snapshot()
    observed_at = time.time()

    sessions: list[AgentSession] = []
    for pane in panes:
        if pane.is_sidebar:
            continue
        procs_in_tree = (
            processes.subtree(procs, pane.pane_pid) if pane.pane_pid > 0 else []
        )
        if only_attached:
            if pane.session_attached:
                if keep_sessions is not None:
                    keep_sessions.add(pane.session_name)
            elif keep_sessions is None or pane.session_name not in keep_sessions:
                # 只依据当前进程保留 Agent、前台程序与 shell 后台服务。
                # 不用前台命令判断：服务可能由 bash 包装或在 shell 后台运行。
                if not any(proc.exe_name and proc.exe_name not in SHELL_NAMES
                           for proc in procs_in_tree):
                    continue
        signature, confidence, _evidence = identify(pane.pane_start_command, procs_in_tree)
        if signature is not None:
            agent, display_name, marker = signature.kind, signature.display_name, signature.marker
        elif is_plain_shell(pane, procs_in_tree):
            agent, display_name, marker = AgentKind.SHELL, SHELL_DISPLAY_NAME, SHELL_MARKER
            confidence = CONFIDENCE_MEDIUM
        else:
            agent, display_name, marker = AgentKind.UNKNOWN, UNKNOWN_DISPLAY_NAME, UNKNOWN_MARKER

        cwd = pane.pane_current_path or None
        sessions.append(
            AgentSession(
                session_key=f"{host_key}#{pane.pane_id}",
                host_key=host_key,
                backend="tmux",
                backend_target=pane.pane_id,
                cwd=cwd,
                # tmux 已返回 macOS 真实路径并解析软链接，这里不再重复 realpath。
                canonical_cwd=cwd,
                cwd_source="pane_current_path" if cwd else "unavailable",
                agent=agent,
                display_name=display_name,
                marker=marker,
                state=PaneState.UNKNOWN,
                state_source=STATE_SOURCE_NONE,
                confidence=confidence,
                observed_at=observed_at,
                generation=generation,
                is_active=pane.pane_active,
                pane_pid=pane.pane_pid,
                session_name=pane.session_name,
                window_index=pane.window_index,
                window_name=pane.window_name,
                pane_index=pane.pane_index,
            )
        )
    return sessions
