# 图片题目识别(OCR → 复用 RAG 管线)设计

> 日期:2026-08-29
> 状态:已确认(方案 B,入口仅对话页)

## 目标

学生在对话页上传题目图片,系统先用视觉模型识别图中题目文字,再把识别文本送入**现有 RAG 答疑管线**,从而保留知识库引用、追问建议、知识点追踪、错题本/画像等全部既有能力。

MVP 范围:**仅在对话页**增加图片入口;考试/错题页暂不支持。

## 方案选型回顾

- 方案 A(图片直答):改动最小但不走 KB,无引用/追踪。
- **方案 B(OCR→RAG,选定)**:两次调用,但完整复用现有管线。
- 方案 C(独立拍照页):重复建设,放弃。

## 数据流

1. 前端:选图 → canvas 压缩(长边 ≤1280px、JPEG 0.8)→ base64 预览 → 随消息发送 `image_base64`。
2. 后端 `chat/router.py`:
   a. 若 `image_base64` 非空,先调用视觉模型(`VISION_MODEL`,非流式)识别题目文字 → `extracted`。
   b. `effective_message = combine(req.message, extracted)`:
      - 仅有图:`effective = extracted`
      - 图+文:`effective = f"{req.message}\n\n【图片识别内容】\n{extracted}"`
   c. 下发 SSE 事件 `{"type":"ocr","text":extracted}`,前端展示"已识别题目"。
   d. **在 DB 插入 user 消息之前**完成 OCR,使 `messages` 表与 `build_messages` 都使用 `effective_message`。
3. 下游 `build_messages` + `stream_chat`(RAG/Function Calling/流式/追问建议)**完全不变**。
4. 识别失败/为空 → 下发 SSE error,不进入答题流程。

## 组件改动

| 模块 | 文件 | 改动 |
|---|---|---|
| 配置 | `backend/app/config.py` | 新增 `VISION_MODEL`(默认 `qwen-vl-max`,可切换) |
| 模型 | `backend/app/models.py` | `ChatRequest` 增加 `image_base64: str \| None = None` |
| 服务 | `backend/app/chat/qwen_service.py` | 新增 `extract_question_text(image_base64) -> str`(单次非流式视觉调用) |
| 路由 | `backend/app/chat/router.py` | OCR 步骤 + 组合消息 + SSE ocr 事件;OCR 置于 DB 插入前 |
| 前端 | `frontend/src/app/(chat)` 输入组件 | 图片按钮、压缩、预览、发送、展示 ocr 事件 |

## OCR Prompt

```
请完整、准确地识别并转录图片中的会计题目文字,包括题干、选项、材料、要求等,
保持原有结构与格式,只输出转录文本,不要解答、不要额外解释。
```

## 存储

- `messages` 表存 `effective_message`(纯文本),**图片不落库**(MVP)。
- 历史会话展示识别文本;图片仅当次会话本地显示,刷新后为文本/占位。

## 错误处理

- 图片超大/格式非法 → 400。
- OCR 调用异常 → SSE `{"type":"error"}`,提示"图片识别失败"。
- OCR 结果为空 → SSE error,提示重拍或改用文字。

## 成本与配额

- 每道图片题两次 LLM 调用(OCR + 答题)。OCR 用便宜视觉模型,答题用用户选定文本模型。
- 用量记账复用现有逻辑;OCR 用量并入该次总量。
- 图片题仍计 1 次每日提问配额。

## 配套

- Nginx `client_max_body_size` 调大(压缩后 base64 约几百 KB)。
- 上线前用真实 CPA 题目图验证 `VISION_MODEL` 识别效果,必要时切换模型。

## 测试

- mock 视觉 OCR 返回,断言组合消息进入 RAG 流程且 SSE 含 ocr 事件。
- 断言无图消息流程完全不变(回归)。
- 断言 OCR 失败/为空 → error 事件,不答题。
