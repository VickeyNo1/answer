from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 通义千问 API Key
    DASHSCOPE_API_KEY: str = ""

    # JWT 配置
    JWT_SECRET_KEY: str = "dev-secret-key-2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # 数据库路径
    DATABASE_URL: str = "./data/app.db"

    # ChromaDB 路径
    CHROMA_DB_PATH: str = "./data/chroma_db"

    # 上传文件目录
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 10

    # CORS 允许的前端域名
    CORS_ORIGINS: str = "http://localhost:3000"

    # 对话模型
    CHAT_MODEL: str = "qwen-plus"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
