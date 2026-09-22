from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://oficinaflow:oficinaflow@localhost:5436/oficinaflow"
    redis_url: str = "redis://localhost:6383/0"
    jwt_secret: str = "change-me-oficinaflow-dev-secret-32chars"
    jwt_expire_minutes: int = 720
    cookie_name: str = "oficinaflow_token"
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:5175"
    api_public_url: str = "http://localhost:8002"
    mp_access_token: str = ""
    webhook_demo_secret: str = "demo-webhook-secret"
    rq_async: bool = False
    webhook_max_retries: int = 2
    free_max_staff: int = 1
    free_max_work_orders_month: int = 20
    pro_max_staff: int = 20
    pro_price_cents: int = 9900


@lru_cache
def get_settings() -> Settings:
    return Settings()
