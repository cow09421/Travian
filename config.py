import os
import sys
from dotenv import load_dotenv
from dataclasses import dataclass, field
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path, override=True)


def _ensure_dirs(*paths):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def validate_config():
    missing = []
    if not os.getenv("TRAVIAN_URL"):
        missing.append("TRAVIAN_URL")
    if not os.getenv("NVIDIA_API_KEY"):
        missing.append("NVIDIA_API_KEY")
    if missing:
        print(f"❌ .env 缺少必要設定：{', '.join(missing)}")
        print("請複製 .env.example 為 .env 並填入正確值後重新啟動")
        sys.exit(1)


@dataclass
class Config:
    travian_url: str = field(default_factory=lambda: os.getenv("TRAVIAN_URL", ""))
    travian_username: str = field(default_factory=lambda: os.getenv("TRAVIAN_USERNAME", ""))
    travian_password: str = field(default_factory=lambda: os.getenv("TRAVIAN_PASSWORD", ""))

    nvidia_api_key: str = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-ai/deepseek-v4-flash"))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "4096")))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.3")))

    headless: bool = field(default_factory=lambda: os.getenv("HEADLESS", "false").lower() == "true")
    browser_slow_mo: int = field(default_factory=lambda: int(os.getenv("BROWSER_SLOW_MO", "50")))

    min_operation_delay: float = field(default_factory=lambda: float(os.getenv("MIN_OPERATION_DELAY", "0.8")))
    max_operation_delay: float = field(default_factory=lambda: float(os.getenv("MAX_OPERATION_DELAY", "3.5")))
    max_sleep_hours: int = field(default_factory=lambda: int(os.getenv("MAX_SLEEP_HOURS", "2")))

    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    logs_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "logs")
    screenshots_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "logs" / "screenshots")
    db_path: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "travian.db")

    def ensure_dirs(self):
        _ensure_dirs(self.logs_dir, self.screenshots_dir)


config = Config()