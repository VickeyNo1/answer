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
                        lambda *a, **k: FakeClient(lambda: [_NSResp("甲公司2×24年购入存货。")]))
    # 本用例无 db_ready 门（MySQL 不可达也会跑），记账必须打桩
    rows: list[dict] = []
    monkeypatch.setattr(
        qwen_service.llm_store, "record_usage",
        lambda model, uid, cid, tin, tout, task_type="chat": rows.append(
            {"model": model, "user_id": uid, "conversation_id": cid, "task_type": task_type}),
    )
    out = qwen_service.extract_question_text("QUJD", 42)
    assert out == "甲公司2×24年购入存货。"
    # 断言走视觉模型 + 多模态 content
    kw = _Completions.last_kwargs
    assert kw["model"] == get_settings().VISION_MODEL
    user_content = kw["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert any(c.get("type") == "image_url" for c in user_content)
    # OCR 用量单独记账；conversation_id 只能是 None（OCR 在建对话之前执行）
    assert rows == [{"model": get_settings().VISION_MODEL, "user_id": 42,
                     "conversation_id": None, "task_type": "ocr"}]


def test_extract_question_text_usage_failure_does_not_break_ocr(monkeypatch):
    """记账失败（如 DB 不可达）不得影响识别结果返回"""
    from app.chat import qwen_service

    def _boom(*a, **kw):
        raise RuntimeError("DB 不可达")

    monkeypatch.setattr(qwen_service, "create_client",
                        lambda *a, **k: FakeClient(lambda: [_NSResp("题干。")]))
    monkeypatch.setattr(qwen_service.llm_store, "record_usage", _boom)
    assert qwen_service.extract_question_text("QUJD", 1) == "题干。"


def test_chat_with_image_emits_ocr_and_stores_combined(client, student_headers, monkeypatch):
    from app.chat import router as chat_router
    from app.chat import solver
    from app.database import get_db_ctx
    # router 直接导入函数名，补丁需打到 router 模块的绑定上；
    # extract_question_text 已新增 user_id 参数，桩必须能吃下第二个实参
    monkeypatch.setattr(chat_router, "extract_question_text", lambda b64, *a: "识别出的题目")
    # 带图 → intent=solve → 走 solver.run_solve；检索与校验必须打桩，
    # 否则会真打 HTTP 到机器A（超时 + 网络依赖）
    monkeypatch.setattr(
        solver.kb_client, "search",
        lambda **kw: {"collection": "questions", "results": [{
            "question_id": "Q-IMG", "question_type": "单选", "chapter": "第一章 总论",
            "knowledge_point_ids": ["ACC-01-03-01"], "stem": "识别出的题目",
            "options": {"A": "甲", "B": "乙"}, "answer": "B",
            "explanation": "解析", "materials": None, "sub_questions": None, "score": 0.9,
        }]} if kw.get("collection") == "questions" else None,
    )
    monkeypatch.setattr(solver, "verify_same_question",
                        lambda *a, **kw: {"same": True, "index": 1, "reason": "同一道题"})
    # solver 与 qwen_service 各自持有 create_client 绑定，solve 路径要 patch solver 的
    monkeypatch.setattr(solver, "create_client",
                        lambda *a, **k: FakeClient(lambda: [_Chunk("答案。", finish="stop")]))
    resp = client.post("/api/chat", json={
        "conversation_id": None, "message": "请解答", "subject": "cpa_acc",
        "image_base64": "QUJD",
    }, headers=student_headers)
    assert resp.status_code == 200
    assert '"type": "ocr"' in resp.text
    # solve 档位经 match 事件下发 + 标注随正文落库（前端零改动的档位可见性手段）
    assert '"type": "match"' in resp.text and '"tier": "exact"' in resp.text
    assert solver.EXACT_SUFFIX.strip() in resp.text
    with get_db_ctx() as db:
        row = db.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["content"] == "请解答\n\n【图片识别内容】\n识别出的题目"


def test_chat_image_solve_retrieval_query_excludes_ocr_prefix(
        client, student_headers, monkeypatch):
    """检索 query 必须用识别原文，不能用组合后的「请解答\\n\\n【图片识别内容】\\n…」——
    那段前缀会污染向量检索"""
    from app.chat import router as chat_router
    from app.chat import solver

    queries: list[str] = []
    monkeypatch.setattr(chat_router, "extract_question_text",
                        lambda b64, *a: "甲公司购入存货一批价款100万元")
    monkeypatch.setattr(solver.kb_client, "search",
                        lambda **kw: queries.append(kw["query"]))
    monkeypatch.setattr(solver, "verify_same_question",
                        lambda *a, **kw: {"same": False, "index": None, "reason": "x"})
    monkeypatch.setattr(solver, "create_client",
                        lambda *a, **k: FakeClient(lambda: [_Chunk("答案。", finish="stop")]))
    resp = client.post("/api/chat", json={
        "conversation_id": None, "message": "请解答", "subject": "cpa_acc",
        "image_base64": "QUJD",
    }, headers=student_headers)
    assert resp.status_code == 200
    assert queries
    assert all("【图片识别内容】" not in q for q in queries)
    assert queries[0] == "甲公司购入存货一批价款100万元"


def test_chat_image_ocr_empty_400_no_message(client, student_headers, monkeypatch):
    from app.chat import router as chat_router
    from app.database import get_db_ctx
    monkeypatch.setattr(chat_router, "extract_question_text", lambda b64, *a: "")
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
