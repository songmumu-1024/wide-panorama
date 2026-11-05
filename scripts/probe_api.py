"""探测图片网关：确认地址前缀、可用模型，以及尺寸/edits 支持情况。

用法：
    python scripts/probe_api.py                     # 只列模型
    python scripts/probe_api.py --matrix            # 测试尺寸与 edits
    python scripts/probe_api.py --matrix --model gpt-image-1
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS = ("image", "flux", "dall", "seedream", "sd", "draw", "paint", "imagen", "kolors")


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def candidates(base: str) -> list[str]:
    base = base.rstrip("/")
    out = [base]
    if base.endswith("/v1"):
        out.append(base[:-3])
    else:
        out.append(base + "/v1")
    return list(dict.fromkeys(out))


def probe_models(base: str, key: str) -> list[str] | None:
    for url in candidates(base):
        try:
            resp = requests.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        except requests.RequestException as exc:
            print(f"[网络失败] {url}/models -> {exc}")
            continue
        print(f"[{resp.status_code}] {url}/models")
        if resp.status_code >= 400:
            print("      " + resp.text[:160].replace("\n", " "))
            continue
        try:
            payload = resp.json()
        except ValueError:
            print("      返回非 JSON，可能不是 OpenAI 兼容网关")
            continue
        items = payload.get("data") or payload.get("models") or []
        ids = [str(it.get("id") if isinstance(it, dict) else it) for it in items]
        print(f"      共 {len(ids)} 个模型")
        return ids
    return None


def summarize(payload: dict) -> str:
    items = payload.get("data") or payload.get("images") or []
    if not items:
        return "无 data 字段: " + json.dumps(payload, ensure_ascii=False)[:160]
    item = items[0]
    if isinstance(item, str):
        return f"字符串项，长度 {len(item)}"
    keys = sorted(item.keys())
    b64 = item.get("b64_json") or item.get("b64") or ""
    url = item.get("url") or ""
    size = item.get("size") or item.get("revised_prompt") or ""
    return f"keys={keys} b64_len={len(b64) if isinstance(b64, str) else 0} url={str(url)[:60]} {size}"


def _arg(name: str, default: str = "") -> str:
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def gen(base: str, key: str, model: str, size: str, complexity: str = "") -> None:
    body = {"model": model, "prompt": "a calm ocean at dusk, wide open sky", "n": 1, "size": size}
    if complexity:
        body["complexity"] = complexity
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=180,
        )
    except requests.RequestException as exc:
        print(f"[{size}] 网络失败: {exc}")
        return
    print(f"[{resp.status_code}] generations {size}" + (f" complexity={complexity}" if complexity else ""))
    if resp.status_code >= 400:
        print("      " + resp.text[:200].replace("\n", " "))
        return
    try:
        print("      " + summarize(resp.json()))
    except ValueError:
        print("      非 JSON 返回")


def edits(base: str, key: str, model: str, complexity: str = "") -> None:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1536, 1024), (30, 60, 120))
    dr = ImageDraw.Draw(img)
    dr.rectangle((0, 0, 700, 1024), fill=(240, 160, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    mask = Image.new("RGBA", (1536, 1024), (255, 255, 255, 255))
    dr2 = ImageDraw.Draw(mask)
    dr2.rectangle((700, 0, 1536, 1024), fill=(0, 0, 0, 0))
    mbuf = io.BytesIO()
    mask.save(mbuf, format="PNG")
    mbuf.seek(0)

    files = {
        "image": ("canvas.png", buf.getvalue(), "image/png"),
        "mask": ("mask.png", mbuf.getvalue(), "image/png"),
    }
    data = {"model": model, "prompt": "continue the scene to the right", "n": "1", "size": "1536x1024"}
    if complexity:
        data["complexity"] = complexity
    try:
        resp = requests.post(
            f"{base.rstrip('/')}/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files=files,
            timeout=180,
        )
    except requests.RequestException as exc:
        print(f"[edits] 网络失败: {exc}")
        return
    print(f"[{resp.status_code}] edits")
    if resp.status_code >= 400:
        print("      " + resp.text[:200].replace("\n", " "))
        return
    try:
        print("      " + summarize(resp.json()))
    except ValueError:
        print("      非 JSON 返回")


def main() -> int:
    load_env(ROOT / ".env")
    base = os.getenv("IMAGE_API_BASE_URL", "")
    key = os.getenv("IMAGE_API_KEY", "")
    if not base or not key:
        print("缺少 IMAGE_API_BASE_URL 或 IMAGE_API_KEY（检查 .env）")
        return 2

    ids = probe_models(base, key)
    if ids is None:
        print("模型列表不可用")
        return 1

    hits = [i for i in ids if any(k in i.lower() for k in KEYWORDS)]
    print("\n可能的图片模型：")
    for i in hits or ids[:30]:
        print("  -", i)

    if "--matrix" in sys.argv:
        model = _arg("--model") or os.getenv("IMAGE_MODEL") or (hits[0] if hits else "")
        if not model:
            print("\n没有可用模型，先设置 IMAGE_MODEL")
            return 1
        complexity = _arg("--complexity")
        sizes = (
            (_arg("--size"),)
            if _arg("--size")
            else ("1024x1024", "1536x1024", "2000x1024", "3072x1024")
        )
        print(f"\n== 尺寸与 edits 测试，model={model} ==")
        for size in sizes:
            gen(base, key, model, size, complexity)
        if "--skip-edits" not in sys.argv:
            edits(base, key, model, complexity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
