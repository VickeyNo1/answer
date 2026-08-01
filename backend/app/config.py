from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 通义千问 API Key
    DASHSCOPE_API_KEY: str = ""

    # JWT 配置
    JWT_SECRET_KEY: str = "dev-secret-key-2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # MySQL（机器A：开发用公网 8.134.97.196，生产用私网 172.22.207.228）
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "answer"

    # 知识库检索服务（机器A :8100，生产走私网）
    KB_BASE_URL: str = "http://172.22.207.228:8100"
    KB_TOKEN: str = ""
    KB_TIMEOUT: int = 10

    # CORS 允许的前端域名
    CORS_ORIGINS: str = "http://localhost:3000"

    # 对话模型
    CHAT_MODEL: str = "qwen3.7-flash"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
