"""PNG 缓存与 Kitty Graphics 图片位置标记，仅使用标准库。"""

from __future__ import annotations

import base64
from functools import cache
from importlib.resources import files

from .model import AgentKind

ICON_WIDTH = 4
ICON_HEIGHT = 3  # 三行画布，图案占中间两行，与文字的中间行居中对齐。
ICON_COLUMN = 5  # 名称起点：两列缩进 + 三列树线。
PLACEHOLDER = "\U0010EEEE"
# 协议规定的行列编码；只需三行、四列以及高位为零的图片 ID。
_DIACRITICS = ("\u0305", "\u030d", "\u030e", "\u0310")


@cache
def payload(kind: AgentKind) -> str:
    """缓存随包发布的缩略图；未知身份不猜测图标。"""
    if kind == AgentKind.UNKNOWN:
        return ""
    data = files("agent_tree").joinpath("assets", f"{kind.value}.png").read_bytes()
    return base64.b64encode(data).decode("ascii")


def _passthrough(sequence: str) -> str:
    return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"


def image_sequence(kind: AgentKind, image_id: int) -> str:
    """上传 PNG 并创建虚拟画布；实际位置由 tmux 保存的标记决定。"""
    if not 0 < image_id <= 0xFFFFFF:
        return ""
    encoded = payload(kind)
    if not encoded:
        return ""
    return (_passthrough(f"\x1b_Ga=t,f=100,t=d,i={image_id},q=2;{encoded}\x1b\\")
            + _passthrough(f"\x1b_Ga=p,i={image_id},c={ICON_WIDTH},r={ICON_HEIGHT},U=1,q=2\x1b\\"))


def placeholder_row(image_id: int, row: int) -> str:
    """四列图片位置标记；前景 RGB 编码 image_id，高字节显式为零。"""
    if not 0 < image_id <= 0xFFFFFF or not 0 <= row < ICON_HEIGHT:
        return ""
    return "".join(PLACEHOLDER + _DIACRITICS[row] + _DIACRITICS[column] + _DIACRITICS[0]
                   for column in range(ICON_WIDTH))


def delete_sequence(image_id: int) -> str:
    """只回收本实例的图片缓存与虚拟画布，不删除宿主其他图片。"""
    if not 0 < image_id <= 0xFFFFFF:
        return ""
    return _passthrough(f"\x1b_Ga=d,d=I,i={image_id},q=2\x1b\\")
