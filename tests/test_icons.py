"""图标资源、无效输入与透传协议回归。"""

import base64
import struct
import unittest

from agent_tree.icons import PLACEHOLDER, delete_sequence, image_sequence, payload, placeholder_row
from agent_tree.model import AgentKind


class IconTests(unittest.TestCase):
    def test_assets_are_small_png_thumbnails(self):
        for kind in (AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.SHELL):
            data = base64.b64decode(payload(kind), validate=True)
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (32, 48))
            self.assertLess(len(payload(kind)), 4096)

    def test_png_upload_and_virtual_placement_do_not_move_cursor(self):
        sequence = image_sequence(AgentKind.CODEX, 0x123456)
        self.assertTrue(sequence.startswith("\x1bPtmux;\x1b\x1b_Ga=t,f=100,t=d,i=1193046,q=2;"))
        self.assertIn(payload(AgentKind.CODEX), sequence)
        self.assertIn("a=p,i=1193046,c=4,r=3,U=1,q=2", sequence)
        self.assertEqual(sequence.count("\x1bPtmux;"), 2)
        self.assertNotIn("1337", sequence)
        self.assertNotIn("\x1b\x1b[", sequence)

    def test_unknown_and_invalid_ids_do_not_emit_images(self):
        self.assertIn(payload(AgentKind.CODEBUDDY), image_sequence(AgentKind.CODEBUDDY, 42))
        self.assertEqual(image_sequence(AgentKind.UNKNOWN, 42), "")
        for image_id in (-1, 0, 0x1000000):
            self.assertEqual(image_sequence(AgentKind.SHELL, image_id), "")
            self.assertEqual(delete_sequence(image_id), "")
            self.assertEqual(placeholder_row(image_id, 0), "")

    def test_placeholders_encode_each_cell_and_high_id_byte(self):
        for row, mark in enumerate(("\u0305", "\u030d", "\u030e")):
            line = placeholder_row(42, row)
            self.assertEqual(line.count(PLACEHOLDER), 4)
            for column, column_mark in enumerate(("\u0305", "\u030d", "\u030e", "\u0310")):
                self.assertEqual(line[column * 4:column * 4 + 4],
                                 PLACEHOLDER + mark + column_mark + "\u0305")
        self.assertEqual(placeholder_row(42, -1), "")
        self.assertEqual(placeholder_row(42, 3), "")

    def test_delete_only_frees_the_owned_image_id(self):
        sequence = delete_sequence(42)
        self.assertIn("a=d,d=I,i=42,q=2", sequence)
        self.assertNotIn("d=A", sequence)
