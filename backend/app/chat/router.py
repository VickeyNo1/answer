"""对话路由：SSE 流式对话 + 对话 CRUD"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.auth.deps import get_current_user
from app.database import get_db, get_db_ctx
from app.models import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from app.chat.memory import get_conversation_history
from app.chat.qwen_service import build_messages, stream_chat
from app.knowledge.embedding import embed_query
from app.knowledge import chroma_service
from app.llm import store as llm_store

router = APIRouter(prefix="/api", tags=["对话"])


# ========== SSE 流式对话 ==========

@router.post("/chat")
async def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """SSE 流式对话：RAG 流程 = embedding → 检索 → 组装 prompt → 流式返回"""
    user_id = current_user["id"]

    # 1. 确定对话 ID（null 则自动新建）
    conversation_id = req.conversation_id
    if conversation_id is None:
        with get_db_ctx() as db:
            cursor = db.execute(
                "INSERT INTO conversations (user_id, title, subject_id) VALUES (?, ?, ?)",
                (user_id, req.message[:30] if req.message else "新对话", req.subject_id),
            )
            db.commit()
            conversation_id = cursor.lastrowid
    elif req.subject_id is not None:
        # 已有对话：同步更新所选科目
        with get_db_ctx() as db:
            db.execute(
                "UPDATE conversations SET subject_id = ? WHERE id = ? AND user_id = ?",
                (req.subject_id, conversation_id, user_id),
            )
            db.commit()

    # 2. 保存用户消息
    with get_db_ctx() as db:
        db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, "user", req.message),
        )
        db.commit()

    # 3. RAG：科目加权检索知识库
    context = None
    try:
        query_embedding = embed_query(req.message)
        general_ids = _get_general_subject_ids()
        results = chroma_service.search_weighted(
            query_embedding, req.subject_id, general_ids, top_k=5,
        )
        if results:
            context = [r["content"] for r in results]
    except Exception:
        # 知识库为空或检索失败时继续（不影响对话）
        pass

    # 4. 构建消息列表
    history = get_conversation_history(conversation_id, limit=10)
    # 排除刚存入的当前用户消息（因为还没得到回复）
    if history and history[-1]["role"] == "user" and history[-1]["content"] == req.message:
        history = history[:-1]

    messages = build_messages(req.message, history, context)
    model_name = llm_store.get_active_model()

    # 5. SSE 流式生成
    async def event_generator():
        # 发送 start 事件
        yield _sse({"type": "start", "conversation_id": conversation_id})

        full_content = ""
        error_occurred = False
        prompt_tokens = 0
        completion_tokens = 0

        for chunk in stream_chat(messages, model_name):
            if "error" in chunk:
                yield _sse({"type": "error", "detail": chunk["error"]})
                error_occurred = True
                break
            if "usage" in chunk:
                prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                completion_tokens = chunk["usage"].get("completion_tokens", 0)
                continue
            content = chunk.get("content", "")
            if content:
                full_content += content
                yield _sse({"type": "delta", "content": content})

        # 记录用量（即使内容为空也记录 token 消耗）
        if not error_occurred and (prompt_tokens or completion_tokens):
            try:
                llm_store.record_usage(
                    model_name, user_id, conversation_id,
                    prompt_tokens, completion_tokens,
                )
            except Exception:
                pass

        # 保存 AI 回复到数据库
        if not error_occurred and full_content:
            with get_db_ctx() as db:
                cursor = db.execute(
                    "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                    (conversation_id, "assistant", full_content),
                )
                db.commit()
                message_id = cursor.lastrowid
            yield _sse({"type": "done", "message_id": message_id})
        elif not error_occurred:
            yield _sse({"type": "done", "message_id": 0})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 关闭缓冲
        },
    )


def _sse(data: dict) -> str:
    """格式化 SSE 数据行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_general_subject_ids() -> list[int]:
    """获取通用类(general)科目的 id 列表，用于检索加权"""
    with get_db_ctx() as db:
        cursor = db.execute("SELECT id FROM subjects WHERE category = 'general'")
        return [r["id"] for r in cursor.fetchall()]


# ========== 对话 CRUD ==========

@router.post("/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationOut)
async def create_conversation(
    req: ConversationCreate,
    current_user: dict = Depends(get_current_user),
):
    """新建对话"""
    with get_db_ctx() as db:
        cursor = db.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (current_user["id"], req.title),
        )
        db.commit()
        conv_id = cursor.lastrowid

        cursor = db.execute(
            "SELECT id, title, created_at, subject_id FROM conversations WHERE id = ?",
            (conv_id,),
        )
        row = cursor.fetchone()
        return ConversationOut(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            subject_id=row["subject_id"],
        )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户的对话列表（按时间降序）"""
    with get_db_ctx() as db:
        cursor = db.execute(
            """SELECT id, title, created_at, subject_id FROM conversations
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            (current_user["id"],),
        )
        rows = cursor.fetchall()
        return [
            ConversationOut(
                id=r["id"], title=r["title"],
                created_at=r["created_at"], subject_id=r["subject_id"],
            )
            for r in rows
        ]


@router.get("/conversations/{conversation_id}", response_model=list[MessageOut])
async def get_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    """获取对话的消息历史（按时间升序）"""
    with get_db_ctx() as db:
        # 验证对话属于当前用户
        cursor = db.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, current_user["id"]),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或不属于当前用户",
            )

        cursor = db.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = ?
               ORDER BY created_at ASC""",
            (conversation_id,),
        )
        rows = cursor.fetchall()
        return [
            MessageOut(
                id=r["id"], role=r["role"],
                content=r["content"], created_at=r["created_at"],
            )
            for r in rows
        ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除对话及其所有消息"""
    with get_db_ctx() as db:
        # 验证对话属于当前用户
        cursor = db.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, current_user["id"]),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或不属于当前用户",
            )

        # 删除消息和对话
        db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        db.commit()

    return {"message": "ok"}
