from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# Monorepo keeps a single .env at its root, but this app runs from
# apps/computer_vision/, so locate it relative to this file rather than cwd.
# In Docker the app is copied to /app, which has fewer parent directories and
# no monorepo-root .env -- settings then come from the environment variables
# injected by docker-compose instead.
_parents = Path(__file__).resolve().parents
ROOT_ENV_FILE = _parents[3] / ".env" if len(_parents) > 3 else _parents[-1] / ".env"


class Settings(BaseSettings):
    anthropic_api_key: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    sop_path: str = "data/sop/sop.docx"
    pid_path: str = "data/pid/colored.pdf"
    model: str = "claude-opus-4-8"

    class Config:
        env_file = ROOT_ENV_FILE
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


SOP_FILENAMES = ["sop.docx", "sop1.docx", "sop2.docx", "sop3.docx"]


def sop_path_for(sop_index: int) -> str:
    if not 0 <= sop_index < len(SOP_FILENAMES):
        raise ValueError(f"sop_index must be between 0 and {len(SOP_FILENAMES) - 1}")
    return str(Path(get_settings().sop_path).parent / SOP_FILENAMES[sop_index])
