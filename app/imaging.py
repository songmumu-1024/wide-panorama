"""图像处理工具：色彩对齐、重叠羽化融合、接缝质量指标。"""
from __future__ import annotations

import numpy as np
from PIL import Image


def to_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.uint8)


def to_image(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")


def resize(img: Image.Image, width: int, height: int) -> Image.Image:
    if img.size == (width, height):
        return img
    return img.resize((width, height), Image.LANCZOS)


def color_match(
    src: np.ndarray,
    ref: np.ndarray,
    strength: float = 0.85,
    src_sample: np.ndarray | None = None,
) -> np.ndarray:
    """把 src 的逐通道均值/标准差对齐到 ref，抑制不同调用间的色温漂移。

    src_sample 用于估计 src 的统计量（默认整幅）。续画时应传入“重叠区”，
    因为重叠区与 ref 描述的是同一块内容，用它估计才不会把整段画面校偏。
    """
    sample = src if src_sample is None else src_sample
    s = src.astype(np.float32)
    sa = sample.astype(np.float32)
    r = ref.astype(np.float32)
    s_mean = sa.reshape(-1, 3).mean(axis=0)
    s_std = sa.reshape(-1, 3).std(axis=0) + 1e-6
    r_mean = r.reshape(-1, 3).mean(axis=0)
    r_std = r.reshape(-1, 3).std(axis=0) + 1e-6
    matched = (s - s_mean) * (r_std / s_std) + r_mean
    out = strength * matched + (1 - strength) * s
    return np.clip(out, 0, 255).astype(np.uint8)


def blend_overlap(canvas: np.ndarray, segment: np.ndarray, overlap: int) -> np.ndarray:
    """把 segment 拼到 canvas 右侧，重叠区用 smoothstep 羽化。

    segment 的宽 = overlap + 新增宽；canvas 的宽 = W。
    输出宽 = W + (segment 宽 - overlap)，可无缝连续拼接。
    """
    if overlap <= 0:
        return np.concatenate([canvas, segment], axis=1)
    h, w, _ = canvas.shape
    seg_w = segment.shape[1]
    if seg_w < overlap:
        raise ValueError("延伸段比重叠区还窄，无法融合")

    t = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
    alpha = (t * t * (3.0 - 2.0 * t))[None, :, None]  # 沿宽度方向 0 -> 1，两端导数为 0

    left = canvas[:, : w - overlap]
    band = canvas[:, w - overlap:] * (1.0 - alpha) + segment[:, :overlap] * alpha
    right = segment[:, overlap:]
    return np.concatenate([left, np.rint(band).astype(np.uint8), right], axis=1)


def seam_score(arr: np.ndarray, seam_x: int, half_band: int = 2, window: int = 96) -> float:
    """接缝处的列梯度能量 / 邻域列梯度中位数。

    用邻域而不是全图中位数做基准，避免接缝落在水面、草地等高纹理区域时被误判。
    < 1.5 基本看不出接缝；> 2.5 说明重叠区内容或颜色对不上。
    """
    grad = np.abs(np.diff(arr.astype(np.float32), axis=1)).mean(axis=(0, 2))
    idx = int(np.clip(seam_x, 0, grad.shape[0] - 1))
    local = float(grad[max(0, idx - half_band): idx + half_band + 1].mean())

    lo = max(0, idx - window)
    hi = min(grad.shape[0], idx + window + 1)
    neighbors = np.concatenate(
        [grad[lo: max(lo, idx - half_band)], grad[min(hi, idx + half_band + 1): hi]]
    )
    ref = float(np.median(neighbors)) if neighbors.size else float(np.median(grad))
    return local / (ref + 1e-6)


def color_shift(left: np.ndarray, right: np.ndarray) -> float:
    """重叠区两侧整体色差（0~255）。"""
    n = min(left.shape[1], right.shape[1])
    if n == 0:
        return 0.0
    diff = np.abs(left[:, -n:].astype(np.float32) - right[:, :n].astype(np.float32))
    return float(diff.mean())
