"""Embedding 封装：调用通义千问 text-embedding-v3 将文本转向量化"""
import dashscope
from dashscope import TextEmbedding
from app.config import get_settings

# 模型配置
EMBEDDING_MODEL = "text-embedding-v3"
BATCH_SIZE = 25  # 通义千问单次最多 25 条


def _init_api_key():
    settings = get_settings()
    dashscope.api_key = settings.DASHSCOPE_API_KEY


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量将文本列表转换为向量（自动分批调用）"""
    if not texts:
        return []

    _init_api_key()
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = TextEmbedding.call(
            model=EMBEDDING_MODEL,
            input=batch,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Embedding API 调用失败: {response.code} - {response.message}"
            )

        # 提取向量
        items = response.output["embeddings"]
        # 按 text_index 排序确保顺序正确
        items.sort(key=lambda x: x["text_index"])
        all_embeddings.extend([item["embedding"] for item in items])

    return all_embeddings


def embed_query(text: str) -> list[float]:
    """将单条查询文本转换为向量"""
    results = embed_texts([text])
    return results[0]
