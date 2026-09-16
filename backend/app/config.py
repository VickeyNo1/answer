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

    # 视觉（OCR）模型：图片题目识别用，可通过 .env 覆盖
    VISION_MODEL: str = "qwen-vl-max"

    # 分用途模型覆盖（空串 = 跟随后台激活模型，见 llm/store.py::get_model_for）
    # 判卷/画像/题目同一性校验的敏感度与调用量与对话完全不同，共用一个模型不合理
    JUDGE_MODEL: str = ""
    PROFILE_MODEL: str = ""
    VERIFY_MODEL: str = ""
    # 批量评测：400 题一次性跑，想固定用最便宜档而不受生产对话切换模型影响
    EVAL_MODEL: str = ""

    # 智谱开放平台（GLM 系列直连自有端点，走用户自购资源包；其余模型一律走百炼）。
    # create_client(model_name) 见模型名以 glm 开头时路由到此端点
    ZHIPU_API_KEY: str = ""
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
