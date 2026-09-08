# 图片题目识别(OCR → 复用 RAG 管线) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 学生在对话页上传题目图片,后端先用视觉模型识别题目文字,再把识别文本送入现有 RAG 答疑管线,保留知识库引用/追问建议/知识点追踪等全部能力。

**Architecture:** 方案 B。`POST /api/chat` 增加可选 `image_base64`;预处理阶段调用 `qwen_service.extract_question_text()`(非流式视觉调用)得到识别文本,与用户文字组合成 `effective_message`,后续 `build_messages`+`stream_chat` 完全不变。SSE 新增 `ocr` 事件;识别失败/为空时在流内下发 `error` 事件。图片不落库。

**Tech Stack:** FastAPI / Pydantic / pytest(后端);Next.js + React + TypeScript(前端);百炼 OpenAI 兼容端点(视觉模型)。

设计文档:`docs/plans/2026-08-29-image-ocr-rag-design.md`

---

### Task 1: 配置 + OCR 服务函数 `extract_question_text`

**Files:**
- Modify: `backend/app/config.py`(加 `VISION_MODEL`)
- Modify: `backend/app/chat/qwen_service.py`(加 `extract_question_text`)
- Test: `backend/tests/test_chat_ocr.py`(新建)

**Step 1: 写失败测试**

```python
# backend/tests/test_chat_ocr.py
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
        return iter(self._factory())

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
    kw = FakeClient.last_kwargs
    assert kw["model"] == get_settings().VISION_MODEL
    user_content = kw["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert any(c.get("type") == "image_url" for c in user_content)
```

**Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_chat_ocr.py::test_extract_question_text_returns_content -v`
Expected: FAIL(`extract_question_text` / `VISION_MODEL` 不存在)

**Step 3: 最小实现**

`config.py` 的 `Settings` 中 `CHAT_MODEL` 之后加:

```python
    # 视觉(OCR)模型
    VISION_MODEL: str = "qwen-vl-max"
```

`qwen_service.py` 顶部加 OCR 常量与函数:

```python
OCR_USER_PROMPT = (
    "请完整、准确地识别并转录图片中的会计题目文字，包括题干、选项、材料、要求等，"
    "保持原有结构与格式，只输出转录文本，不要解答、不要额外解释。"
)


def extract_question_text(image_base64: str, model_name: str | None = None) -> str:
    """单次非流式视觉调用,识别图片中的题目文字(方案 B OCR 步骤)"""
    settings = get_settings()
    model = model_name or settings.VISION_MODEL
    client = create_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": OCR_USER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ]},
        ],
        extra_body={"enable_thinking": False},
    )
    return (resp.choices[0].message.content or "").strip()
```

**Step 4: 运行确认通过**

Run: `uv run pytest tests/test_chat_ocr.py -v`
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/config.py backend/app/chat/qwen_service.py backend/tests/test_chat_ocr.py
git commit -m "feat: 新增视觉OCR函数extract_question_text与VISION_MODEL配置"
```

---

### Task 2: `ChatRequest.image_base64` + 路由 OCR 集成 + SSE `ocr`/`error` 事件

**Files:**
- Modify: `backend/app/models.py`(`ChatRequest`)
- Modify: `backend/app/chat/router.py`(预处理 OCR + generator 事件)
- Test: `backend/tests/test_chat_ocr.py`(追加路由级测试)

**Step 1: 写失败测试**(追加到 test_chat_ocr.py)

```python
def test_chat_with_image_emits_ocr_and_stores_combined(client, student_headers, monkeypatch):
    from app.chat import qwen_service
    from app.database import get_db_ctx
    monkeypatch.setattr(qwen_service, "extract_question_text", lambda b64: "识别出的题目")
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


def test_chat_image_ocr_empty_errors(client, student_headers, monkeypatch):
    from app.chat import qwen_service
    monkeypatch.setattr(qwen_service, "extract_question_text", lambda b64: "")
    resp = client.post("/api/chat", json={
        "conversation_id": None, "message": "", "subject": "cpa_acc",
        "image_base64": "QUJD",
    }, headers=student_headers)
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert '"type": "delta"' not in resp.text
```

**Step 2: 运行确认失败**

Run: `uv run pytest tests/test_chat_ocr.py -v`
Expected: FAIL(`image_base64` 字段/ocr 事件不存在)

**Step 3: 最小实现**

`models.py` `ChatRequest` 加字段:

```python
class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    subject: str | None = None
    image_base64: str | None = None
```

`router.py`:导入 `extract_question_text`;在并发闸门(步骤 3)之后、确定对话 ID(步骤 4)之前插入:

```python
        # 3.5 图片 OCR(方案 B):识别题目文字;失败不抛异常,转 SSE error
        ocr_text = None
        ocr_error = None
        if req.image_base64:
            try:
                ocr_text = (extract_question_text(req.image_base64) or "").strip()
                if not ocr_text:
                    ocr_error = "未从图片中识别到题目文字，请重拍或改用文字提问"
            except Exception as e:
                ocr_error = f"图片识别失败，请稍后再试（{e}）"
        effective_message = req.message
        if ocr_text:
            effective_message = (
                f"{req.message}\n\n【图片识别内容】\n{ocr_text}"
                if req.message.strip() else ocr_text
            )
```

并把步骤 4 标题、步骤 5 插入、步骤 6 历史排除与 `build_messages` 全部从 `req.message` 改为 `effective_message`(历史排除行:`history[-1]["content"] == effective_message`)。

generator 中排队循环之后、`stream_chat` 循环之前插入:

```python
            if ocr_text:
                yield _sse({"type": "ocr", "text": ocr_text})
            if ocr_error:
                yield _sse({"type": "error", "detail": ocr_error})
                error_occurred = True
            for chunk in stream_chat(...) if not error_occurred else []:
                ...
```

(即把原 `for chunk in stream_chat(...)` 改为仅在 `not error_occurred` 时迭代。)

**Step 4: 运行确认通过**

Run: `uv run pytest tests/test_chat_ocr.py -v`
Expected: PASS
回归: `uv run pytest tests/test_chat_sse.py tests/test_chat_quota.py -v`
Expected: PASS(无图流程不变)

**Step 5: 提交**

```bash
git add backend/app/models.py backend/app/chat/router.py backend/tests/test_chat_ocr.py
git commit -m "feat: /api/chat支持image_base64,OCR后复用RAG管线并下发ocr事件"
```

---

### Task 3: 前端图片上传 + 压缩 + 发送 + ocr 展示

**Files:**
- Create: `frontend/src/lib/image.ts`
- Modify: `frontend/src/lib/sse.ts`(加 `onOcr` + `image_base64`)
- Modify: `frontend/src/components/ChatInput.tsx`(图片按钮/预览/压缩)
- Modify: `frontend/src/components/ChatWindow.tsx`(streaming 气泡显示 ocr)
- Modify: `frontend/src/app/page.tsx`(串接 image 状态与回调)

> 前端无单测基建,以 `npm run build` + 手工验证为准。

**Step 1: 新建压缩工具 `frontend/src/lib/image.ts`**

```ts
/** 选图 → canvas 压缩(长边≤1280、JPEG 0.8)→ 返回纯 base64(不含 data: 前缀) */
export function compressImage(file: File, maxEdge = 1280, quality = 0.8): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("canvas 不可用"));
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality).split(",")[1]);
      };
      img.onerror = () => reject(new Error("图片加载失败"));
      img.src = reader.result as string;
    };
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}
```

**Step 2: `sse.ts` 增加 ocr 回调与请求字段**

- `SSECallbacks` 加 `onOcr?: (text: string) => void;`
- `sendChatMessage` 签名加 `imageBase64?: string | null`,body 加 `image_base64: imageBase64 || undefined`
- switch 加 `case "ocr": callbacks.onOcr?.(data.text); break;`

**Step 3: `ChatInput.tsx` 加图片按钮**

- `onSend` 类型改为 `(message: string, imageBase64?: string | null) => void`
- 新增 `imageBase64` state + 隐藏 `<input type="file" accept="image/*">` + 📎 按钮 + 缩略图预览(可移除)
- `handleSubmit` 条件改为 `!disabled && (trimmed || imageBase64)`;发送后清空 text 与 imageBase64

**Step 4: `ChatWindow.tsx` streaming 气泡显示 ocr**

- props 加 `ocrText?: string | null`
- streaming 气泡内 `kbSearching` 块旁加:当 `ocrText && !streamingContent` 时显示 `已识别题目,正在作答…` 一行(可附 ocrText 截断预览)

**Step 5: `page.tsx` 串接**

- 新增 `ocrText` state;`handleSendMessage(message, imageBase64?)` 里重置 `setOcrText(null)`,调用 `sendChatMessage(convId, message, subject, imageBase64, {...callbacks, onOcr: setOcrText})`
- 将 `ocrText` 传入 `<ChatWindow>`

**Step 6: 构建验证**

Run: `cd frontend && npm run build`
Expected: 编译 + TypeScript 通过

**Step 7: 提交**

```bash
git add frontend/src
git commit -m "feat: 对话页支持上传图片题目(压缩+预览+ocr展示)"
```

---

### Task 4: Nginx 请求体上限 + 部署

**Files:**
- Modify: 机器B `/etc/nginx/conf.d/*.conf`(server 或 location 块)

**Step 1: 调大 body 上限**

在对应 `server{}` 内加:

```nginx
client_max_body_size 10m;
```

**Step 2: 校验并重载**

Run: `nginx -t && systemctl reload nginx`
Expected: syntax ok

**Step 3: 部署后端+前端**

Run: `bash /opt/answer/deploy/deploy.sh`
Expected: 构建通过、服务重启

---

### Task 5: 端到端手工验证(机器B)

**Step 1:** 登录学生账号,对话页上传一张真实 CPA 题目照片(可手机拍屏幕)。
**Step 2:** 观察:出现"已识别题目"提示 → 流式输出答案 → 若命中知识库出现引用卡片。
**Step 3:** 检查 DB:`SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT 1;` 应含 `【图片识别内容】`。
**Step 4:** 验证识别效果不佳时切换模型:在 `backend/.env` 设 `VISION_MODEL`(如 `qwen-vl-plus`/`qwen3-vl` 系列)→ `systemctl restart answer-backend` → 重测。

---

## 风险与回退

- 视觉模型名需以真实题目图验证;若 `qwen-vl-max` 效果/价格不合,改 `VISION_MODEL` 即可,无需改代码。
- 若 OCR 质量不达标,回退:前端隐藏图片按钮即关闭入口,后端字段向后兼容(不传 `image_base64` 走原文本流程)。
