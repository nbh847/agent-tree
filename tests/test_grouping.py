"""grouping 模块的离线单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tree.grouping import (
    build_tree,
    find_project_root,
    group_sort_key,
    session_sort_key,
)
from agent_tree.model import (
    UNKNOWN_DIR_KEY,
    UNKNOWN_DIR_LABEL,
    AgentKind,
    AgentSession,
    PaneState,
)


def make_session(
    pane_id: str = "%0",
    cwd: str | None = "/tmp/proj",
    *,
    session: str = "s0",
    window_index: int = 1,
    pane_index: int = 1,
    agent: AgentKind = AgentKind.CLAUDE_CODE,
) -> AgentSession:
    return AgentSession(
        session_key=f"/sock#{pane_id}",
        host_key="/sock",
        backend="tmux",
        backend_target=pane_id,
        cwd=cwd,
        canonical_cwd=cwd,
        cwd_source="pane_current_path" if cwd else "unavailable",
        agent=agent,
        display_name="Claude Code",
        marker="C",
        state=PaneState.UNKNOWN,
        state_source="not-implemented",
        confidence="high",
        observed_at=0.0,
        generation=1,
        is_active=True,
        pane_pid=100,
        session_name=session,
        window_index=window_index,
        window_name="w",
        pane_index=pane_index,
    )


class ProjectRootGroupingTests(unittest.TestCase):
    """仓库内按 git 根聚合；不在仓库内时退回工作目录。"""

    def test_sessions_in_same_repo_group_under_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "kzz-radar")
            nested = os.path.join(repo, "web")
            os.makedirs(nested)
            os.makedirs(os.path.join(repo, ".git"))
            tree = build_tree([make_session("%0", nested), make_session("%1", repo)])
            self.assertEqual(len(tree), 1)
            self.assertEqual(tree[0].key, repo)
            self.assertEqual(tree[0].label, "kzz-radar")
            self.assertEqual(len(tree[0].sessions), 2)

    def test_directory_outside_repo_keeps_its_own_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = os.path.join(tmp, "web")
            os.makedirs(plain)
            tree = build_tree([make_session("%0", plain)])
            self.assertEqual(tree[0].key, plain)
            self.assertEqual(tree[0].label, "web")

    def test_worktree_git_file_is_its_own_root(self):
        # worktree 的 .git 是文件而非目录，同样算命中，因此与主仓库各自成组
        with tempfile.TemporaryDirectory() as tmp:
            main = os.path.join(tmp, "repo")
            worktree = os.path.join(tmp, "repo-feature")
            os.makedirs(os.path.join(main, ".git"))
            os.makedirs(worktree)
            with open(os.path.join(worktree, ".git"), "w") as handle:
                handle.write("gitdir: ../repo/.git/worktrees/repo-feature\n")
            tree = build_tree([make_session("%0", main), make_session("%1", worktree)])
            self.assertEqual(len(tree), 2)

    def test_nested_repo_wins_over_outer_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            outer = os.path.join(tmp, "outer")
            inner = os.path.join(outer, "inner")
            os.makedirs(os.path.join(outer, ".git"))
            os.makedirs(os.path.join(inner, ".git"))
            self.assertEqual(find_project_root(inner), inner)

    def test_home_directory_is_not_treated_as_repo_root(self):
        # 家目录本身是 dotfiles 仓库时，不应把所有家目录下的会话并成一组
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".git"))
            nested = os.path.join(home, "work", "proj")
            os.makedirs(nested)
            with mock.patch("agent_tree.grouping.Path.home", return_value=Path(home)):
                self.assertIsNone(find_project_root(nested))

    def test_empty_path_has_no_project_root(self):
        self.assertIsNone(find_project_root(""))


class BuildTreeTests(unittest.TestCase):
    def test_groups_by_full_path(self):
        tree = build_tree([make_session("%0", "/tmp/a"), make_session("%1", "/tmp/b")])
        self.assertEqual([group.key for group in tree], ["/tmp/a", "/tmp/b"])

    def test_same_basename_different_paths_not_merged(self):
        tree = build_tree([make_session("%0", "/tmp/one/proj"), make_session("%1", "/tmp/two/proj")])
        self.assertEqual(len(tree), 2)
        self.assertEqual({group.label for group in tree}, {"proj"})

    def test_parent_and_child_directories_are_separate(self):
        tree = build_tree([make_session("%0", "/tmp/a"), make_session("%1", "/tmp/a/sub")])
        self.assertEqual([group.key for group in tree], ["/tmp/a", "/tmp/a/sub"])

    def test_symlink_and_direct_merge_when_canonical_path_equal(self):
        # tmux 已把软链接解析为真实路径，两条记录因此拥有同一 canonical_cwd
        tree = build_tree([make_session("%0", "/tmp/real"), make_session("%1", "/tmp/real")])
        self.assertEqual(len(tree), 1)
        self.assertEqual(len(tree[0].sessions), 2)

    def test_worktree_directories_stay_independent(self):
        tree = build_tree(
            [
                make_session("%0", "/tmp/repo"),
                make_session("%1", "/tmp/repo-feature"),
            ]
        )
        self.assertEqual(len(tree), 2)

    def test_unknown_cwd_grouped_last_with_label(self):
        tree = build_tree([make_session("%0", None), make_session("%1", "/tmp/a")])
        self.assertEqual(tree[-1].key, UNKNOWN_DIR_KEY)
        self.assertEqual(tree[-1].label, UNKNOWN_DIR_LABEL)
        self.assertEqual(tree[-1].display_path, "")

    def test_group_label_is_basename(self):
        tree = build_tree([make_session("%0", "/Users/mac/workspace/中文目录")])
        self.assertEqual(tree[0].label, "中文目录")
        self.assertEqual(tree[0].display_path, "/Users/mac/workspace/中文目录")

    def test_sessions_keep_insertion_order_within_group(self):
        tree = build_tree(
            [
                make_session("%2", "/tmp/a", window_index=2),
                make_session("%0", "/tmp/a", window_index=1),
            ]
        )
        self.assertEqual([s.backend_target for s in tree[0].sessions], ["%0", "%2"])

    def test_sort_keys_are_deterministic(self):
        first = make_session("%1", "/tmp/a", window_index=3, pane_index=2)
        second = make_session("%0", "/tmp/a", window_index=3, pane_index=1)
        self.assertLess(session_sort_key(second), session_sort_key(first))
        tree = build_tree([make_session("%0", None)])
        self.assertEqual(group_sort_key(tree[0])[0], 1)

    def test_sessions_sort_agents_before_unknown_and_shell(self):
        tree = build_tree(
            [
                make_session("%0", "/tmp/a", agent=AgentKind.SHELL),
                make_session("%1", "/tmp/a", agent=AgentKind.UNKNOWN),
                make_session("%2", "/tmp/a", agent=AgentKind.CLAUDE_CODE),
            ]
        )
        self.assertEqual(
            [session.agent for session in tree[0].sessions],
            [AgentKind.CLAUDE_CODE, AgentKind.UNKNOWN, AgentKind.SHELL],
        )

    def test_empty_input_gives_empty_tree(self):
        self.assertEqual(build_tree([]), ())


if __name__ == "__main__":
    unittest.main()