"""PNG 缓存与 Kitty Graphics 图片位置标记，仅使用标准库。"""

from __future__ import annotations

import base64
from functools import cache
from importlib.resources import files

from .model import AgentKind

ICON_WIDTH = 2
ICON_HEIGHT = 3  # 条目与 Logo 占三行；会话图片仅在名称行使用一行画布。
ICON_COLUMN = 8  # 图标起点：主树干三列缩进 + 分级树线与间隔。
LOGO_WIDTH = 24
LOGO_HEIGHT = 3
PLACEHOLDER = "\U0010EEEE"
# 协议规定的行列编码；覆盖三行、24 列以及高位为零的图片 ID。
# Kitty 官方 rowcolumn-diacritics.txt 的前 24 项，覆盖顶部 Logo。
_DIACRITICS = tuple(chr(value) for value in (
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
    0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357,
    0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369,
))


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
            + _passthrough(f"\x1b_Ga=p,i={image_id},c={ICON_WIDTH},r=1,U=1,q=2\x1b\\"))


def placeholder_row(image_id: int, row: int, width: int = ICON_WIDTH) -> str:
    """指定列宽的图片位置标记；前景 RGB 编码 ID，高字节显式为零。"""
    if (not 0 < image_id <= 0xFFFFFF or not 0 <= row < ICON_HEIGHT
            or not 1 <= width <= len(_DIACRITICS)):
        return ""
    return "".join(PLACEHOLDER + _DIACRITICS[row] + _DIACRITICS[column] + _DIACRITICS[0]
                   for column in range(width))


@cache
def logo_payload() -> str:
    return base64.b64encode(files("agent_tree").joinpath("assets", "logo.png").read_bytes()).decode("ascii")


def logo_sequence(image_id: int) -> str:
    """大图按 4096 字符分块；Logo 单独拥有缓存 ID，不改变会话图标。"""
    if not 0 < image_id <= 0xFFFFFF:
        return ""
    encoded = logo_payload()
    sequences = []
    for offset in range(0, len(encoded), 4096):
        more = int(offset + 4096 < len(encoded))
        command = f"a=t,f=100,t=d,i={image_id},q=2,m={more}" if offset == 0 else f"m={more}"
        sequences.append(_passthrough(f"\x1b_G{command};{encoded[offset:offset+4096]}\x1b\\"))
    sequences.append(_passthrough(f"\x1b_Ga=p,i={image_id},c={LOGO_WIDTH},r={LOGO_HEIGHT},U=1,q=2\x1b\\"))
    return "".join(sequences)


@cache
def decoration_payload(kind: str) -> str:
    if kind not in {"folder", "branch", "card-left", "card-right"}:
        return ""
    return base64.b64encode(files("agent_tree").joinpath("assets", f"{kind}.png").read_bytes()).decode("ascii")


def decoration_sequence(kind: str, image_id: int) -> str:
    if not 0 < image_id <= 0xFFFFFF:
        return ""
    encoded = decoration_payload(kind)
    if not encoded:
        return ""
    columns, rows = (1, 3) if kind.startswith("card-") else (2, 1)
    return (_passthrough(f"\x1b_Ga=t,f=100,t=d,i={image_id},q=2;{encoded}\x1b\\")
            + _passthrough(f"\x1b_Ga=p,i={image_id},c={columns},r={rows},U=1,q=2\x1b\\"))


def delete_sequence(image_id: int) -> str:
    """只回收本实例的图片缓存与虚拟画布，不删除宿主其他图片。"""
    if not 0 < image_id <= 0xFFFFFF:
        return ""
    return _passthrough(f"\x1b_Ga=d,d=I,i={image_id},q=2\x1b\\")
