from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "围标检测系统"
    debug: bool = False

    # Database (asyncpg driver, 与 db/session.py 对齐)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/documentcheck"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # File upload (C4 file-upload):压缩包原文件 + 解压产物各自的根目录;
    # 上限与 services/upload/validator.py MAX_ARCHIVE_BYTES 同步 = 500MB
    upload_dir: str = "./uploads"
    extracted_dir: str = "./extracted"
    max_file_size_mb: int = 500

    # JWT / Auth (C2)
    secret_key: str = "change-this-in-production"  # 生产部署必须通过 env 覆盖
    access_token_expire_minutes: int = 60 * 24  # 24h
    jwt_algorithm: str = "HS256"

    # 账户锁定(C2 auth)
    auth_lockout_threshold: int = 5
    auth_lockout_ttl_minutes: int = 15

    # 默认管理员 seed(C2 auth);生产必须通过 env 覆盖,且 must_change_password=true 首次登录强制改
    auth_seed_admin_username: str = "admin"
    auth_seed_admin_password: str = "admin123"

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
