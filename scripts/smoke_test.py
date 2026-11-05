"""接口冒烟测试：校验参数拦截、错误码、可选的真实生成链路。

用法：
    python scripts/smoke_test.py                       # 只测不花钱的校验类接口
    python scripts/smoke_test.py --generate            # 额外提交一次 6:1（会真实调用模型）
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def expect_status(method: str, path: str, status: int, **kwargs) -> bool:
    resp = requests.request(method, BASE + path, timeout=10, **kwargs)
    body = resp.text[:160].replace("\n", " ")
    return check(f"{method} {path} -> {status}", resp.status_code == status, f"实际 {resp.status_code} {body}")


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--generate", action="store_true", help="提交一次真实生成")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    ok = True
    health = requests.get(BASE + "/api/health", timeout=10).json()
    ok &= check("health", health.get("ok") is True, str(health))

    cases = [
        ("POST", "/api/generate", 422, {"json": {"prompt": ""}}),
        ("POST", "/api/generate", 400, {"json": {"prompt": "x", "ratio": "2:1", "height": 1024}}),
        ("POST", "/api/generate", 400, {"json": {"prompt": "x", "ratio": "abc", "height": 1024}}),
        ("POST", "/api/generate", 400, {"json": {"prompt": "x", "width": 6143, "height": 1024}}),
        ("POST", "/api/generate", 400, {"json": {"prompt": "x", "width": 3072, "height": 1024}}),
        ("POST", "/api/generate", 400, {"json": {"prompt": "x", "ratio": "16:1", "height": 1536}}),
        ("GET", "/api/jobs/not-exist", 404, {}),
        ("GET", "/files/..%2F.env", 404, {}),
    ]
    for method, path, status, kwargs in cases:
        ok &= expect_status(method, path, status, **kwargs)

    if args.generate:
        resp = requests.post(
            BASE + "/api/generate",
            json={"prompt": "黄昏海岸线，远处灯塔", "ratio": "6:1", "height": 512},
            timeout=20,
        )
        ok &= check("提交生成任务", resp.status_code == 200, resp.text[:120])
        job = resp.json()["job_id"]
        for _ in range(120):
            data = requests.get(f"{BASE}/api/jobs/{job}", timeout=10).json()
            if data["status"] in {"done", "error"}:
                break
            time.sleep(2)
        ok &= check("任务完成", data["status"] == "done", str(data.get("error")))
        if data["status"] == "done":
            r = data["result"]
            ok &= check("尺寸严格达标", r["width"] == r["height"] * 6, f"{r['width']}x{r['height']}")
            ok &= check("单次画布 <=3:1", r["metrics"]["max_single_call_ratio"] <= 3.0001, str(r["metrics"]))
            ok &= check("接缝指标达标", r["metrics"]["seam_score_max"] <= 2.5, str(r["metrics"]["seam_score_max"]))

    print("\n结果：", "全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
