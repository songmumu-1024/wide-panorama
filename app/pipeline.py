"""生成管线：规划 -> 首段 -> 逐段向右续画 -> 色彩对齐 -> 羽化融合 -> 指标落盘。"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from PIL import Image

from .geometry import plan_canvas, parse_ratio
from .imaging import (
    blend_overlap,
    color_match,
    color_shift,
    resize_cover,
    seam_score,
    to_array,
    to_image,
)
from .providers.base import GenContext, ImageProvider

ProgressFn = Callable[[int, str], None]


def build_prompts(prompt: str, index: int, total: int, overlap_ratio: float) -> tuple[str, str]:
    base = (
        f"{prompt}. Ultra-wide panoramic scene, seamless composition, consistent horizon line, "
        "natural lighting and rich detail, photographic quality, no text, no watermark."
    )
    cont = (
        f"{prompt}. Continue this panoramic scene to the right seamlessly. "
        "Keep exactly the same horizon height, camera perspective, scale, lighting direction, "
        "color grading and art style. Extend the existing elements naturally, do not repeat the "
        f"main subject, no text, no watermark, no visible seam. (segment {index + 1} of {total})"
    )
    return base, cont


@dataclass
class StepRecord:
    index: int
    mode: str
    canvas_width: int
    new_width: int
    color_shift: float
    seam_score: float
    seconds: float


@dataclass
class GenerateResult:
    provider: str
    prompt: str
    target_ratio: float
    width: int
    height: int
    actual_ratio: float
    calls: int
    overlap: int
    image_png: str
    image_jpg: str
    meta_json: str
    elapsed: float
    steps: list[StepRecord] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _save_outputs(
    arr,
    out_dir: str,
    ratio: float,
    width: int,
    height: int,
    meta: dict,
    stem: str | None = None,
) -> tuple[str, str, str]:
    os.makedirs(out_dir, exist_ok=True)
    img = to_image(arr)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"{ratio:g}".replace(".", "p")
    stem = stem or f"panorama_{slug}x1_{width}x{height}_{stamp}"
    png_path = os.path.join(out_dir, f"{stem}.png")
    jpg_path = os.path.join(out_dir, f"{stem}.jpg")
    meta_path = os.path.join(out_dir, f"{stem}.json")
    img.save(png_path)
    img.save(jpg_path, quality=92, subsampling=1)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return png_path, jpg_path, meta_path


def generate_panorama(
    prompt: str,
    ratio: str | float = "6:1",
    height: int = 1024,
    width: int | None = None,
    provider: ImageProvider | None = None,
    output_dir: str = "outputs",
    max_single_ratio: float = 3.0,
    overlap_frac: float = 0.15,
    seed: int = 20261105,
    on_progress: ProgressFn | None = None,
    stem: str | None = None,
) -> GenerateResult:
    if provider is None:
        raise ValueError("必须提供 provider")
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("提示词不能为空")

    t0 = time.time()
    target = parse_ratio(ratio)
    plan = plan_canvas(target, height, max_single_ratio, overlap_frac, width=width)
    target = plan.actual_ratio

    def notify(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(max(0, min(100, pct)), msg)

    notify(2, f"规划完成：{plan.width}×{plan.height}，共 {plan.calls} 次调用")

    base_prompt, cont_prompt = build_prompts(prompt, 0, plan.calls, plan.overlap / plan.base_width)
    ctx = GenContext(
        prompt=base_prompt,
        seed=seed,
        x_offset=0,
        total_width=plan.width,
        index=0,
        total_calls=plan.calls,
    )
    step_t0 = time.time()
    notify(5, "生成首段画面")
    base_img = resize_cover(provider.text_to_image(ctx, plan.base_width, plan.height), plan.base_width, plan.height)
    canvas = to_array(base_img)

    steps: list[StepRecord] = [
        StepRecord(
            index=0,
            mode="base",
            canvas_width=plan.base_width,
            new_width=plan.base_width,
            color_shift=0.0,
            seam_score=0.0,
            seconds=round(time.time() - step_t0, 2),
        )
    ]

    for i, ext_w in enumerate(plan.extensions, start=1):
        pct = 5 + int(90 * i / max(1, len(plan.extensions)))
        notify(pct, f"向外延伸 {i}/{len(plan.extensions)}：新增 {ext_w}px")
        _, cont_prompt = build_prompts(prompt, i, plan.calls, plan.overlap / plan.base_width)

        canvas_w = plan.overlap + ext_w
        ctx = GenContext(
            prompt=cont_prompt,
            seed=seed,
            x_offset=canvas.shape[1] - plan.overlap,
            total_width=plan.width,
            index=i,
            total_calls=plan.calls,
        )
        window = to_image(canvas[:, -plan.overlap:])

        step_t0 = time.time()
        if provider.supports_outpaint:
            seg_img = provider.outpaint(ctx, window, canvas_w, plan.height, plan.overlap)
            mode = "outpaint"
        else:
            seg_img = provider.text_to_image(ctx, canvas_w, plan.height)
            mode = "text-only"
        seg_img = resize_cover(seg_img, canvas_w, plan.height)
        seg = to_array(seg_img)

        # 融合前先量化色差，再把色彩对齐到左侧重叠区
        shift = color_shift(canvas[:, -plan.overlap:], seg[:, : plan.overlap])
        seg = color_match(seg, canvas[:, -plan.overlap:], src_sample=seg[:, : plan.overlap])

        seam_x = canvas.shape[1]
        canvas = blend_overlap(canvas, seg, plan.overlap)
        score = seam_score(canvas, seam_x)

        meta = provider.last_meta()
        steps.append(
            StepRecord(
                index=i,
                mode=meta.get("mode", mode),
                canvas_width=canvas_w,
                new_width=ext_w,
                color_shift=round(shift, 2),
                seam_score=round(score, 2),
                seconds=round(time.time() - step_t0, 2),
            )
        )

    notify(97, "校验尺寸与接缝质量")
    if canvas.shape[1] != plan.width or canvas.shape[0] != plan.height:
        raise RuntimeError(f"输出尺寸异常：{canvas.shape[1]}x{canvas.shape[0]}，期望 {plan.width}x{plan.height}")

    seam_values = [s.seam_score for s in steps[1:]] or [0.0]
    size_ok = canvas.shape[1] == plan.width and canvas.shape[0] == plan.height
    ratio_ok = (plan.width / plan.height) > max_single_ratio + 1e-9
    metrics = {
        "calls": plan.calls,
        "overlap_px": plan.overlap,
        "canvas_ratios": [round(r, 3) for r in plan.canvas_ratios],
        "max_single_call_ratio": round(max(plan.canvas_ratios), 3) if plan.canvas_ratios else round(plan.base_width / plan.height, 3),
        "seam_score_max": round(max(seam_values), 2),
        "seam_score_avg": round(sum(seam_values) / len(seam_values), 2),
        "color_shift_max": round(max([s.color_shift for s in steps[1:]] or [0.0]), 2),
        "size_ok": size_ok,
        "ratio_ok": ratio_ok,
    }

    result = GenerateResult(
        provider=provider.name,
        prompt=prompt,
        target_ratio=round(target, 4),
        width=plan.width,
        height=plan.height,
        actual_ratio=round(plan.width / plan.height, 4),
        calls=plan.calls,
        overlap=plan.overlap,
        image_png="",
        image_jpg="",
        meta_json="",
        elapsed=0.0,
        steps=steps,
        metrics=metrics,
    )

    payload = {
        "provider": provider.name,
        **{
            k: v
            for k, v in asdict(result).items()
            if k not in {"image_png", "image_jpg", "meta_json", "steps"}
        },
        "steps": [asdict(s) for s in steps],
        "metrics": metrics,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    png_path, jpg_path, meta_path = _save_outputs(
        canvas, output_dir, target, plan.width, plan.height, payload, stem
    )
    result.image_png = os.path.basename(png_path)
    result.image_jpg = os.path.basename(jpg_path)
    result.meta_json = os.path.basename(meta_path)
    result.elapsed = round(time.time() - t0, 2)

    # 二次写入完整元数据（含文件名与耗时）
    payload.update(
        {
            "image_png": result.image_png,
            "image_jpg": result.image_jpg,
            "elapsed": result.elapsed,
        }
    )
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    notify(100, "完成")
    return result
