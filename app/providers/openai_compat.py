"""OpenAI 兼容的图片接口适配层。

支持两种调用：
1. POST {base}/images/generations —— 文生图（作为兜底）
2. POST {base}/images/edits       —— 带 mask 的续画/扩图（首选，接缝质量最好）

不同网关对 size 的约束不同，因此提供 auto/exact/preset 三种模式。
"""
from __future__ import annotations

import base64
import io
import math

import numpy as np
import requests
from PIL import Image

from ..imaging import resize_cover, to_array, to_image
from .base import GenContext, ImageProvider, ProviderError


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class OpenAICompatProvider(ImageProvider):
    name = "openai-compatible"
    supports_outpaint = True
    supports_seed = False

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 300,
        size_mode: str = "auto",
        preset_sizes: tuple[str, ...] = (),
        enable_edits: bool = True,
    ):
        if not base_url:
            raise ProviderError("缺少 IMAGE_API_BASE_URL")
        if not api_key:
            raise ProviderError("缺少 IMAGE_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.size_mode = size_mode
        self.presets = list(preset_sizes) or ["1536x1024", "1024x1024", "1024x1536"]
        self.enable_edits = enable_edits
        self._meta: dict = {}

    # ---------- 对外接口 ----------
    def text_to_image(self, ctx: GenContext, width: int, height: int) -> Image.Image:
        return self._generate(ctx.prompt, width, height)

    def outpaint(self, ctx: GenContext, context, width: int, height: int, overlap: int) -> Image.Image:
        if not self.enable_edits:
            return self._fallback(ctx, context, width, height, overlap, "edits disabled")
        try:
            return self._edit(ctx.prompt, context, width, height, overlap)
        except Exception as exc:  # 网关不支持 edits 时退化为文生图，保证整体可用
            self._meta = {"mode": "fallback-text", "error": str(exc)[:180]}
            return self._fallback(ctx, context, width, height, overlap, str(exc))

    def last_meta(self) -> dict:
        return dict(self._meta)

    # ---------- 内部实现 ----------
    def _fallback(self, ctx, context, width, height, overlap, reason: str) -> Image.Image:
        new_w = width - overlap
        gen = self._generate(ctx.prompt, new_w, height)
        gen = resize_cover(gen, new_w, height)
        combined = np.concatenate([to_array(context), to_array(gen)], axis=1)
        self._meta = {"mode": "fallback-text", "reason": reason[:180]}
        return to_image(combined)

    def _edit(self, prompt: str, context, width: int, height: int, overlap: int) -> Image.Image:
        new_w = width - overlap
        ctx_arr = to_array(context)

        # 初始填充：把左边缘的列复制到右侧，给 inpainting 一个中性起点。
        # 不要用 reflect：镜像会诱导模型把云层/山脊画成对称结构，破坏全景的自然感。
        pad = np.pad(ctx_arr, ((0, 0), (0, new_w), (0, 0)), mode="edge")
        init = np.concatenate([ctx_arr, pad[:, :new_w]], axis=1)

        # mask：透明区域 = 允许重绘（OpenAI 约定）；重叠区保持不透明
        mask = np.zeros((height, width, 4), dtype=np.uint8)
        mask[:, :, :3] = 255
        mask[:, :overlap, 3] = 255

        url = f"{self.base_url}/images/edits"
        size = self._pick_size(width, height)
        data = {"model": self.model, "prompt": prompt, "n": "1", "size": size}
        files = {
            "image": ("canvas.png", _png_bytes(to_image(init)), "image/png"),
            "mask": ("mask.png", _png_bytes(Image.fromarray(mask, mode="RGBA")), "image/png"),
        }
        resp = requests.post(
            url,
            headers=self._headers(),
            data=data,
            files=files,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise ProviderError(f"edits {resp.status_code}: {resp.text[:300]}")
        img = self._decode(resp)
        raw_w, raw_h = img.size
        img = resize_cover(img, width, height)
        self._meta = {"mode": "edits", "size": size, "canvas": f"{width}x{height}", "out": f"{raw_w}x{raw_h}"}
        return img

    def _generate(self, prompt: str, width: int, height: int) -> Image.Image:
        size = self._pick_size(width, height)
        body = {"model": self.model, "prompt": prompt, "n": 1, "size": size}
        resp = requests.post(
            f"{self.base_url}/images/generations",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code >= 400 and self.size_mode == "auto":
            preset = self._nearest_preset(width, height)
            body["size"] = preset
            resp = requests.post(
                f"{self.base_url}/images/generations",
                headers=self._headers(),
                json=body,
                timeout=self.timeout,
            )
            if resp.status_code < 400:
                img = self._decode(resp)
                raw_w, raw_h = img.size
                self._meta = {"mode": "generations", "size": preset, "resized": True, "out": f"{raw_w}x{raw_h}"}
                return resize_cover(img, width, height)
        if resp.status_code >= 400:
            raise ProviderError(f"generations {resp.status_code}: {resp.text[:300]}")
        img = self._decode(resp)
        self._meta = {"mode": "generations", "size": size, "out": f"{img.width}x{img.height}"}
        return img

    def _pick_size(self, width: int, height: int) -> str:
        if self.size_mode == "preset":
            return self._nearest_preset(width, height)
        return f"{width}x{height}"

    def _nearest_preset(self, width: int, height: int) -> str:
        target = width / height
        best, best_score = self.presets[0], float("inf")
        for preset in self.presets:
            try:
                pw, ph = (int(v) for v in preset.lower().split("x"))
            except ValueError:
                continue
            score = abs(math.log((pw / ph) / target))
            if score < best_score:
                best, best_score = preset, score
        return best

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _decode(resp: requests.Response) -> Image.Image:
        try:
            payload = resp.json()
        except ValueError:
            raise ProviderError(f"接口返回非 JSON: {resp.text[:200]}")
        items = payload.get("data") or payload.get("images") or []
        if not items:
            raise ProviderError(f"接口未返回图片: {str(payload)[:200]}")
        item = items[0]
        if isinstance(item, str):
            b64 = item
        else:
            b64 = item.get("b64_json") or item.get("b64") or ""
        if b64:
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        url = item.get("url") if isinstance(item, dict) else None
        if url:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        raise ProviderError("接口返回中没有 b64_json 或 url")
