from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # TigerGraph
    tg_host: str = "http://localhost"
    tg_username: str = "tigergraph"
    tg_password: str = "tigergraph"
    tg_secret: str = ""
    tg_graph: str = "SpikeGraph"

    # Database (Turso)
    turso_database_url: str = "file:db/interlock.db"
    turso_auth_token: str = ""

    # LLMs
    groq_api_key: str = ""
    llm_offline: bool = False
    llm_spend_cap_usd: float = 25.0

    # App Settings
    demo_mode: bool = False

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
