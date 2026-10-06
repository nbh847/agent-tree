"""自建侧栏 pane 的生命周期与导航。

侧栏由本程序创建，使用 pane 级用户选项 ``@agent_tree_sidebar`` 标记实例所有权。
退出或异常终止只清理自己创建的 pane，不触碰用户 pane、进程与全局配置。

跨 window 持续显示采用「迁移单个自建侧栏」：导航时把侧栏 ``join-pane`` 进目标
window，再切换发起 client，最后把焦点交回侧栏。
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .tmux import SEP, SIDEBAR_OPTION, Tmux, TmuxCommandError

#: 侧栏默认宽度。
DEFAULT_WIDTH = "24%"
#: 小于该列数时拒绝创建侧栏，避免侧栏本身无法使用。
MIN_TERMINAL_COLUMNS = 60


class SidebarError(RuntimeError):
    """侧栏创建、导航或清理失败。"""


def new_instance_id() -> str:
    """生成实例标识，用于区分多个侧栏并避免互相回收。"""
    return uuid.uuid4().hex[:12]


def source_root() -> str:
    """本包所在 ``src`` 目录，供侧栏子进程设置 ``PYTHONPATH``。"""
    return str(Path(__file__).resolve().parents[1])


@dataclass(frozen=True)
class ClientContext:
    """一个 tmux client 的位置与活跃度。"""

    name: str
    session_name: str
    window_index: int
    pane_id: str
    activity: int


@dataclass(frozen=True)
class Location:
    """pane 所在的 session 与 window。"""

    session_name: str
    window_index: int

    @property
    def window(self) -> str:
        return f"{self.session_name}:{self.window_index}"


def _to_int(value: str, default: int = -1) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def list_clients(tmux: Tmux) -> list[ClientContext]:
    """读取所有 client 的上下文。

    control client 没有 tty，不能用 ``display-message -c`` 读取上下文，必须走
    ``list-clients`` 逐 client 读取。
    """
    fmt = SEP.join(
        [
            "#{client_name}",
            "#{session_name}",
            "#{window_index}",
            "#{pane_id}",
            "#{client_activity}",
        ]
    )
    clients: list[ClientContext] = []
    for line in tmux.run("list-clients", "-F", fmt).stdout.splitlines():
        fields = line.split(SEP)
        if len(fields) != 5:
            continue
        clients.append(
            ClientContext(
                name=fields[0],
                session_name=fields[1],
                window_index=_to_int(fields[2]),
                pane_id=fields[3],
                activity=_to_int(fields[4], 0),
            )
        )
    return clients


class SidebarManager:
    """管理本实例自建侧栏 pane 的创建、迁移、导航与清理。"""

    def __init__(
        self,
        tmux: Tmux,
        instance_id: str,
        width: str = DEFAULT_WIDTH,
        pane_id: str | None = None,
        client_name: str | None = None,
        target_pane: str | None = None,
    ) -> None:
        self.tmux = tmux
        self.instance_id = instance_id
        self.width = width
        self.pane_id = pane_id
        self.last_target = target_pane
        self._synced_target: str | None = None
        self.client_name = client_name
        #: 被导航 ``switch-client`` 带走的 client：``(name, 原 session, 带到的 session)``。
        #: 退出侧栏时要把它送回原 session，否则它的原 session 会一直被留在 detached，
        #: 下次启动侧栏时因「只看附着会话」而看不到。
        self._borrowed_client: tuple[str, str, str] | None = None

    # ---- 查询 ----

    def owned_panes(self) -> list[str]:
        """所有 agent-tree 实例创建的侧栏 pane。"""
        fmt = SEP.join(["#{pane_id}", f"#{{{SIDEBAR_OPTION}}}"])
        panes = []
        for line in self.tmux.run("list-panes", "-a", "-F", fmt).stdout.splitlines():
            fields = line.split(SEP)
            if len(fields) == 2 and fields[1]:
                panes.append(fields[0])
        return panes

    def is_mine(self, pane_id: str) -> bool:
        """该 pane 是否由本实例创建（只回收自己的资源）。"""
        completed = self.tmux.run(
            "display-message", "-p", "-t", pane_id, f"#{{{SIDEBAR_OPTION}}}", check=False
        )
        return completed.returncode == 0 and completed.stdout.strip() == self.instance_id

    def claim_pane(self, pane_id: str) -> None:
        """把当前 pane 认领为本实例的侧栏。

        只接受由 agent-tree 启动的 pane（启动命令来自本程序）或已属于本实例的 pane。
        否则 ``--in-pane`` 被误用在用户自己的 shell pane 上时，导航会把这个用户 pane
        迁移到别的 window，属于破坏性行为，因此这里直接拒绝。
        """
        owner = self.tmux.run(
            "display-message", "-p", "-t", pane_id, f"#{{{SIDEBAR_OPTION}}}", check=False
        ).stdout.strip()
        if owner and owner != self.instance_id:
            raise SidebarError(f"该 pane 已属于另一个 agent-tree 实例（{owner}），拒绝接管")
        if not owner:
            start_command = self.tmux.run(
                "display-message", "-p", "-t", pane_id, "#{pane_start_command}", check=False
            ).stdout.strip()
            if "agent_tree" not in start_command:
                raise SidebarError(
                    "该 pane 不是由 agent-tree 启动的，拒绝接管；请在 tmux 内运行 agent-tree"
                )
        self.tmux.run("set-option", "-p", "-t", pane_id, SIDEBAR_OPTION, self.instance_id)

    def alive(self, pane_id: str) -> bool:
        return (
            self.tmux.run(
                "display-message", "-p", "-t", pane_id, "#{pane_id}", check=False
            ).returncode
            == 0
        )

    def location_of(self, pane_id: str) -> Location | None:
        completed = self.tmux.run(
            "display-message",
            "-p",
            "-t",
            pane_id,
            "#{session_name}" + SEP + "#{window_index}",
            check=False,
        )
        if completed.returncode != 0:
            return None
        fields = completed.stdout.strip().split(SEP)
        if len(fields) != 2:
            return None
        return Location(fields[0], _to_int(fields[1]))

    def initiating_client(self) -> ClientContext | None:
        """当前正在注视侧栏所在 window 的 client；多个时取最近活跃的。"""
        if self.pane_id is None:
            return None
        if self.client_name is not None:
            return next((c for c in list_clients(self.tmux) if c.name == self.client_name), None)
        location = self.location_of(self.pane_id)
        if location is None:
            return None
        candidates = [
            client
            for client in list_clients(self.tmux)
            if (client.session_name, client.window_index)
            == (location.session_name, location.window_index)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda client: client.activity)

    # ---- 生命周期 ----

    def enable_images(self) -> bool:
        """只在本实例自建 pane 上启用透传；不支持时保留文字界面。"""
        if self.pane_id is None or not self.is_mine(self.pane_id):
            return False
        return self.tmux.run("set-option", "-p", "-t", self.pane_id,
                             "allow-passthrough", "on", check=False).returncode == 0

    def image_origin(self) -> tuple[int, int, str] | None:
        """图片的宿主坐标原点；不可见、缩放或 client 裁剪时停止透传。"""
        if self.pane_id is None or self.client_name is None:
            return None
        tokens = ("client_session", "session_name", "window_active", "window_zoomed_flag",
                  "pane_left", "pane_top", "client_width", "client_height",
                  "window_width", "window_height", "status-position", "status", "window_id")
        result = self.tmux.run("display-message", "-p", "-c", self.client_name,
                               "-t", self.pane_id,
                               SEP.join(f"#{{{token}}}" for token in tokens), check=False)
        fields = result.stdout.strip().split(SEP)
        if result.returncode or len(fields) != len(tokens):
            return None
        client_session, session, active, zoomed, *rest = fields
        if client_session != session or active != "1" or zoomed != "0":
            return None
        left, top, client_width, client_height, width, height = map(_to_int, rest[:6])
        if min(left, top, width, height) < 0 or client_width < width or client_height < height:
            return None
        status = 1 if rest[7] == "on" else max(0, _to_int(rest[7], 0))
        # 返回窗口 ID，让界面识别同尺寸迁移；PNG 缓存由位置标记复用。
        return left, top + (status if rest[6] == "top" else 0), rest[8]

    def launch(self, target_window: str) -> str:
        """在目标 window 左侧创建自建侧栏 pane 并返回其 ``pane_id``。"""
        width = self.tmux.run(
            "display-message", "-p", "-t", target_window, "#{window_width}"
        ).stdout.strip()
        if _to_int(width, 0) < MIN_TERMINAL_COLUMNS:
            raise SidebarError(
                f"window 过窄（{width} 列，至少需要 {MIN_TERMINAL_COLUMNS} 列），未创建侧栏"
            )

        for pane in self.owned_panes():
            location = self.location_of(pane)
            if location is not None and location.window == target_window:
                raise SidebarError(f"{target_window} 已有 agent-tree 侧栏，未重复创建")

        command = [sys.executable, "-m", "agent_tree", "--in-pane", "--instance", self.instance_id]
        command += ["--width", self.width]
        candidates = [c for c in list_clients(self.tmux)
                      if f"{c.session_name}:{c.window_index}" == target_window]
        if candidates:
            client = max(candidates, key=lambda c: c.activity)
            self.client_name = client.name
            self.last_target = client.pane_id
            command += ["--client", client.name, "--target-pane", client.pane_id]
        if self.tmux.socket:
            command += ["--socket", self.tmux.socket]

        # 显式传递启动终端类型，避免沿用 tmux server 的旧终端环境。
        protocol = "iterm" if (os.environ.get("TERM_PROGRAM") == "iTerm.app"
                               or os.environ.get("ITERM_SESSION_ID")) else ""

        try:
            pane_id = self.tmux.run(
                "split-window",
                "-b",
                "-h",
                "-t",
                target_window,
                "-l",
                self.width,
                "-P",
                "-F",
                "#{pane_id}",
                "-e",
                f"PYTHONPATH={source_root()}",
                "-e",
                f"AGENT_TREE_IMAGE_PROTOCOL={protocol}",
                *command,
            ).stdout.strip()
        except TmuxCommandError as exc:
            raise SidebarError(f"创建侧栏失败：{exc}") from exc
        if not pane_id:
            raise SidebarError("创建侧栏失败：未返回 pane_id")

        try:
            self.tmux.run("set-option", "-p", "-t", pane_id, SIDEBAR_OPTION, self.instance_id)
        except TmuxCommandError as exc:
            self.tmux.run("kill-pane", "-t", pane_id, check=False)
            raise SidebarError(f"标记侧栏所有权失败：{exc}") from exc
        self.pane_id = pane_id
        return pane_id

    def teardown(self) -> None:
        """只清理本实例创建的侧栏 pane。

        用户 pane 与进程保留；未被用户改动的布局由 tmux 在 pane 关闭时自动还原，
        已改动的布局保持用户的新结构，不套用旧快照。
        """
        pane_id, self.pane_id = self.pane_id, None
        self.restore_client()
        if pane_id is None or not self.is_mine(pane_id):
            return
        self.tmux.run("kill-pane", "-t", pane_id, check=False)

    # ---- 导航 ----

    def follow_client(self) -> str | None:
        """跟随绑定终端的当前窗口，只迁移侧栏，保留目标输入焦点。

        client 已断开时不接管其他 client；目标关闭或过窄时提示并留待下一轮刷新。
        """
        if self.client_name is None or self.pane_id is None:
            return None
        client = self.initiating_client()
        if client is None:
            return None
        location = self.location_of(self.pane_id)
        if location is None:
            return None
        if self._borrowed_client is not None and client.session_name != self._borrowed_client[2]:
            self._borrowed_client = None  # 用户主动切换后不再还原旧的导航起点。
        if (client.session_name, client.window_index) != (location.session_name, location.window_index):
            if not self.is_mine(self.pane_id) or not self.alive(client.pane_id):
                raise SidebarError("侧栏或当前目标 pane 已失效")
            for pane in self.owned_panes():
                if pane != self.pane_id and self.location_of(pane) == Location(client.session_name, client.window_index):
                    raise SidebarError("当前窗口已有其他侧栏，未重复迁入")
            width = self.tmux.run("display-message", "-p", "-t", client.pane_id, "#{window_width}").stdout.strip()
            if _to_int(width, 0) < MIN_TERMINAL_COLUMNS:
                raise SidebarError("当前窗口过窄，无法迁入侧栏")
            try:
                self.tmux.run("join-pane", "-d", "-b", "-h", "-s", self.pane_id,
                              "-t", client.pane_id, "-l", self.width)
            except TmuxCommandError as exc:
                raise SidebarError(f"跟随窗口失败：{exc}") from exc
        if client.pane_id != self.pane_id:
            self.last_target = client.pane_id
            self._synced_target = client.pane_id
            return client.pane_id
        if self.last_target != self._synced_target:
            self._synced_target = self.last_target
            return self.last_target
        return None

    def navigate(
        self,
        target_session: str,
        target_window_index: int,
        target_pane: str,
        *,
        focus_target: bool = False,
    ) -> None:
        """进入目标视图：迁移侧栏、必要时切换 client、聚焦目标 pane。

        ``focus_target=False`` 时焦点保留在侧栏，``True`` 时交给目标 pane。目标失效
        或迁移失败时抛出 :class:`SidebarError`，由调用方提示且不改变当前视图。

        侧栏独占原 window 且目标在别的 session 时，先切 client 再迁移：若先迁移，
        原 window 会因没有剩余 pane 被销毁，client 所在 session 随之消亡，client 会被
        直接断开而不是跟着去目标 session。此顺序下若 join-pane 失败，client 已先切走。
        """
        if self.pane_id is None or not self.alive(self.pane_id):
            raise SidebarError("侧栏已不存在")
        if not self.alive(target_pane):
            raise SidebarError("目标 pane 已失效")

        window = f"{target_session}:{target_window_index}"
        client = self.initiating_client()
        location = self.location_of(self.pane_id)

        commands: list[tuple[str, ...]] = []
        switching = client is not None and client.session_name != target_session
        switch = ("switch-client", "-c", client.name, "-t", window) if switching else None
        if location is not None and location.window != window:
            if switch is not None and self._alone_in_window(location):
                commands.append(switch)  # 先带走 client，避免空窗口销毁导致断开。
            commands.append((
                "join-pane", "-d", "-b", "-h", "-s", self.pane_id,
                "-t", window, "-l", self.width,
            ))
        if switch is not None:
            if switch not in commands:
                commands.append(switch)
        else:
            commands.append(("select-window", "-t", window))
        focus = target_pane if focus_target else self.pane_id
        commands.append(("select-pane", "-t", focus))
        # 一次提交到同一命令队列，避免每个子进程之间呈现迁移／切窗中间帧。
        args: list[str] = []
        for command in commands:
            if args:
                args.append(";")
            args.extend(command)
        try:
            self.tmux.run(*args)
        except TmuxCommandError as exc:
            # 队列遇错停止；独占窗口时前置 switch 可能已经成功。
            if switching and any(c.name == client.name and c.session_name == target_session
                                 for c in list_clients(self.tmux)):
                self._remember_client(client, target_session)
            raise SidebarError(f"导航失败：{exc}") from exc
        if switching:
            self._remember_client(client, target_session)
        self.last_target = target_pane

    def _alone_in_window(self, location: Location) -> bool:
        """侧栏是否是其所在 window 的唯一 pane。"""
        completed = self.tmux.run(
            "list-panes", "-t", location.window, "-F", "#{pane_id}", check=False
        )
        return completed.returncode == 0 and completed.stdout.split() == [self.pane_id]

    def _remember_client(self, client: ClientContext, target_session: str) -> None:
        """记录成功切换的 client，以便退出时送回原 session。"""
        if self._borrowed_client is not None and self._borrowed_client[0] == client.name:
            origin = self._borrowed_client[1]
        else:
            origin = client.session_name
        self._borrowed_client = (client.name, origin, target_session)

    def restore_client(self) -> None:
        """把导航带走的 client 送回它原来的 session；退出侧栏时调用。

        只在该 client 仍停在我们把它带去的地方时还原——若用户自己又切换过，就不再
        干预。侧栏退出后用户各标签页回到各自 session，原 session 也就不会一直 detached。
        """
        borrowed, self._borrowed_client = self._borrowed_client, None
        if borrowed is None:
            return
        name, origin, moved_to = borrowed
        for client in list_clients(self.tmux):
            if client.name != name:
                continue
            if client.session_name == moved_to:
                self.tmux.run("switch-client", "-c", name, "-t", origin, check=False)
            return

    # ---- 新建会话 ----

    def new_session(self, cwd: str) -> str:
        """在 ``cwd`` 下新建 session，并把侧栏与发起 client 一起带过去。

        这是唯一会新建用户终端的操作，只在用户显式按键时调用；新 session 里跑的是
        用户的默认 shell，不向其发送任何输入。建好后复用 :meth:`navigate`，因此同样
        只迁移自建侧栏 pane，不触碰用户既有 pane 与布局。

        ``new-session -d`` 默认按 80x24 建窗口，``join-pane -l 30%`` 会按 80 列算出
        侧栏宽度，``switch-client`` 后窗口放大重排时侧栏被摊宽；按侧栏当前窗口尺寸
        创建（``-x``／``-y``）可以让宽度比例从头就正确。
        """
        size = self.tmux.run(
            "display-message",
            "-p",
            "-t",
            self.pane_id,
            "#{window_width}" + SEP + "#{window_height}",
        ).stdout.strip().split(SEP)
        name = self.tmux.run(
            "new-session",
            "-d",
            "-c",
            cwd,
            "-x",
            size[0],
            "-y",
            size[1],
            "-P",
            "-F",
            "#{session_name}",
        ).stdout.strip()
        if not name:
            raise SidebarError("新建会话失败：未返回 session 名")
        fields = self.tmux.run(
            "display-message", "-p", "-t", name, "#{window_index}" + SEP + "#{pane_id}"
        ).stdout.strip().split(SEP)
        if len(fields) != 2 or not fields[1]:
            raise SidebarError("新建会话失败：无法定位其窗口")
        self.navigate(name, _to_int(fields[0], 1), fields[1])
        return name
