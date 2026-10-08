"""进程快照与进程树遍历。

身份识别必须依赖真实运行的进程，而不是 pane 名称：实测 ``claude`` 的
``pane_current_command`` 会是版本号（如 ``2.1.285``）。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import PurePath


@dataclass(frozen=True)
class ProcInfo:
    """单个进程的观察结果。``argv`` 由 ``ps`` 的命令行按空白切分得到。"""

    pid: int
    ppid: int
    argv: tuple[str, ...]

    @property
    def exe_name(self) -> str:
        """``argv[0]`` 的文件名部分，供身份匹配使用。

        归一化 login shell 的前导连字符（如 ``-zsh``）。
        """
        if not self.argv:
            return ""
        name = PurePath(self.argv[0]).name
        return name[1:] if name.startswith("-") else name


def snapshot() -> dict[int, ProcInfo]:
    """读取全量进程快照。读取失败时返回空表并降级，不抛出异常。"""
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    return _parse(completed.stdout)


def _parse(text: str) -> dict[int, ProcInfo]:
    result: dict[int, ProcInfo] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        argv = tuple(parts[2].split()) if len(parts) > 2 else ()
        result[pid] = ProcInfo(pid=pid, ppid=ppid, argv=argv)
    return result


def subtree(procs: dict[int, ProcInfo], root_pid: int) -> list[ProcInfo]:
    """返回以 ``root_pid`` 为根的进程子树（含根），按深度优先排序。"""
    children: dict[int, list[int]] = {}
    for info in procs.values():
        children.setdefault(info.ppid, []).append(info.pid)

    ordered: list[ProcInfo] = []

    def walk(pid: int, seen: set[int]) -> None:
        if pid in seen or pid not in procs:
            return
        seen.add(pid)
        ordered.append(procs[pid])
        for child in sorted(children.get(pid, ())):
            walk(child, seen)

    walk(root_pid, set())
    return ordered
