"""离线 Mock 后端：按“世界坐标”渲染一幅连续的全景，用来验证拼接几何与融合算法。

它不是 AI 生图，仅用于无 API Key 时跑通链路、做回归测试。
由于场景由世界坐标连续定义，只要拼接偏移算对，接缝处像素天然连续，
因此接缝指标可以直接反映“拼错了没有”。
"""
from __future__ import annotations

import numpy as np

from ..imaging import to_image
from .base import GenContext, ImageProvider


def _render_scene(x0: float, width: int, height: int, seed: int, variant: int = 0) -> np.ndarray:
    """渲染全景世界在 [x0, x0+width) 区间的窗口。所有元素都是世界坐标的连续函数。"""
    rng = np.random.default_rng(seed + variant * 9973)
    hue = float(rng.uniform(-0.05, 0.05))

    xs = (x0 + np.arange(width, dtype=np.float32)) / float(height)
    ys = np.arange(height, dtype=np.float32) / float(height)
    X = xs[None, :]
    Y = ys[:, None]
    horizon = 0.58

    top = np.array([0.05 + hue, 0.115, 0.26], dtype=np.float32)
    mid = np.array([0.30, 0.46, 0.72], dtype=np.float32)
    warm = np.array([0.96, 0.63 + hue, 0.36], dtype=np.float32)

    t = np.clip(Y / horizon, 0.0, 1.0)[:, 0]
    below = mid + (warm - mid) * np.clip((t - 0.55) / 0.45, 0, 1)[:, None]
    above = top + (mid - top) * np.clip(t / 0.5, 0, 1)[:, None]
    sky = np.where((t < 0.5)[:, None], above, below).astype(np.float32)

    img = np.broadcast_to(sky[:, None, :], (height, width, 3)).copy()

    sun_x = 2.1 + variant * 2.6
    d2 = ((X - sun_x) / 0.15) ** 2 + ((Y - 0.50) / 0.12) ** 2
    glow = np.exp(-d2).astype(np.float32)
    img += glow[..., None] * np.array([1.0, 0.62, 0.30], dtype=np.float32) * 0.55
    img += (np.exp(-d2 * 10.0)[..., None]) * np.array([1.0, 0.95, 0.80], dtype=np.float32) * 0.75

    # 远山轮廓：世界的确定函数
    ridge = horizon - (0.14 + 0.055 * np.sin(1.6 * X + 1.1) + 0.028 * np.sin(4.3 * X + 0.6))
    mountain = (Y > ridge) & (Y < horizon)
    mtn_l = (0.13 + 0.16 * np.clip((horizon - Y) / 0.28, 0, 1))[..., None]
    mtn_col = mtn_l * np.array([0.85, 1.0, 1.25], dtype=np.float32)
    img = np.where(mountain[..., None], mtn_col, img)

    # 地平线附近的雾带，压低接缝处的对比度
    haze = ((np.abs(Y - horizon) < 0.02) & (Y < horizon))[..., None]
    img = np.where(haze, img * 0.72 + np.array([0.85, 0.62, 0.44]) * 0.28, img)

    # 水面
    water = (Y >= horizon) & (Y < 0.90)
    ripple = 0.5 + 0.5 * np.sin(38.0 * X + 5.0 * Y / horizon)
    depth = np.clip((Y - horizon) / (0.90 - horizon), 0, 1)[..., None]
    water_col = np.array([0.08, 0.17, 0.29], dtype=np.float32) + depth * np.array(
        [0.03, 0.05, 0.09], dtype=np.float32
    )
    water_col = water_col + (glow * ripple)[..., None] * np.array([0.55, 0.34, 0.18]) * 0.55
    img = np.where(water[..., None], water_col, img)

    # 近景地台
    ground = Y >= 0.90
    ground_col = np.array([0.06, 0.08, 0.12], dtype=np.float32) + (
        np.sin(9.0 * X + 3.0 * Y) * 0.012
    )[..., None]
    img = np.where(ground[..., None], ground_col, img)

    # 固定位置的灯塔：用于检查“主体是否被重复生成”
    tower = (np.abs(X - 1.30) < 0.035) & (Y > horizon - 0.30) & (Y < horizon)
    img = np.where(tower[..., None], np.array([0.88, 0.86, 0.80], dtype=np.float32), img)
    stripe = tower & (((Y * 24) % 2) < 1)
    img = np.where(stripe[..., None], np.array([0.55, 0.16, 0.14], dtype=np.float32), img)
    lamp = (np.abs(X - 1.30) < 0.045) & (Y > horizon - 0.315) & (Y <= horizon - 0.30)
    img = np.where(lamp[..., None], np.array([1.0, 0.92, 0.55], dtype=np.float32), img)

    # 轻微颗粒感，避免色带
    grain = (np.sin(21.0 * X + 7.0 * Y) * np.sin(13.0 * X - 11.0 * Y))[..., None] * 0.012
    img += grain

    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


class MockProvider(ImageProvider):
    name = "mock"
    supports_outpaint = True

    def text_to_image(self, ctx: GenContext, width: int, height: int):
        # 无条件文生图：每次调用落在不同场景区域，模拟“仅靠提示词”时的内容漂移
        return to_image(
            _render_scene(
                x0=ctx.index * 3.2 * height,
                width=width,
                height=height,
                seed=ctx.seed,
                variant=ctx.index,
            )
        )

    def outpaint(self, ctx: GenContext, context, width: int, height: int, overlap: int):
        # 以世界坐标渲染同一幅画，保证与 context 像素级对齐
        return to_image(_render_scene(x0=float(ctx.x_offset), width=width, height=height, seed=ctx.seed))
