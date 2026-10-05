"""processes 模块的离线单元测试。"""

from __future__ import annotations

import unittest

from agent_tree import processes


class ParseTests(unittest.TestCase):
    def test_parse_reads_pid_ppid_and_argv(self):
        text = (
            "  100   1 /sbin/launchd\n"
            "  200 100 /usr/local/bin/node /tmp/app.js\n"
            "\n"
            "   坏行\n"
        )
        procs = processes._parse(text)
        self.assertEqual(procs[100].ppid, 1)
        self.assertEqual(procs[100].argv, ("/sbin/launchd",))
        self.assertEqual(procs[200].argv, ("/usr/local/bin/node", "/tmp/app.js"))
        self.assertEqual(len(procs), 2)

    def test_parse_tolerates_missing_command(self):
        procs = processes._parse("  300   1\n")
        self.assertEqual(procs[300].argv, ())


class ExeNameTests(unittest.TestCase):
    def test_strips_directory(self):
        proc = processes.ProcInfo(pid=1, ppid=0, argv=("/Users/mac/.local/bin/claude",))
        self.assertEqual(proc.exe_name, "claude")

    def test_normalises_login_shell_dash(self):
        proc = processes.ProcInfo(pid=1, ppid=0, argv=("-zsh",))
        self.assertEqual(proc.exe_name, "zsh")

    def test_empty_argv(self):
        self.assertEqual(processes.ProcInfo(pid=1, ppid=0, argv=()).exe_name, "")


class SubtreeTests(unittest.TestCase):
    def setUp(self):
        self.procs = {
            100: processes.ProcInfo(100, 1, ("-zsh",)),
            101: processes.ProcInfo(101, 100, ("/Users/mac/.local/bin/claude",)),
            102: processes.ProcInfo(102, 101, ("/usr/bin/pgrep",)),
            200: processes.ProcInfo(200, 1, ("/bin/sleep", "900")),
        }

    def test_subtree_includes_root_and_descendants_only(self):
        pids = [proc.pid for proc in processes.subtree(self.procs, 100)]
        self.assertEqual(sorted(pids), [100, 101, 102])

    def test_subtree_of_leaf_is_itself(self):
        self.assertEqual([p.pid for p in processes.subtree(self.procs, 200)], [200])

    def test_unknown_root_gives_empty(self):
        self.assertEqual(processes.subtree(self.procs, 999), [])

    def test_cycle_does_not_loop_forever(self):
        cyclic = {
            1: processes.ProcInfo(1, 2, ("a",)),
            2: processes.ProcInfo(2, 1, ("b",)),
        }
        self.assertEqual(len(processes.subtree(cyclic, 1)), 2)


if __name__ == "__main__":
    unittest.main()