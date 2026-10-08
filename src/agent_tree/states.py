"""当前 CLI 输入区的保守状态匹配；不存储屏幕，不从静默推断完成。"""

from __future__ import annotations

import re

from .model import AgentKind, PaneState

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RUNNING = re.compile(r"^\S.*\(.*\d+(?:s|m|h).*\besc to interrupt\)", re.I)
_CODEX_CLOCK = re.compile(r"^[•◦]\s+.+\(\d+(?:h(?:\s+\d+m)?(?:\s+\d+s)?|m(?:\s+\d+s)?|s)\)(?:\s|$)")
_CLAUDE_RUNNING = re.compile(r"^[✻✽✶✳✢·*].*….*\(.*(?:esc to interrupt|\d+s|\d+m)", re.I)
_CODEBUDDY_RUNNING = re.compile(r"^[✶✸✹✺✷]\s+.+…\s+\(\d+(?:s|m|h)\s*[·)]", re.I)
_CODEX_LIMIT_NOTICE = re.compile(r"^⚠ 5h limit: (?:only )?\d+% left · resets at .+ · /status$")


def detect_state(agent: AgentKind, screen: str | None) -> tuple[PaneState, str]:
    """只匹配底部实时区域；历史问句或一般正文不足以判定等待操作。"""
    if screen is None:
        return PaneState.UNKNOWN, "screen-unavailable"
    if agent not in {AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI}:
        return PaneState.UNKNOWN, "not-applicable"
    lines = [_ANSI.sub("", line).replace("\u00a0", " ").strip()
             for line in screen.splitlines()]
    # 保留空行位置，避免历史内容因去掉空白被拉入输入区。
    tail = lines[-12:]
    prompts = [i for i, line in enumerate(tail) if line.startswith(("›", "❯"))]
    if agent is AgentKind.CODEBUDDY:
        prompts += [i for i, line in enumerate(tail)
                    if line.startswith(">") and i > 0 and i + 1 < len(tail)
                    and all(re.match(r"^[─━]{5,}$", tail[j]) for j in (i - 1, i + 1))]
        prompts.sort()
    if prompts:
        # 正文位于输入框上方；仅保留紧邻最新输入框的运行指示区。
        start = max(0, prompts[-1] - 3)
        if agent is AgentKind.CODEX:
            # Codex 会在运行指示与输入框之间插入 Tip、额度提醒和空行。
            # 只跨过这些装饰行，遇到正文即停止，避免捞取历史状态。
            index = prompts[-1] - 1
            while index >= 0 and (not tail[index] or tail[index].startswith("└ Tip:")
                                  or _CODEX_LIMIT_NOTICE.fullmatch(tail[index])):
                index -= 1
            if index >= 0:
                start = min(start, index)
        elif agent is AgentKind.CODEBUDDY and prompts[-1] > 0:
            index = prompts[-1] - 1
            if re.match(r"^[─━]{5,}$", tail[index]):
                index -= 1
                while index >= 0 and (not tail[index] or tail[index].startswith("└ Tip:")):
                    index -= 1
                if index >= 0:
                    start = index
        tail = tail[start:]
    text = "\n".join(tail).lower()
    # 确认框必须同时有操作键提示和选项；普通回答中的问句不算。
    menu = any(re.match(r"^[›❯>]?\s*[1-9][.)]\s", line) for line in tail)
    controls = bool(re.search(r"(?:enter|return) to (?:select|confirm|submit)|esc to (?:cancel|deny)|escape to cancel", text))
    if menu and controls:
        return PaneState.BLOCKED, "screen:selection-dialog"
    if agent is AgentKind.CODEX:
        if any(_RUNNING.search(line) or _CODEX_CLOCK.search(line) for line in tail):
            return PaneState.WORKING, "screen:codex-status"
        prompt = next((i for i in range(len(tail) - 1, -1, -1) if tail[i].startswith("›")), None)
        if prompt is not None and any(
            "context left" in line.lower() or "? for shortcuts" in line.lower()
            or re.match(r"^(?:gpt-|o[134](?:\b|-)).*[·•]", line, re.I)
            for line in tail[prompt + 1:]
        ):
            return PaneState.IDLE, "screen:codex-composer"
    elif agent in {AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY}:
        if any(_RUNNING.search(line) or _CLAUDE_RUNNING.search(line)
               or (agent is AgentKind.CODEBUDDY and _CODEBUDDY_RUNNING.search(line))
               for line in tail):
            return PaneState.WORKING, "screen:interrupt-status"
        # Claude 风格输入框必须有上下边框，单独正文中的 ❯ 不算。
        for index, line in enumerate(tail):
            if line.startswith(("❯", ">")) and index > 0 and index + 1 < len(tail):
                if all(re.match(r"^[─━]{5,}$", tail[i]) for i in (index - 1, index + 1)):
                    return PaneState.IDLE, "screen:bounded-composer"
    elif agent is AgentKind.PI:
        if any(re.search(r"(?:working|retrying|compacting|summarizing).*\(esc to (?:interrupt|cancel)\)", line, re.I)
               for line in tail):
            return PaneState.WORKING, "screen:pi-interrupt"
    return PaneState.UNKNOWN, "screen:no-matching-signal"
