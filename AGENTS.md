# AGENTS.md

> 本文件是 **AI 编码助手的唯一入口文档**。开始任何任务前先读本文件，再按需跳转到 `doc/` 下的详细文档。
> 项目：会计答疑智能体（RAG + 大模型的会计专业 AI 答疑系统）
> 文档基线版本：v2.0 ｜ 维护约定见 [§9](#9-文档维护约定ai-必读)

---

## 1. 快速导航（先看这里）

| 我要做什么 | 去哪看 |
|-----------|--------|
| 了解项目/技术栈 | 本文件 [§2](#2-项目概述)、[§3](#3-技术栈以代码实际版本为准) |
| 找模块代码位置与职责 | 本文件 [§4 代码地图](#4-代码地图) |
| 运行 / 测试 / 初始化数据 | 本文件 [§5 常用命令](#5-常用命令) |
| 遵守编码约定、避开已知坑 | 本文件 [§6 约定与注意事项](#6-编码约定与注意事项必读) |
| 查数据库表结构 | 本文件 [§7 数据库](#7-数据库表结构) |
| 查全部接口一览 | 本文件 [§8 接口一览](#8-接口一览26-个业务接口) → 明细见 `doc/接口文档.md` |
| 查接口请求/响应细节 | `doc/接口文档.md` |
| 查架构与开发规范 | `doc/开发文档.md` |
| 查部署与采购成本 | `doc/ops/部署采购方案.md` |

---

## 2. 项目概述

面向会计专业学生的 AI 智能答疑系统，前后端分离：

- **后端**（`backend/`，端口 8000）：FastAPI，提供认证、对话（RAG + 流式）、知识库、管理后台、大模型管理、科目管理接口。
- **前端**（`frontend/`，端口 3000）：Next.js App Router，学生对话页 + 管理员后台。
- **核心链路**：学生提问 → 向量化 → ChromaDB 检索（可按科目加权）→ 组装 Prompt → dashscope 大模型流式回答（SSE）→ 记录用量与费用。

两大能力（v2.0 新增）：
1. **大模型管理**（仅管理员）：配置/切换阿里通义千问与 DeepSeek 模型，查看每日/累计 token 用量与费用。
2. **科目体系**（全员可见）：财务通用类 + 专业课程类；学生选科目后，RAG 检索对该科目知识**加权不过滤**。

---

## 3. 技术栈（以代码实际版本为准）

| 层级 | 技术 | 版本 | 位置 |
|------|------|------|------|
| 前端框架 | Next.js (App Router) | 16.2.10 | `frontend/package.json` |
| UI 库 | React | 19.2.4 | 同上 |
| 样式 | Tailwind CSS | v4 | 同上 |
| Markdown 渲染 | react-markdown + remark-gfm + rehype-highlight | — | 对话回答渲染 |
| 后端框架 | FastAPI | 0.115.* | `backend/requirements.txt` |
| ASGI 服务器 | uvicorn[standard] | 0.30.* | 同上 |
| 关系数据库 | SQLite（WAL 模式） | 内置 | `backend/data/app.db` |
| 向量数据库 | ChromaDB（cosine） | 0.5.* | `backend/data/chroma_db` |
| 大模型/Embedding | dashscope SDK（通义千问 + DeepSeek 统一接入） | 1.20.* | `DASHSCOPE_API_KEY` |
| 认证 | JWT（python-jose）+ bcrypt（passlib） | — | `app/auth/` |
| 文档解析 | python-docx / pypdf / openpyxl | — | `app/knowledge/doc_parser.py` |
| Python 环境 | uv + Python 3.11+ | — | `backend/.venv` |

> ⚠️ DeepSeek 走**阿里百炼统一接入**，复用 `DASHSCOPE_API_KEY`，模型名直接通过 dashscope `Generation.call` 调用，**无需**独立 SDK 或分支。

---

## 4. 代码地图

### 后端 `backend/app/`

| 路径 | 职责 | 关键点 |
|------|------|--------|
| `main.py` | FastAPI 应用入口，注册 7 个 router，CORS，`/api/health` | 启动时 `init_db()` 建表 |
| `config.py` | `Settings`（pydantic-settings），读 `.env` | `get_settings()` 带 `lru_cache` |
| `database.py` | SQLite 建表 + 轻量迁移 | `get_db()`（Depends 生成器）vs `get_db_ctx()`（脚本上下文管理器）见 §6 |
| `models.py` | 全部 Pydantic 请求/响应模型 | 新增接口先在此定义 schema |
| `auth/` | 登录、JWT、依赖 | `deps.py`：`get_current_user`、`require_admin` |
| `chat/` | 对话与 RAG 主流程 | `router.py`（SSE + 对话 CRUD）、`qwen_service.py`（`stream_chat`）、`memory.py`（多轮历史） |
| `knowledge/` | 知识库 | `router.py`（上传/列表/删除）、`chroma_service.py`（向量存取 + `search_weighted`）、`doc_parser.py`、`embedding.py`（text-embedding-v3） |
| `admin/` | 管理后台 | `router.py`（学生增删改查/批量、统计）、`stats.py`（聚合统计） |
| `llm/` | 大模型管理（v2.0） | `router.py`（模型 CRUD/activate/usage）、`store.py`（模型与用量数据访问 + 费用计算） |
| `subjects/` | 科目（v2.0） | `router.py`：`router`（公开列表）+ `admin_router`（管理员 CRUD） |

### 前端 `frontend/src/`

| 路径 | 职责 |
|------|------|
| `app/page.tsx` | 学生对话主页（会话列表、流式对话、科目选择） |
| `app/login/page.tsx` | 登录页 |
| `app/admin/page.tsx` | 管理后台，Tab 容器（学生/知识库/统计/大模型/科目） |
| `components/` | `AuthGuard`、`ChatInput`、`ChatWindow`、`ConversationList` |
| `components/admin/` | `StudentTab`、`KnowledgeTab`、`StatsTab`、`ModelTab`（v2.0）、`SubjectTab`（v2.0） |
| `lib/api.ts` | fetch 封装：`apiGet/apiPost/apiPut/apiDelete/apiUpload` |
| `lib/auth.ts` | token 本地存储与读取 |
| `lib/sse.ts` | SSE 对话客户端 `sendChatMessage(conversationId, message, subjectId, callbacks)` |
| `types/index.ts` | 全部 TypeScript 类型（与后端 `models.py` 对应） |

---

## 5. 常用命令

> 环境：Windows + **PowerShell**。命令分隔符用 `;`，**不要用 `&&`**；PowerShell 无 `tail`/`grep`（用 `Select-Object -Last N` / `Select-String`）。

### 后端（在 `backend/` 目录）

```powershell
# 安装依赖（首次）
uv pip install -r requirements.txt

# 初始化默认数据（管理员 admin/admin123 + 默认模型 + 默认科目，幂等）
uv run python seed.py

# 启动后端（http://localhost:8000，文档 /docs）
uv run uvicorn app.main:app --reload

# 运行测试
uv run pytest -q
```

### 前端（在 `frontend/` 目录）

```powershell
npm install            # 首次
npm run dev            # http://localhost:3000
npx tsc --noEmit       # 类型检查
```

- 默认管理员账号：`admin` / `admin123`（由 `seed.py` 写入）。
- E2E 测试（`tests/e2e/`）在后端未启动时自动 skip。

---

## 6. 编码约定与注意事项（必读）

- **数据库连接两种用法别混用**：接口内用 `Depends(get_db)`（生成器）；脚本/非请求上下文用 `with get_db_ctx() as db`（上下文管理器）。
- **FastAPI 路由顺序**：静态路径要声明在动态路径之前。例如 `/api/admin/models/usage` 必须在 `/{model_id}` 之前，否则会被 `int` 参数路由拦截。
- **科目未分类约定**：`subject_id = 0` 表示「未分类」；历史文档无科目归属时按 0 处理，检索时走普通权重。
- **科目加权检索（不过滤）**：候选取 `top_k×3`，命中所选科目块 `distance×0.6`（`SUBJECT_MATCH_WEIGHT`）、通用类科目块 `distance×0.8`（`GENERAL_WEIGHT`），其余不变，按 distance 升序取前 `top_k`。见 `knowledge/chroma_service.py`。
- **用量采集**：从 dashscope 流式响应的 `usage` 读取 `input_tokens`/`output_tokens`；无 usage 时记 0。费用 = `tokens/1000 × 单价`，单价由管理员维护（不自动同步官方价）。
- **新增/修改接口的落点**：schema → `app/models.py`；路由 → 对应模块 `router.py`；注册 → `app/main.py`；类型 → 前端 `types/index.ts`；文档 → `doc/接口文档.md` + 本文件 §8。
- **认证**：需登录接口带 `Authorization: Bearer <token>`；管理员接口用 `Depends(require_admin)`。
- **响应格式**：成功直接返回业务数据（无外层包裹）；无数据时返回 `{"message": "ok"}`；错误返回 `{"detail": "..."}`。

---

## 7. 数据库表结构

SQLite（WAL），建表见 `app/database.py`。

| 表 | 关键列 | 说明 |
|----|--------|------|
| `users` | `id, student_id(UNIQUE), password_hash, name, role('student'/'admin'), created_at` | 用户/学生 |
| `conversations` | `id, user_id, title, subject_id(可空,v2.0), created_at` | 会话，`subject_id` 为轻量迁移列 |
| `messages` | `id, conversation_id, role, content, created_at` | 消息 |
| `model_configs` | `id, provider('ali'/'deepseek'), model_name(UNIQUE), display_name, price_in, price_out, enabled, is_active, created_at` | 模型配置，`is_active=1` 为当前模型（v2.0） |
| `usage_logs` | `id, model_name, user_id, conversation_id, prompt_tokens, completion_tokens, total_tokens, cost, created_at` | 用量与费用（v2.0） |
| `subjects` | `id, name(UNIQUE), category('general'/'professional'), description, sort_order, created_at` | 科目（v2.0） |

> 迁移方式：`_add_column_if_missing()` 用 `PRAGMA table_info` 检测后 `ALTER TABLE ADD COLUMN`，兼容已有 `app.db`。

---

## 8. 接口一览（26 个业务接口）

Base URL：`http://localhost:8000`。权限：🟢 全员登录 ｜ 🔒 管理员。
**接口明细（请求/响应/示例）是 `doc/接口文档.md` 的单一职责,本节仅作分组索引。**

| 模块 | 代码位置 | 数量 | 权限 | 说明 |
|------|---------|------|------|------|
| 认证 | `app/auth/` | 2 | 公开 / 🟢 | 登录取 JWT、当前用户信息 |
| 对话 | `app/chat/` | 5 | 🟢 | 流式对话(SSE,支持 `subject_id`)、会话 CRUD |
| 知识库 | `app/knowledge/` | 3 | 🔒 | 文档上传(可带 `subject_id`)/列表/删除 |
| 管理员 | `app/admin/` | 6 | 🔒 | 学生增删改查、批量导入、使用统计 |
| 大模型管理（v2.0） | `app/llm/` | 6 | 🔒 | 模型 CRUD、`activate` 切换、`usage` 用量费用 |
| 科目（v2.0） | `app/subjects/` | 4 | 🟢 / 🔒 | 科目列表(全员)+ 科目 CRUD(管理员) |

> 另有运维接口 `GET /api/health`（健康检查，无需认证）。全部接口的路径与字段明细见 `doc/接口文档.md`。

---

## 9. 文档维护约定（AI 必读）

保持文档与代码同步，是本项目文档架构的核心目标：

1. **改代码即改文档**：任何接口/表结构/模块/命令/依赖版本变化，必须在同一次改动中更新受影响文档。
2. **单一事实来源**：
   - 接口明细只写在 `doc/接口文档.md`；本文件 §8 只维护「一览」。
   - 技术栈版本以 `frontend/package.json` / `backend/requirements.txt` 为准，文档引用需与其一致。
3. **新增接口的文档动作**：更新 `doc/接口文档.md` 明细 + 本文件 §8 一览 +（如涉及）§7 表结构。
4. **版本标注**：v2.0 及以后新增内容标注版本，便于区分历史。
5. **不要编造**：不确定的字段/行为先读代码（`Grep`/`Read`）再写；宁可留 TODO 也不臆测。
