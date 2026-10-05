"""agent-tree 命令入口。

三种模式：

- ``agent-tree``：在 tmux 内当前 window 左侧创建自建侧栏 pane（默认）。
- ``agent-tree --snapshot``：一次性打印聚合树后退出，不依赖终端。
- ``agent-tree --in-pane``：在当前 pane 内运行侧栏界面，由创建侧栏时内部调用。
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys

from . import discovery, tui
from .grouping import build_tree
from .model import AgentSession, Tree
from .sidebar import DEFAULT_WIDTH, SidebarError, SidebarManager, new_instance_id
from .tmux import Tmux, TmuxError, TmuxUnavailable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-tree", description="tmux Agent 会话侧栏")
    parser.add_argument(
        "--socket",
        default=None,
        help="目标 tmux socket 名；默认使用当前环境中的 socket",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=tui.DEFAULT_REFRESH_SECONDS,
        help=f"刷新间隔秒数（默认 {tui.DEFAULT_REFRESH_SECONDS}）",
    )
    parser.add_argument(
        "--width",
        default=DEFAULT_WIDTH,
        help="侧栏宽度，取 tmux -l 的值（默认占总宽 30%%，也可写绝对列数）",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="只打印一次树结构后退出，不启动界面",
    )
    parser.add_argument(
        "--in-pane",
        action="store_true",
        help="在当前 pane 内运行侧栏界面（内部使用）",
    )
    parser.add_argument("--instance", default=None, help="侧栏实例标识（内部使用）")
    parser.add_argument("--client", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target-pane", default=None, help=argparse.SUPPRESS)
    return parser


def _snapshot(tmux: Tmux) -> int:
    host_key = tmux.server_key()
    tree = build_tree(
        discovery.discover(tmux, host_key, generation=1, only_attached=True)
    )
    print(tui.format_tree_text(tree, host_key))
    return 0


def _launch(tmux: Tmux, current_pane: str, width: str, instance: str | None) -> int:
    manager = SidebarManager(tmux, instance or new_instance_id(), width=width)
    location = manager.location_of(current_pane)
    if location is None:
        print("agent-tree: 无法确定当前 pane 的位置", file=sys.stderr)
        return 2
    try:
        pane_id = manager.launch(location.window)
    except (SidebarError, TmuxError) as exc:
        manager.teardown()
        print(f"agent-tree: {exc}", file=sys.stderr)
        return 4
    print(f"agent-tree: 侧栏已启动（{pane_id}）。在侧栏内按 q 退出，只清理该侧栏。")
    return 0


def _run_in_pane(tmux: Tmux, current_pane: str, interval: float, instance: str | None,
                 width: str = DEFAULT_WIDTH, client_name: str | None = None,
                 target_pane: str | None = None) -> int:
    # 界面框架只在交互模式才需要，--snapshot 不因此多出依赖与启动开销。
    from . import ui

    instance_id = instance or new_instance_id()
    manager = SidebarManager(tmux, instance_id, width=width, pane_id=current_pane,
                             client_name=client_name, target_pane=target_pane)
    try:
        # 认领并标记自己：既避免启动瞬间被自己发现为「未知」条目，
        # 也拒绝接管不是本程序创建的 pane。
        manager.claim_pane(current_pane)
    except SidebarError as exc:
        print(f"agent-tree: {exc}", file=sys.stderr)
        return 2

    generations = itertools.count(1)
    host_key: list[str] = []
    #: 本次侧栏运行期间曾附着过的 session。导航会 switch-client 使原 session 断开，
    #: 记住它们，避免「选走之后原窗口从列表消失」。
    keep_sessions: set[str] = set()

    def refresh() -> Tree:
        # host_key 只解析一次：socket 路径在会话期间不变，省去每次刷新的额外 tmux 调用。
        if not host_key:
            host_key.append(tmux.server_key())
        sessions = discovery.discover(
            tmux,
            host_key[0],
            generation=next(generations),
            only_attached=True,
            keep_sessions=keep_sessions,
        )
        return build_tree(sessions)

    model = tui.SidebarModel(refresh, interval)
    model.can_navigate = True
    model.sync_host = manager.follow_client
    model.active_pane = target_pane

    def sidebar_window() -> tuple[str, int] | None:
        """侧栏 pane 当前所在的 session 与 window；pane 失效时为 ``None``。

        供模型判断侧栏旁的用户 pane 是否全部关闭（如旁边的 shell 执行 exit）。
        """
        location = manager.location_of(current_pane)
        if location is None:
            return None
        return location.session_name, location.window_index

    model.sidebar_window = sidebar_window

    def open_target(session: AgentSession) -> None:
        """进入选中会话：切换视图并把输入焦点交给目标 pane。

        Enter／→／Esc／鼠标点击都走这里，行为一致——用户要的是「进去」，也就是焦点
        落到那个 shell／Agent 上。需要在同一 session 内换 window 时侧栏跟着迁移；
        跨 session 时会切换发起 client（原 session 仍保留在列表里可切回）。
        """
        try:
            manager.navigate(
                session.session_name,
                session.window_index,
                session.backend_target,
                focus_target=True,
            )
        except SidebarError as exc:
            model.message = str(exc)
        else:
            model.message = ""

    model.on_navigate = open_target
    model.on_handoff = open_target
    model.on_new_session = manager.new_session

    def check_mouse() -> None:
        # 放在占位帧之后执行：tmux 查询较慢，不应拖慢侧栏首次出现。
        location = manager.location_of(current_pane)
        if location is not None and not tmux.mouse_enabled(location.session_name):
            model.message = "鼠标点击未启用（tmux mouse off）；键盘操作可用"

    try:
        ui.run_sidebar(model, check_mouse)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 - 侧栏界面失败不应影响用户其他 pane
        print(f"agent-tree: 界面启动失败：{exc}", file=sys.stderr)
        return 3
    finally:
        # 退出时把导航带走的终端送回它原来的 session：否则那个 session 会一直
        # detached，下次启动侧栏时因「只看附着会话」而看不到它。
        manager.restore_client()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tmux = Tmux(socket=args.socket)
    try:
        tmux.ensure_server()
    except TmuxUnavailable as exc:
        print(f"agent-tree: {exc}", file=sys.stderr)
        return 2

    if args.snapshot:
        return _snapshot(tmux)

    current_pane = os.environ.get("TMUX_PANE")
    if not current_pane:
        print("agent-tree: 请在 tmux 内运行（未检测到 TMUX_PANE）", file=sys.stderr)
        return 2

    if args.in_pane:
        return _run_in_pane(tmux, current_pane, args.interval, args.instance,
                            args.width, args.client, args.target_pane)
    return _launch(tmux, current_pane, args.width, args.instance)


if __name__ == "__main__":
    raise SystemExit(main())
