from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "围标检测系统"
    debug: bool = False

    # Database (asyncpg driver, 与 db/session.py 对齐)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/documentcheck"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # File upload
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50

    # JWT
    secret_key: str = "change-this-in-production"
    access_token_expire_minutes: int = 60 * 24

    # LLM 适配层 (C1 infra-base)
    llm_provider: str = "dashscope"  # dashscope | openai
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"  # dashscope 默认;openai 时改 gpt-4o-mini 等
    llm_base_url: str | None = None  # 留空走 provider 默认
    llm_timeout_s: float = 30.0

    # 数据生命周期 (C1 强制 dry-run;真删随 C4 file-upload 一起开放)
    lifecycle_dry_run: bool = True
    lifecycle_interval_s: int = 3600
    lifecycle_age_days: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
