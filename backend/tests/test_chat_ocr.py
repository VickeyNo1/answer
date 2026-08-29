"""图片 OCR(方案 B)测试:extract_question_text + /api/chat 图片链路"""


class _Msg:
    def __init__(self, content): self.content = content

class _NSChoice:
    def __init__(self, content): self.message = _Msg(content)

class _NSResp:
    def __init__(self, content): self.choices = [_NSChoice(content)]

class _Delta:
    def __init__(self, content): self.content = content; self.tool_calls = None

class _Choice:
    def __init__(self, content, finish): self.delta = _Delta(content); self.finish_reason = finish

class _Chunk:
    def __init__(self, content=None, finish=None):
        self.choices = [_Choice(content, finish)] if (content is not None or finish) else []
        self.usage = None

class _Completions:
    def __init__(self, factory): self._factory = factory
    def create(self, **kwargs):
        _Completions.last_kwargs = kwargs
        items = self._factory()
        # 非流式（无 stream 参数）直接返回首个响应；流式返回迭代器
        if not kwargs.get("stream"):
            return items[0]
        return iter(items)

class FakeClient:
    last_kwargs = None
    def __init__(self, factory): self.chat = type("C", (), {"completions": _Completions(factory)})()


def test_extract_question_text_returns_content(monkeypatch):
    from app.chat import qwen_service
    from app.config import get_settings
    monkeypatch.setattr(qwen_service, "create_client",
                        lambda: FakeClient(lambda: [_NSResp("甲公司2×24年购入存货。")]))
    out = qwen_service.extract_question_text("QUJD")
    assert out == "甲公司2×24年购入存货。"
    # 断言走视觉模型 + 多模态 content
    kw = _Completions.last_kwargs
    assert kw["model"] == get_settings().VISION_MODEL
    user_content = kw["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert any(c.get("type") == "image_url" for c in user_content)


def test_chat_with_image_emits_ocr_and_stores_combined(client, student_headers, monkeypatch):
    from app.chat import router as chat_router
    from app.chat import qwen_service
    from app.database import get_db_ctx
    # router 直接导入函数名，补丁需打到 router 模块的绑定上
    monkeypatch.setattr(chat_router, "extract_question_text", lambda b64: "识别出的题目")
    monkeypatch.setattr(qwen_service, "create_client",
                        lambda: FakeClient(lambda: [_Chunk("答案。", finish="stop")]))
    resp = client.post("/api/chat", json={
        "conversation_id": None, "message": "请解答", "subject": "cpa_acc",
        "image_base64": "QUJD",
    }, headers=student_headers)
    assert resp.status_code == 200
    assert '"type": "ocr"' in resp.text
    with get_db_ctx() as db:
        row = db.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["content"] == "请解答\n\n【图片识别内容】\n识别出的题目"


def test_chat_image_ocr_empty_400_no_message(client, student_headers, monkeypatch):
    from app.chat import router as chat_router
    from app.database import get_db_ctx
    monkeypatch.setattr(chat_router, "extract_question_text", lambda b64: "")
    with get_db_ctx() as db:
        before = db.execute("SELECT COUNT(*) AS cnt FROM messages").fetchone()["cnt"]
    resp = client.post("/api/chat", json={
        "conversation_id": None, "message": "", "subject": "cpa_acc",
        "image_base64": "QUJD",
    }, headers=student_headers)
    # 识别为空直接 400：不建对话、不落库消息、不消耗配额、不进入答题
    assert resp.status_code == 400
    assert "未从图片中识别到题目文字" in resp.text
    with get_db_ctx() as db:
        after = db.execute("SELECT COUNT(*) AS cnt FROM messages").fetchone()["cnt"]
    assert before == after
