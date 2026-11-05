"""FastAPI Demo：上传提示词 + 目标比例，异步生成并轮询进度。"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import get_settings
from .geometry import parse_ratio
from .jobs import JobStore
from .pipeline import generate_panorama
from .providers import build_provider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT, "static")
INDEX_FILE = os.path.join(STATIC_DIR, "index.html")

settings = get_settings()
provider = build_provider(settings)
store = JobStore()
# 并发闸门：公网 Demo 下防止连点/多人同时提交把额度和内存打满
job_slots = threading.BoundedSemaphore(settings.max_concurrent_jobs)

app = FastAPI(title="Wide Panorama - 突破 3:1 宽高比", version="1.0")


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=800)
    ratio: str = "6:1"
    # 可选：直接指定目标宽度（与 height 组成目标尺寸），优先级高于 ratio
    width: int | None = Field(default=None, ge=64, le=16384)
    height: int = Field(default=settings.default_height, ge=256, le=2048)
    seed: int | None = None


def _run_job(job_id: str, req: GenerateRequest) -> None:
    store.start(job_id, "开始生成")
    try:
        slot = req.width or req.ratio
        stem = f"panorama_{str(slot).replace(':', 'x')}_{req.height}_{job_id}"
        result = generate_panorama(
            prompt=req.prompt,
            ratio=req.ratio,
            width=req.width,
            height=req.height,
            provider=provider,
            output_dir=settings.output_dir,
            max_single_ratio=settings.max_single_ratio,
            overlap_frac=settings.overlap_frac,
            seed=req.seed if req.seed is not None else 20261105,
            on_progress=lambda pct, msg: store.progress(job_id, pct, msg),
            stem=stem,
        )
        store.finish(job_id, {**asdict(result), "files": {
            "png": f"/files/{result.image_png}",
            "jpg": f"/files/{result.image_jpg}",
            "meta": f"/files/{result.meta_json}",
        }})
    except Exception as exc:  # 把失败原因回传给前端
        store.fail(job_id, f"{type(exc).__name__}: {exc}")
    finally:
        job_slots.release()


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "provider": provider.name,
        "demo_mode": provider.name == "mock",
        "api_configured": settings.api_configured,
        "max_single_ratio": settings.max_single_ratio,
        "default_height": settings.default_height,
    }


@app.post("/api/generate")
def create_job(req: GenerateRequest) -> dict:
    if req.width is not None and req.width % 8 != 0:
        raise HTTPException(status_code=400, detail="目标宽度需为 8 的倍数，便于各段对齐")
    try:
        ratio = req.width / req.height if req.width else parse_ratio(req.ratio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if ratio <= settings.max_single_ratio:
        raise HTTPException(
            status_code=400,
            detail=f"目标宽高比必须大于 {settings.max_single_ratio:g}:1，否则不构成超宽图",
        )
    width = req.width or round(ratio * req.height)
    if width > 16384:
        raise HTTPException(status_code=400, detail="目标宽度过大，请降低高度或比例（上限 16384px）")

    if not job_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=f"当前生成任务已满（最多 {settings.max_concurrent_jobs} 个并发），请稍后重试",
        )
    try:
        job = store.create({
            "prompt": req.prompt,
            "ratio": req.ratio,
            "width": req.width,
            "height": req.height,
        })
        threading.Thread(target=_run_job, args=(job.id, req), daemon=True).start()
    except Exception:
        job_slots.release()
        raise
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()


@app.get("/files/{name}")
def get_file(name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = os.path.join(settings.output_dir, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=name)


@app.get("/")
def index():
    return FileResponse(INDEX_FILE)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
