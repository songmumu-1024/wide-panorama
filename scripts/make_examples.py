"""生成 6:1 / 8:1 等比例的案例图，供 README 与交付材料使用。

用法：
    python scripts/make_examples.py                         # 默认 Mock，离线可跑
    python scripts/make_examples.py --provider openai       # 需要配置 IMAGE_API_KEY
    python scripts/make_examples.py --ratios 6:1,8:1 --height 1024
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.pipeline import generate_panorama
from app.providers import build_provider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ratios", default="6:1,8:1")
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--prompt", default="黄昏时分的海岸线，远处灯塔，平静海面，电影感光线")
    parser.add_argument("--provider", default=None, help="mock | openai（默认读 IMAGE_PROVIDER）")
    parser.add_argument("--out", default=os.path.join(ROOT, "outputs"))
    parser.add_argument("--seed", type=int, default=20261105)
    args = parser.parse_args()

    settings = get_settings()
    if args.provider:
        settings = settings.__class__(**{**settings.__dict__, "provider": args.provider})
    provider = build_provider(settings)

    for ratio in [r.strip() for r in args.ratios.split(",") if r.strip()]:
        print(f"\n==> {ratio}  (provider={provider.name})")
        result = generate_panorama(
            prompt=args.prompt,
            ratio=ratio,
            height=args.height,
            provider=provider,
            output_dir=args.out,
            max_single_ratio=settings.max_single_ratio,
            overlap_frac=settings.overlap_frac,
            seed=args.seed,
            on_progress=lambda pct, msg: print(f"    [{pct:>3}%] {msg}"),
            stem=f"case_{ratio.replace(':', 'x')}x1",
        )
        print(
            f"    -> {result.image_png}\n"
            f"    {result.width}x{result.height}，比例 {result.actual_ratio:.2f}:1，"
            f"接缝 {result.metrics['seam_score_max']}，耗时 {result.elapsed}s"
        )


if __name__ == "__main__":
    main()
