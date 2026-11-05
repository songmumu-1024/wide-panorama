"""生成后端的统一接口。

管线只依赖这两个方法，因此可以自由替换成任意模型/网关：
- text_to_image：文生图，单次画布比例不超过 MAX_SINGLE_RATIO
- outpaint：在已有画面右侧续画（若后端不支持，管线自动退化为文生图 + 融合）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image


@dataclass
class GenContext:
    prompt: str
    seed: int
    x_offset: int = 0      # 当前窗口在整幅全景中的像素起点（仅 Mock 等本地后端使用）
    total_width: int = 0   # 最终全景宽度
    index: int = 0         # 第几次调用（从 0 开始）
    total_calls: int = 1


class ProviderError(RuntimeError):
    pass


class ImageProvider:
    name = "base"
    supports_outpaint = False
    supports_seed = True

    def text_to_image(self, ctx: GenContext, width: int, height: int) -> Image.Image:
        raise NotImplementedError

    def outpaint(
        self,
        ctx: GenContext,
        context: Image.Image,
        width: int,
        height: int,
        overlap: int,
    ) -> Image.Image:
        """context 为左侧重叠区；返回 (overlap + 新增) x height 的画布。"""
        raise NotImplementedError

    def last_meta(self) -> dict:
        return {}
