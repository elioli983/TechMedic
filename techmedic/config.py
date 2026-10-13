from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    jev_api_key: str
    openai_model: str
    jev_model: str
    jev_api_url: str
    database_path: Path
    web_research_enabled: bool
    web_research_max_sources: int

    @property
    def missing_keys(self) -> list[str]:
        missing: list[str] = []
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.jev_api_key:
            missing.append("JEV_API_KEY")
        return missing



def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))

def get_settings() -> Settings:
    raw_db = os.getenv("TECHMEDIC_DB_PATH", "").strip()
    db_path = Path(raw_db).expanduser() if raw_db else PROJECT_ROOT / "data" / "techmedic_v1_5_6.sqlcipher"
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        jev_api_key=os.getenv("JEV_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.1").strip() or "gpt-5.1",
        jev_model=os.getenv("JEV_MODEL", "jev-latest").strip() or "jev-latest",
        jev_api_url=os.getenv("JEV_API_URL", "").strip(),
        database_path=db_path,
        web_research_enabled=_env_bool("TECHMEDIC_WEB_RESEARCH_ENABLED", True),
        web_research_max_sources=_env_int("TECHMEDIC_WEB_RESEARCH_MAX_SOURCES", 10, 1, 20),
    )
