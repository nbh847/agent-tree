"""目录分组、树结构与稳定排序。

分组键优先取**仓库根目录**：从会话的工作目录逐级向上查找 ``.git``，命中即以该目录
成组，因此同一仓库下不同子目录（如 ``kzz-radar`` 与 ``kzz-radar/web``）的会话聚到
一起。不在任何仓库内时退回规范化完整目录。``.git`` 既可能是目录也可能是文件，
后者见于 worktree／submodule，两者都算命中，所以各 worktree 仍是各自的根。

取不到目录时归入「目录未知」。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .model import (
    UNKNOWN_DIR_KEY,
    UNKNOWN_DIR_LABEL,
    AgentKind,
    AgentSession,
    DirectoryGroup,
    Tree,
)

#: 组内排序时的种类优先级：先已识别 Agent，再「未知」，最后普通 shell。
_AGENT_RANK = {
    AgentKind.CLAUDE_CODE: 0,
    AgentKind.CODEX: 0,
    AgentKind.CODEBUDDY: 0,
    AgentKind.PI: 0,
    AgentKind.UNKNOWN: 1,
    AgentKind.SHELL: 2,
}


def find_project_root(path: str) -> str | None:
    """向上查找 ``.git``，返回仓库根目录；不在仓库内时返回 ``None``。

    只做文件系统判断，不调用 ``git``：既不依赖 git 安装，也没有子进程开销。
    家目录本身不作为仓库根，避免把 ``$HOME`` 当仓库的 dotfiles 配置把所有家目录下的
    会话错误地合并成一组。
    """
    if not path:
        return None
    start = Path(path)
    home = Path.home()
    for directory in (start, *start.parents):
        if directory == home:
            return None
        if (directory / ".git").exists():
            return str(directory)
    return None


def group_key(session: AgentSession) -> str:
    """分组键：优先仓库根目录，其次规范化工作目录，都取不到时归入「目录未知」。"""
    cwd = session.canonical_cwd
    if not cwd:
        return UNKNOWN_DIR_KEY
    return find_project_root(cwd) or cwd


def build_tree(sessions: list[AgentSession]) -> Tree:
    """把会话按仓库根目录（无仓库时按工作目录）聚合为稳定排序的两层树。"""
    buckets: dict[str, list[AgentSession]] = {}
    for session in sessions:
        buckets.setdefault(group_key(session), []).append(session)

    groups: list[DirectoryGroup] = []
    for key, items in buckets.items():
        if key == UNKNOWN_DIR_KEY:
            display_path = ""
            label = UNKNOWN_DIR_LABEL
        else:
            display_path = key
            label = PurePosixPath(key).name or key
        groups.append(
            DirectoryGroup(
                key=key,
                display_path=display_path,
                label=label,
                sessions=tuple(sorted(items, key=session_sort_key)),
            )
        )

    groups.sort(key=group_sort_key)
    return tuple(groups)


def session_sort_key(session: AgentSession) -> tuple[int, str, int, int, str]:
    """会话排序键。使用不随状态变化的字段，避免刷新时顺序跳动。

    先按种类优先级（Agent → 未知 → shell），再按 session／window／pane 定位。
    """
    return (
        _AGENT_RANK.get(session.agent, 1),
        session.session_name,
        session.window_index,
        session.pane_index,
        session.backend_target,
    )


def group_sort_key(group: DirectoryGroup) -> tuple[int, str]:
    """目录排序键。「目录未知」固定置底。"""
    return (1 if group.key == UNKNOWN_DIR_KEY else 0, group.key)
