"""ChromaDB 封装：向量数据库的增删查改操作"""
import os
import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import get_settings

# 集合名称（所有知识库文档存放在同一个 collection）
COLLECTION_NAME = "knowledge_base"

# 科目加权检索的距离乘子（越小越靠前）
SUBJECT_MATCH_WEIGHT = 0.6   # 命中所选科目
GENERAL_WEIGHT = 0.8         # 通用类(general)科目


def _get_client() -> chromadb.ClientAPI:
    """获取 ChromaDB 持久化客户端"""
    settings = get_settings()
    db_path = settings.CHROMA_DB_PATH
    os.makedirs(db_path, exist_ok=True)
    return chromadb.PersistentClient(path=db_path)


def _get_collection():
    """获取或创建知识库 collection"""
    client = _get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def add_document(doc_name: str, chunks: list[str], embeddings: list[list[float]],
                 subject_id: int = 0) -> int:
    """将文档的文本片段和向量存入 ChromaDB（subject_id=0 表示未分类）"""
    collection = _get_collection()
    ids = [f"{doc_name}::chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {"source": doc_name, "chunk_index": i, "subject_id": int(subject_id or 0)}
        for i in range(len(chunks))
    ]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )
    return len(chunks)


def search_documents(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """根据查询向量检索最相关的文档片段"""
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    documents = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else None
            documents.append({
                "content": doc,
                "source": meta.get("source", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "subject_id": meta.get("subject_id", 0),
                "distance": distance,
            })
    return documents


def search_weighted(query_embedding: list[float], subject_id: int | None,
                    general_subject_ids: list[int] | None = None,
                    top_k: int = 5) -> list[dict]:
    """科目加权检索（不过滤）：命中所选科目/通用类科目的片段获得更靠前的排序。

    取候选 top_k*3 条 → 按科目调整距离权重 → 升序取前 top_k。
    """
    general_ids = set(general_subject_ids or [])
    candidates = search_documents(query_embedding, top_k=top_k * 3)
    if not candidates:
        return []

    for c in candidates:
        base = c["distance"] if c["distance"] is not None else 1.0
        sid = c.get("subject_id", 0)
        if subject_id and sid == subject_id:
            weight = SUBJECT_MATCH_WEIGHT
        elif sid in general_ids:
            weight = GENERAL_WEIGHT
        else:
            weight = 1.0
        c["weighted_distance"] = base * weight

    candidates.sort(key=lambda x: x["weighted_distance"])
    return candidates[:top_k]


def delete_document(doc_name: str) -> bool:
    """从 ChromaDB 中删除指定文档的所有向量"""
    collection = _get_collection()
    # 查找该文档的所有 chunk
    existing = collection.get(where={"source": doc_name})
    if not existing or not existing["ids"]:
        return False

    collection.delete(ids=existing["ids"])
    return True


def list_documents() -> list[dict]:
    """列出 ChromaDB 中所有已入库的文档（去重，含所属科目）"""
    collection = _get_collection()
    all_data = collection.get()

    if not all_data or not all_data["metadatas"]:
        return []

    # 按 source 去重并统计 chunk 数量，同时记录所属科目
    doc_stats: dict[str, int] = {}
    doc_subject: dict[str, int] = {}
    for meta in all_data["metadatas"]:
        source = meta.get("source", "unknown")
        doc_stats[source] = doc_stats.get(source, 0) + 1
        if source not in doc_subject:
            doc_subject[source] = meta.get("subject_id", 0) or 0

    return [
        {"name": name, "chunk_count": count, "subject_id": doc_subject.get(name, 0)}
        for name, count in doc_stats.items()
    ]


def clear_subject(subject_id: int) -> int:
    """将所属指定科目的文档片段重置为未分类(subject_id=0)，返回受影响片段数"""
    if not subject_id:
        return 0
    collection = _get_collection()
    existing = collection.get(where={"subject_id": int(subject_id)})
    if not existing or not existing["ids"]:
        return 0
    new_metas = []
    for meta in existing["metadatas"]:
        m = dict(meta)
        m["subject_id"] = 0
        new_metas.append(m)
    collection.update(ids=existing["ids"], metadatas=new_metas)
    return len(existing["ids"])


def document_exists(doc_name: str) -> bool:
    """检查文档是否已存在于 ChromaDB 中"""
    collection = _get_collection()
    existing = collection.get(where={"source": doc_name})
    return bool(existing and existing["ids"])
