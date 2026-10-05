"""命令入口的参数解析测试。

回归背景：argparse 会把 help 文本当作格式串处理，help 中直接出现 ``%`` 会让
``build_parser`` 抛 ``ValueError: badly formed help string``，导致启动器无法运行。
"""

from __future__ import annotations

import unittest

from agent_tree.__main__ import build_parser
from agent_tree.sidebar import DEFAULT_WIDTH


class ParserTests(unittest.TestCase):
    def test_parser_builds_and_parses_defaults_without_error(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.width, DEFAULT_WIDTH)
        self.assertFalse(args.snapshot)
        self.assertFalse(args.in_pane)
        self.assertIsNone(args.socket)
        self.assertIsNone(args.instance)

    def test_help_text_renders_without_error(self):
        # 允许 help 中含百分号；渲染时不得抛 ValueError
        text = build_parser().format_help()
        self.assertIn("--width", text)
        self.assertIn("30%", text)

    def test_width_accepts_percent_and_absolute(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["--width", "25%"]).width, "25%")
        self.assertEqual(parser.parse_args(["--width", "40"]).width, "40")

    def test_modes_are_mutually_distinguishable(self):
        parser = build_parser()
        self.assertTrue(parser.parse_args(["--snapshot"]).snapshot)
        self.assertTrue(parser.parse_args(["--in-pane"]).in_pane)
        self.assertEqual(parser.parse_args(["--instance", "abc"]).instance, "abc")


if __name__ == "__main__":
    unittest.main()