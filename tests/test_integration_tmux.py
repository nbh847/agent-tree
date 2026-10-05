"""隔离的 tmux 集成测试。

默认跳过；设置 ``AGENT_TREE_RUN_TMUX_TESTS=1`` 时执行。测试在独立 socket 上创建
自建 pane，结束后清理，不接触用户会话。
"""

from __future__ import annotations

import itertools
import contextlib
import fcntl
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest
import uuid
from pathlib import Path

from agent_tree import discovery, tui
from agent_tree.discovery import discover
from agent_tree.grouping import build_tree
from agent_tree.icons import PLACEHOLDER, payload
from agent_tree.model import AgentKind
from agent_tree.sidebar import SidebarManager, list_clients
from agent_tree.tmux import SIDEBAR_OPTION, Tmux

SOCKET = "agent-tree-itest"
ENABLED = os.environ.get("AGENT_TREE_RUN_TMUX_TESTS") == "1"


@unittest.skipUnless(ENABLED, "需要设置 AGENT_TREE_RUN_TMUX_TESTS=1")
@unittest.skipUnless(shutil.which("tmux"), "未找到 tmux")
class DiscoveryIntegrationTests(unittest.TestCase):
    """用真实 tmux pane 与真实进程验证发现、识别与分组。"""

    def setUp(self) -> None:
        self.tmux = Tmux(socket=SOCKET)
        self.tmux.run("kill-server", check=False)
        self.workdir = tempfile.mkdtemp(prefix="agent-tree-itest-")
        self.bin = os.path.join(self.workdir, "bin")
        os.makedirs(self.bin)
        # macOS 会杀死签名失效的系统二进制副本；软链接保留签名，启动命令仍为 codex。
        os.symlink("/bin/sleep", os.path.join(self.bin, "codex"))
        self.fake_codex = os.path.join(self.bin, "codex")
        self.proj = os.path.join(self.workdir, "proj")
        self.other = os.path.join(self.workdir, "other")
        os.makedirs(self.proj)
        os.makedirs(self.other)

    def tearDown(self) -> None:
        # tmux 退出后可能留下 socket 空壳文件；测试自行清理，避免反复运行堆积残留
        socket_path = self.tmux.run(
            "display-message", "-p", "#{socket_path}", check=False
        ).stdout.strip()
        self.tmux.run("kill-server", check=False)
        if socket_path:
            Path(socket_path).unlink(missing_ok=True)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _tree(self):
        return build_tree(discover(self.tmux, self.tmux.server_key()))

    def test_finds_agent_keeps_shell_and_excludes_self_owned_pane(self) -> None:
        # 用独立 session 规避 base-index 造成的 window 索引冲突，并顺带覆盖跨 session 发现
        self.tmux.run(
            "new-session", "-d", "-s", "agent", "-n", "a", "-c", self.proj,
            self.fake_codex, "900",
        )
        self.tmux.run("new-session", "-d", "-s", "shell", "-n", "a", "-c", self.other)
        self.tmux.run("new-session", "-d", "-s", "self", "-n", "a", "-c", self.other)
        self_pane = self.tmux.run(
            "list-panes", "-t", "self:a", "-F", "#{pane_id}"
        ).stdout.strip()
        self.tmux.run("set-option", "-p", "-t", self_pane, SIDEBAR_OPTION, "itest")

        tree = self._tree()
        by_key = {group.key: group for group in tree}
        self.assertEqual(
            set(by_key), {os.path.realpath(self.proj), os.path.realpath(self.other)}
        )

        (session,) = by_key[os.path.realpath(self.proj)].sessions
        self.assertEqual(session.display_name, "Codex")
        self.assertEqual(session.marker, "O")
        self.assertEqual(session.state_source, "not-implemented")
        self.assertEqual(session.generation, 0)
        self.assertEqual(session.session_name, "agent")

        # 普通 shell 保留为 Shell 条目；侧栏自身 pane（同样位于 other）被排除
        (shell,) = by_key[os.path.realpath(self.other)].sessions
        self.assertEqual(shell.display_name, "Shell")
        self.assertEqual(shell.marker, "$")

    def test_detached_live_agent_visible_after_restart(self) -> None:
        # new-session -d 建出的是 detached session（session_attached=0）
        self.tmux.run(
            "new-session", "-d", "-s", "agent", "-n", "a", "-c", self.proj,
            self.fake_codex, "900",
        )
        host = self.tmux.server_key()
        self.assertEqual(len(discover(self.tmux, host)), 1)
        self.tmux.run("new-session", "-d", "-s", "shell", "-n", "w", "-c", self.other, "/bin/sh")
        for _ in range(2):
            kept = discover(self.tmux, host, only_attached=True, keep_sessions=set())
            self.assertEqual([s.session_name for s in kept], ["agent"])
        self.tmux.run("kill-session", "-t", "agent")
        self.assertEqual(discover(self.tmux, host, only_attached=True), [])

    def test_keep_sessions_retains_detached_session(self) -> None:
        # 模拟导航把 client 切走使原 session 断开：keep_sessions 里的仍应保留
        self.tmux.run(
            "new-session", "-d", "-s", "agent", "-n", "a", "-c", self.proj,
            self.fake_codex, "900",
        )
        host = self.tmux.server_key()
        keep = {"agent"}
        kept = discover(self.tmux, host, only_attached=True, keep_sessions=keep)
        self.assertEqual([session.session_name for session in kept], ["agent"])
        self.assertEqual(keep, {"agent"})

    def test_grouping_separates_same_basename_directories(self) -> None:
        nested = os.path.join(self.workdir, "deep", "proj")
        os.makedirs(nested)
        self.tmux.run(
            "new-session", "-d", "-s", "a", "-n", "w", "-c", self.proj, self.fake_codex, "900"
        )
        self.tmux.run(
            "new-session", "-d", "-s", "b", "-n", "w", "-c", nested, self.fake_codex, "900"
        )

        tree = self._tree()
        self.assertEqual(len(tree), 2)
        self.assertEqual({group.label for group in tree}, {"proj"})

    def test_only_shells_listed_as_shell(self) -> None:
        self.tmux.run("new-session", "-d", "-s", "s", "-n", "shell", "-c", self.other)
        tree = self._tree()
        self.assertEqual(len(tree), 1)
        (session,) = tree[0].sessions
        self.assertEqual(session.display_name, "Shell")

    def _codex_sessions(self):
        return [
            session
            for group in self._tree()
            for session in group.sessions
            if session.display_name == "Codex"
        ]

    def test_pane_id_is_stable_across_join_pane(self) -> None:
        self.tmux.run(
            "new-session", "-d", "-s", "s", "-n", "a", "-c", self.proj, self.fake_codex, "900"
        )
        self.tmux.run("new-window", "-d", "-t", "s", "-n", "b", "-c", self.other)
        (session,) = self._codex_sessions()
        pane_id = session.backend_target
        self.tmux.run("join-pane", "-s", pane_id, "-t", "s:b")
        (after,) = self._codex_sessions()
        self.assertEqual(after.backend_target, pane_id)
        self.assertEqual(after.session_key, session.session_key)

    def _pane_width(self, pane_id: str) -> int:
        completed = self.tmux.run("display-message", "-p", "-t", pane_id, "#{pane_width}")
        return int(completed.stdout.strip())

    def test_new_session_keeps_sidebar_width(self) -> None:
        # new-session 默认按 80x24 建 session：join-pane 的 30% 按 80 列算，
        # client 切过去窗口放大重排后侧栏被摊宽。按当前窗口尺寸新建则全程不变。
        self.tmux.run(
            "new-session", "-d", "-s", "a", "-n", "w", "-x", "178", "-y", "40",
            "-c", self.proj, self.fake_codex, "900",
        )
        manager = SidebarManager(self.tmux, "itest-width")
        side = manager.launch("a:w")
        before = self._pane_width(side)
        self.assertEqual(before, int(178 * 0.24))
        manager.new_session(self.other)
        self.assertEqual(self._pane_width(side), before)

    def test_companion_exit_replaces_sidebar_target(self) -> None:
        # 侧栏旁的用户 pane 全部关闭（如 shell exit）后，侧栏自动补位：
        # 被关会话所在分组不在了时取全列表第一个会话。
        # 侧栏 pane 用标记过的 sleep pane 模拟，避免真实界面进程的启动时序干扰。
        self.tmux.run(
            "new-session", "-d", "-s", "a", "-n", "w", "-c", self.proj,
            self.fake_codex, "900",
        )
        self.tmux.run("new-session", "-d", "-s", "b", "-n", "w", "-c", self.other)
        side = self.tmux.run(
            "split-window", "-b", "-h", "-d", "-t", "a:w", "-l", "40%",
            "-P", "-F", "#{pane_id}", "sleep", "900",
        ).stdout.strip()
        self.tmux.run("set-option", "-p", "-t", side, SIDEBAR_OPTION, "itest-companion")
        manager = SidebarManager(self.tmux, "itest-companion", pane_id=side)

        keep: set[str] = {"a", "b"}  # 生产中侧栏所在 session 已被记录为曾附着
        generations = itertools.count(1)
        model = tui.SidebarModel(
            lambda: build_tree(
                discover(
                    self.tmux,
                    self.tmux.server_key(),
                    generation=next(generations),
                    only_attached=True,
                    keep_sessions=keep,
                )
            )
        )
        model.on_navigate = lambda session: manager.navigate(
            session.session_name, session.window_index, session.backend_target,
            focus_target=True,
        )
        model.sidebar_window = lambda: (
            (loc.session_name, loc.window_index)
            if (loc := manager.location_of(side)) is not None
            else None
        )

        model.reload()  # 旁 pane 存活：不动作
        self.assertEqual(manager.location_of(side).session_name, "a")

        panes = self.tmux.run(
            "list-panes", "-t", "a:w", "-F", "#{pane_id}"
        ).stdout.split()
        (companion,) = [pane for pane in panes if pane != side]
        self.tmux.run("kill-pane", "-t", companion)  # 模拟 shell 执行 exit

        model.reload()  # 自动补位
        self.assertEqual(manager.location_of(side).session_name, "b")
        self.assertNotIn("a", self.tmux.run(
            "list-sessions", "-F", "#{session_name}"
        ).stdout.split())


@unittest.skipUnless(ENABLED and shutil.which("tmux"), "需要启用 tmux 集成测试")
class FollowIntegrationTests(unittest.TestCase):
    """真实 client 与真实 textual 侧栏：原生切窗、跨 session 与高亮同步。"""

    def setUp(self):
        self.socket = "agent-tree-follow-" + uuid.uuid4().hex[:8]
        self.tmux = Tmux(socket=self.socket)
        self.clients = []
        self.workdir = tempfile.TemporaryDirectory(prefix="agent-tree-follow-")
        self.root = Path(__file__).resolve().parents[1]
        self.a = Path(self.workdir.name) / "alpha"
        self.b = Path(self.workdir.name) / "beta"
        self.a.mkdir()
        self.b.mkdir()
        subprocess.run(["tmux", "-L", self.socket, "-f", "/dev/null", "new-session",
                        "-d", "-s", "A", "-n", "first", "-x", "160", "-y", "32",
                        "-c", str(self.a)], check=True, capture_output=True)
        self.tmux.run("new-window", "-d", "-t", "A", "-n", "second", "-c", str(self.b))
        self.tmux.run("set-option", "-s", "terminal-features", "xterm-256color:RGB")
        self.tmux.run("new-session", "-d", "-s", "B", "-n", "third",
                      "-x", "160", "-y", "32", "-c", str(self.a))

    def tearDown(self):
        socket_path = self.tmux.run("display-message", "-p", "#{socket_path}", check=False).stdout.strip()
        self.tmux.run("kill-server", check=False)
        for pid, fd in self.clients:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)
        if socket_path:
            Path(socket_path).unlink(missing_ok=True)
        self.workdir.cleanup()

    def attach(self, target):
        before = {c.name for c in list_clients(self.tmux)}
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-L", self.socket, "attach", "-t", target])
        self.clients.append((pid, fd))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 160, 0, 0))
        os.kill(pid, signal.SIGWINCH)
        os.set_blocking(fd, False)
        return self.wait_for(lambda: next((c for c in list_clients(self.tmux) if c.name not in before), None))

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for _, fd in self.clients:
                with contextlib.suppress(BlockingIOError, OSError):
                    os.read(fd, 65536)
            result = predicate()
            if result:
                return result
            time.sleep(0.1)
        detail = repr(self.capture(self.side)) if hasattr(self, "side") else ""
        self.fail(f"等待真实侧栏状态超时：{detail}")

    def pane(self, target):
        return self.tmux.run("display-message", "-p", "-t", target, "#{pane_id}").stdout.strip()

    def capture(self, side):
        return self.tmux.run("capture-pane", "-p", "-e", "-t", side).stdout

    @staticmethod
    def highlighted_shell(text):
        # textual 在无色测试终端下会把 #21262d 映射成 #252525。
        # tmux 的 SGR 背景可跨行继承，三行高亮不必在名称行重复输出背景。
        selected = False
        for token in re.findall(r"\x1b\[[0-9;]*m|Shell", text):
            if token == "Shell":
                if selected:
                    return True
            elif token in ("\x1b[m", "\x1b[0m", "\x1b[49m"):
                selected = False
            elif "48;2;" in token:
                selected = any(bg in token for bg in (
                    "48;2;33;38;45", "48;2;37;37;37"))
        return False

    def test_native_switch_follows_and_updates_rendered_selection(self):
        owner = self.attach("A:first")
        other = self.attach("B:third")
        first, second, third = [self.pane(t) for t in ("A:first", "A:second", "B:third")]
        user_pids = {p: self.tmux.run("display-message", "-p", "-t", p, "#{pane_pid}").stdout
                     for p in (first, second, third)}
        original_layout = self.tmux.run("display-message", "-p", "-t", first, "#{window_layout}").stdout
        env = dict(os.environ, TMUX_PANE=first)
        subprocess.run([str(self.root / "bin/agent-tree"), "--socket", self.socket,
                        "--width", "35%"], env=env, cwd=self.root, check=True, capture_output=True)
        manager = SidebarManager(self.tmux, "probe")
        side = self.wait_for(lambda: next(iter(manager.owned_panes()), None))
        self.side = side
        self.wait_for(lambda: "会话" in self.capture(side) and "Shell" in self.capture(side))
        width = self.tmux.run("display-message", "-p", "-t", side, "#{pane_width}").stdout

        # prefix+n 走 tmux 原生绑定，侧栏没有发起导航。
        os.write(self.clients[0][1], b"\x02n")
        self.wait_for(lambda: manager.location_of(side) == manager.location_of(second))
        self.wait_for(lambda: "[beta]" in self.capture(side) and
                      self.highlighted_shell(self.capture(side).split("[beta]", 1)[-1]))
        self.assertEqual(self.pane("A:second"), second, "跟随不能抢输入焦点")
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", side, "#{pane_width}").stdout, width)
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", first, "#{window_layout}").stdout, original_layout)
        self.assertEqual(next(c for c in list_clients(self.tmux) if c.name == other.name).session_name, "B")

        # 原生命令跨 session，保留 B 的焦点，侧栏高亮回到 alpha 分组。
        self.tmux.run("switch-client", "-c", owner.name, "-t", "B:third")
        self.wait_for(lambda: manager.location_of(side) == manager.location_of(third))
        self.assertEqual(self.pane("B:third"), third)
        self.wait_for(lambda: self.highlighted_shell(self.capture(side).split("[beta]", 1)[0]))
        self.tmux.run("switch-client", "-c", other.name, "-t", "A:first")
        time.sleep(0.6)
        self.assertEqual(manager.location_of(side), manager.location_of(third), "其他终端不能抢走侧栏")

        self.tmux.run("switch-client", "-c", owner.name, "-t", "A:second")
        self.wait_for(lambda: manager.location_of(side) == manager.location_of(second))
        for p, pid in user_pids.items():
            self.assertEqual(self.tmux.run("display-message", "-p", "-t", p, "#{pane_pid}").stdout, pid)
        self.tmux.run("select-pane", "-t", side)
        os.write(self.clients[0][1], b"q")
        self.wait_for(lambda: manager.location_of(side) is None)
        self.assertEqual(next(c for c in list_clients(self.tmux) if c.name == owner.name).session_name, "A")
        self.assertEqual(self.tmux.run("list-panes", "-a", "-F", "#{pane_id}").stdout.split(),
                         [first, second, third])

    def test_image_frames_idle_migration_and_owned_passthrough(self):
        self.tmux.run("set-option", "-s", "focus-events", "on")
        self.tmux.run("set-option", "-t", "A:first", "mouse", "on")
        owner = self.attach("A:first")
        first, second = self.pane("A:first"), self.pane("A:second")
        for kind in ("codex", "claude"):
            executable = Path(self.workdir.name) / kind
            executable.symlink_to("/bin/sleep")
            self.tmux.run("new-window", "-d", "-t", "A", "-c", str(self.a), str(executable), "900")
        env = dict(os.environ, TMUX_PANE=first, TERM_PROGRAM="iTerm.app")
        subprocess.run([str(self.root / "bin/agent-tree"), "--socket", self.socket],
                       env=env, cwd=self.root, check=True, capture_output=True)
        manager = SidebarManager(self.tmux, "probe")
        side = None
        deadline = time.monotonic() + 20
        while side is None and time.monotonic() < deadline:
            side = next(iter(manager.owned_panes()), None)
            if side is None:
                time.sleep(0.05)
        self.assertIsNotNone(side)
        self.side = side
        fd = self.clients[0][1]
        def output(seconds, until=None):
            data = b""
            deadline = time.monotonic() + seconds
            last_output = time.monotonic()
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.05)[0]:
                    with contextlib.suppress(BlockingIOError):
                        data += os.read(fd, 65536)
                        last_output = time.monotonic()
                # 不能在 OSC 包或连续帧中途截断采集；等完整图片且输出安静下来。
                if until is not None and until(data) and time.monotonic() - last_output >= 0.3:
                    break
            return data
        kinds = (AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.SHELL)
        frame = output(20, until=lambda data: all(payload(kind).encode() in data for kind in kinds)
                       and data.count(b"U=1,q=2") == 3 and PLACEHOLDER.encode() in data)
        for kind in kinds:
            self.assertEqual(frame.count(payload(kind).encode()), 1, f"{kind.value} PNG 只上传一次")
        self.assertEqual(self.tmux.run("show-options", "-p", "-t", side,
                                      "allow-passthrough").stdout.strip(), "allow-passthrough on")
        self.assertEqual(self.tmux.run("show-options", "-g", "allow-passthrough").stdout.strip(),
                         "allow-passthrough off")
        self.assertEqual(self.tmux.run("show-options", "-p", "-t", first,
                                      "allow-passthrough").stdout.strip(), "")
        image_ids = re.findall(rb"_Ga=t,f=100,t=d,i=(\d+),q=2;", frame)
        self.assertEqual(len(set(image_ids)), 3)
        self.assertIn(PLACEHOLDER, self.capture(side), "tmux 必须保存图片位置标记")
        self.tmux.run("send-keys", "-t", side, "j")
        selected = output(1)
        self.assertNotIn(b"_Ga=t", selected, "选中变化不应重新上传 PNG")
        self.assertIn(PLACEHOLDER.encode(), selected)
        self.assertNotIn(b"_Ga=t", output(3), "空闲刷新不应重复发送图片")
        self.tmux.run("select-pane", "-t", side)
        self.assertNotIn(b"_Ga=t", output(1))
        os.write(fd, b"\x1b[<0;2;31M\x1b[<0;2;31m")
        self.assertNotIn(b"_Ga=t", output(1), "点击底栏不应重新上传图片")
        for y in list(range(2, 32)) + list(range(31, 1, -1)):
            os.write(fd, f"\x1b[<35;12;{y}M".encode())
            time.sleep(0.02)
        self.assertNotIn(b"_Ga=t", output(1), "上下移动鼠标不应重新上传图片")
        self.tmux.run("select-pane", "-t", first)
        output(1)
        for _ in range(3):
            for x, target in ((2, side), (80, first)):
                os.write(fd, f"\x1b[<0;{x};2M\x1b[<0;{x};2m".encode())
                focus_output = output(1)
                self.assertNotIn(b"_Ga=t", focus_output, "焦点切换不应重新上传 PNG")
                self.assertNotIn(b"_Ga=p", focus_output, "焦点切换不应重建图片画布")
                self.assertIn(PLACEHOLDER.encode(), focus_output,
                              "宿主重绘必须保留真实图片的位置标记")
                self.assertEqual(self.tmux.run("display-message", "-p", "-t", target,
                                              "#{pane_active}").stdout.strip(), "1")
        # 同尺寸跨 window 跟随也只移动 tmux 保存的位置标记。
        self.tmux.run("switch-client", "-c", owner.name, "-t", "A:second")
        moved = output(20, until=lambda data: PLACEHOLDER.encode() in data)
        self.assertEqual(manager.location_of(side), manager.location_of(second))
        self.assertNotIn(b"_Ga=t", moved)
        self.assertNotIn(b"_Ga=p", moved)
        self.assertEqual(self.tmux.run("show-options", "-p", "-t", side,
                                      "allow-passthrough").stdout.strip(), "allow-passthrough on")
        self.tmux.run("send-keys", "-t", side, "q")
        exited = output(1)
        for image_id in image_ids:
            self.assertIn(b"_Ga=d,d=I,i=" + image_id + b",q=2", exited)
        self.wait_for(lambda: manager.location_of(side) is None)
        self.assertTrue(manager.alive(first))
        self.assertTrue(manager.alive(second))


if __name__ == "__main__":
    unittest.main()
