from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings

# Monorepo keeps a single .env at its root, but this app runs from
# apps/computer_vision_engine_dev/, so locate it relative to this file
# rather than cwd.
_parents = Path(__file__).resolve().parents
ROOT_ENV_FILE = _parents[3] / ".env" if len(_parents) > 3 else _parents[-1] / ".env"

# Paths below are relative to apps/computer_vision_engine_dev/ (this app's cwd).
APP_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    anthropic_api_key: str
    diagram_path: str = "data/diagram.pdf"
    truth_set_path: str = "data/truth_set.json"
    results_dir: str = "results"
    model: str = "claude-opus-4-5"

    class Config:
        env_file = ROOT_ENV_FILE
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def app_path(relative: str) -> Path:
    """Resolve a path relative to this app's root, regardless of cwd."""
    return APP_DIR / relative
