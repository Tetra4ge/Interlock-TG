from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # TigerGraph
    tg_host: str = "http://localhost"
    tg_username: str = "tigergraph"
    tg_password: str = "tigergraph"
    tg_secret: str = ""
    tg_graph: str = "InterlockV2"
    tg_restpp_port: int = 9000
    tg_gs_port: int = 14240

    # Database (Turso)
    turso_database_url: str = "file:db/interlock.db"
    turso_auth_token: str = ""

    # LLMs
    groq_api_key: str = ""
    llm_offline: bool = False
    llm_spend_cap_usd: float = 25.0

    # App Settings
    demo_mode: bool = False
    # Seconds to reuse a read-only API response. The run store can be a remote database
    # where every query is a network round trip, and runs change rarely. 0 disables it.
    read_cache_seconds: float = 15.0
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,https://interlock-tg.vercel.app"

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
