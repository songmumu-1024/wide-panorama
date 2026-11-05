"""离线自检：验证分窗几何、尺寸精度与接缝质量（不依赖任何外部 API）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geometry import plan_canvas
from app.pipeline import generate_panorama
from app.providers.mock import MockProvider

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "selfcheck")


def check_geometry() -> None:
    print("[1] 分窗几何")
    for ratio in (4.0, 6.0, 8.0, 12.0):
        plan = plan_canvas(ratio, height=1024)
        assert plan.width == round(ratio * 1024 / 8) * 8, plan
        assert plan.base_width + sum(plan.extensions) == plan.width, plan
        assert all(r <= 3.0001 for r in plan.canvas_ratios), plan
        assert plan.actual_ratio > 3, plan
        assert plan.overlap > 0
        print(
            f"    {ratio:g}:1 -> {plan.width}x{plan.height}，"
            f"基准 {plan.base_width}px，延伸 {plan.extensions}，"
            f"重叠 {plan.overlap}px，调用 {plan.calls} 次，"
            f"画布比例 {[round(r, 2) for r in plan.canvas_ratios]}"
        )

    # 用户直接指定目标尺寸时，宽度必须精确等于请求值
    plan = plan_canvas(6.0, height=1024, width=4992)
    assert plan.width == 4992, plan
    assert plan.base_width + sum(plan.extensions) == 4992, plan
    assert all(r <= 3.0001 for r in plan.canvas_ratios), plan
    print(
        f"    指定宽度 4992x1024 -> 调用 {plan.calls} 次，"
        f"延伸 {plan.extensions}，画布比例 {[round(r, 2) for r in plan.canvas_ratios]}"
    )


def check_pipeline() -> None:
    print("\n[2] 端到端（Mock 后端）")
    provider = MockProvider()
    for ratio in ("6:1", "8:1"):
        result = generate_panorama(
            prompt="黄昏海岸线，远处灯塔，平静海面",
            ratio=ratio,
            height=768,
            provider=provider,
            output_dir=OUT_DIR,
            stem=f"selfcheck_{ratio.replace(':', 'x')}",
        )
        assert result.width == round(result.actual_ratio * result.height)
        assert result.width / result.height >= 3.0
        assert result.metrics["max_single_call_ratio"] <= 3.0001
        assert result.metrics["seam_score_max"] < 2.0, result.metrics
        print(
            f"    {ratio}: {result.width}x{result.height}，比例 {result.actual_ratio:.2f}，"
            f"调用 {result.calls} 次，最大接缝 {result.metrics['seam_score_max']}，"
            f"最大色差 {result.metrics['color_shift_max']}，耗时 {result.elapsed}s"
        )


if __name__ == "__main__":
    check_geometry()
    check_pipeline()
    print("\n全部自检通过。输出目录：", OUT_DIR)
