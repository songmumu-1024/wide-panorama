"""全局配置：全部通过环境变量覆盖，便于本地/容器部署。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """读取项目根目录的 .env；已存在的环境变量优先，便于容器/CI 覆盖。"""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key and key not in os.environ:
            os.environ[key] = value.strip('"').strip("'")


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # 生成后端：mock（离线演示）| openai（OpenAI 兼容的图片接口）
    provider: str
    base_url: str
    api_key: str
    model: str
    # 单次调用允许的最大宽高比，题目给出的限制是 3:1
    max_single_ratio: float
    # 相邻两段的水平重叠比例（相对单段宽度）
    overlap_frac: float
    default_height: int
    request_timeout: int
    # exact：直接传 WxH；preset：只接受白名单尺寸（部分网关有限制）
    size_mode: str
    preset_sizes: tuple[str, ...]
    enable_edits: bool
    output_dir: str

    @property
    def api_configured(self) -> bool:
        return self.provider == "mock" or bool(self.api_key)


def get_settings() -> Settings:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return Settings(
        provider=_env("IMAGE_PROVIDER", "mock") or "mock",
        base_url=_env("IMAGE_API_BASE_URL", "https://api.openai.com/v1"),
        api_key=_env("IMAGE_API_KEY", ""),
        model=_env("IMAGE_MODEL", "gpt-image-1"),
        max_single_ratio=float(_env("MAX_SINGLE_RATIO", "3")),
        overlap_frac=float(_env("OVERLAP_FRAC", "0.15")),
        default_height=int(_env("DEFAULT_HEIGHT", "1024")),
        request_timeout=int(_env("REQUEST_TIMEOUT", "300")),
        size_mode=_env("IMAGE_SIZE_MODE", "auto") or "auto",
        preset_sizes=tuple(
            s for s in _env("IMAGE_PRESET_SIZES", "1536x1024,1024x1024,1024x1536").split(",") if s
        ),
        enable_edits=_env("IMAGE_ENABLE_EDITS", "1") not in {"0", "false", "False"},
        output_dir=_env("OUTPUT_DIR", os.path.join(root, "outputs")),
    )
