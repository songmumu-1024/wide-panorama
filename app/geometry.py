"""宽高比解析 + 分窗规划。

核心公式（设单段最大比例 P=3，段高 H，重叠 o）：

    基准段宽度        = min(W, P*H)
    最大新增宽度      = P*H - o
    需要延伸次数      = ceil((W - 基准宽) / 最大新增宽)
    第 i 次画布宽度   = o + 新增宽   <= P*H     （因此永远不超限）

最终宽度严格等于目标宽度 W，不做拉伸、不做裁切。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


def parse_ratio(value: str | float | int) -> float:
    """接受 '6:1' / '8:1' / '6x1' / '6/1' / 6 等写法，返回浮点比例。"""
    if isinstance(value, (int, float)):
        ratio = float(value)
    else:
        text = str(value).strip().lower()
        for ch in ("：", "×", "x", "/"):
            text = text.replace(ch, ":")
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", text)
        if m:
            w, h = float(m.group(1)), float(m.group(2))
            if h == 0:
                raise ValueError("宽高比的分母不能为 0")
            ratio = w / h
        elif re.fullmatch(r"\d+(?:\.\d+)?", text):
            ratio = float(text)
        else:
            raise ValueError(f"无法解析宽高比: {value!r}")
    if ratio <= 0:
        raise ValueError("宽高比必须大于 0")
    return ratio


@dataclass
class Plan:
    target_ratio: float          # 用户期望比例
    height: int                  # 最终高度
    width: int                   # 最终宽度（严格满足目标）
    base_width: int              # 首段宽度
    overlap: int                 # 相邻段重叠像素
    extensions: list[int]        # 每次延伸新增的宽度（不含重叠）
    canvas_ratios: list[float]   # 每次调用画布的宽/高，必须 <= max_single_ratio

    @property
    def calls(self) -> int:
        return 1 + len(self.extensions)

    @property
    def actual_ratio(self) -> float:
        return self.width / self.height


def plan_canvas(
    target_ratio: float,
    height: int = 1024,
    max_single_ratio: float = 3.0,
    overlap_frac: float = 0.15,
) -> Plan:
    if height < 64:
        raise ValueError("高度至少 64 像素")
    if max_single_ratio < 1.0:
        raise ValueError("单次最大宽高比必须 >= 1")

    # 全部尺寸按 8 的倍数对齐：多数图片接口要求，且能保证画布宽也落在 8 的倍数上
    height = max(8, int(round(int(height) / 8.0)) * 8)
    max_width = max(8, int(round(max_single_ratio * height / 8.0)) * 8)
    overlap = max(8, int(round(overlap_frac * max_width / 8.0)) * 8)
    overlap = min(overlap, max_width // 2)  # 重叠不能吃掉整个画布

    width = max(8, int(round(target_ratio * height / 8.0)) * 8)
    base_width = min(width, max_width)

    remaining = width - base_width
    max_new = max_width - overlap
    n = math.ceil(remaining / max_new) if remaining > 0 else 0

    extensions: list[int] = []
    left = remaining
    for i in range(n):
        per = math.ceil((left / (n - i)) / 8.0) * 8
        per = min(per, max_new, left)
        extensions.append(per)
        left -= per
    if left:  # 兜底：极端取整下补齐余量
        extensions[-1] += left

    for e in extensions:
        if e <= 0 or e > max_new:
            raise ValueError(f"分窗规划异常：新增宽度 {e} 超出上限 {max_new}")

    return Plan(
        target_ratio=target_ratio,
        height=height,
        width=width,
        base_width=base_width,
        overlap=overlap,
        extensions=extensions,
        canvas_ratios=[(overlap + e) / height for e in extensions],
    )
