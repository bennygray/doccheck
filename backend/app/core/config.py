from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "围标检测系统"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/documentcheck"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # File upload
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50

    # JWT
    secret_key: str = "change-this-in-production"
    access_token_expire_minutes: int = 60 * 24

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
