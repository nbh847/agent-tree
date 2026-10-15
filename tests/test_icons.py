"""图标资源、无效输入与透传协议回归。"""

import base64
import struct
import re
import unittest

from agent_tree.icons import (PLACEHOLDER, LOGO_WIDTH, delete_sequence, image_sequence,
                              logo_payload, logo_sequence, payload, placeholder_row)
from agent_tree.icons import decoration_payload, decoration_sequence
from agent_tree.model import AgentKind


class IconTests(unittest.TestCase):
    def test_folder_branch_assets_are_transparent_and_use_single_row_canvas(self):
        for kind in ("folder", "branch"):
            data = base64.b64decode(decoration_payload(kind))
            self.assertEqual(struct.unpack(">II", data[16:24]), (32, 32))
            self.assertEqual(data[25], 6)  # RGBA
            self.assertIn("c=2,r=1,U=1", decoration_sequence(kind, 42))
        self.assertEqual(decoration_payload("unknown"), "")
        self.assertEqual(decoration_sequence("folder", 0), "")

    def test_card_edges_use_three_rows_and_icon_placement_does_not_crop(self):
        for kind in ("card-left", "card-right"):
            data = base64.b64decode(decoration_payload(kind))
            self.assertEqual(struct.unpack(">II", data[16:24]), (16, 108))
            self.assertEqual(data[25], 6)
            self.assertIn("c=1,r=3,U=1", decoration_sequence(kind, 42))
        self.assertNotIn(",y=", image_sequence(AgentKind.CODEX, 42))

    def test_logo_chunking_and_placeholder_columns_preserve_payload(self):
        data = base64.b64decode(logo_payload(), validate=True)
        self.assertEqual(struct.unpack(">II", data[16:24]), (640, 160))
        sequence = logo_sequence(42)
        chunks = re.findall(r"_G([^;]+);([A-Za-z0-9+/=]+)", sequence)
        self.assertEqual("".join(chunk for _, chunk in chunks), logo_payload())
        self.assertTrue(all(len(chunk) <= 4096 for _, chunk in chunks))
        self.assertTrue(all(len(chunk) % 4 == 0 for _, chunk in chunks[:-1]))
        self.assertTrue(chunks[-1][0].endswith("m=0"))
        self.assertIn("c=24,r=3,U=1,q=2", sequence)
        self.assertEqual(placeholder_row(42, 0, LOGO_WIDTH).count(PLACEHOLDER), LOGO_WIDTH)
        self.assertEqual(logo_sequence(0), "")
        self.assertEqual(placeholder_row(42, 0, LOGO_WIDTH + 1), "")

    def test_assets_are_small_png_thumbnails(self):
        for kind in (AgentKind.CODEX, AgentKind.CLAUDE_CODE, AgentKind.CODEBUDDY, AgentKind.PI, AgentKind.SHELL):
            data = base64.b64decode(payload(kind), validate=True)
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (32, 48))
            self.assertLess(len(payload(kind)), 4096)

    def test_png_upload_and_virtual_placement_do_not_move_cursor(self):
        sequence = image_sequence(AgentKind.CODEX, 0x123456)
        self.assertTrue(sequence.startswith("\x1bPtmux;\x1b\x1b_Ga=t,f=100,t=d,i=1193046,q=2;"))
        self.assertIn(payload(AgentKind.CODEX), sequence)
        self.assertIn("a=p,i=1193046,c=2,r=1,U=1,q=2", sequence)
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
            line = placeholder_row(42, row, 4)
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
