from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # TigerGraph
    tg_host: str
    tg_username: str = "tigergraph"
    tg_password: str
    tg_secret: str = ""
    tg_graph: str = "SpikeGraph"

    # Database (Turso)
    turso_database_url: str
    turso_auth_token: str = ""

    # LLMs
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_offline: bool = False

    # App Settings
    demo_mode: bool = False

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
