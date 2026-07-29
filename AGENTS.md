# AGENTS.md

> 本文件是 **AI 编码助手的唯一入口文档**。开始任何任务前先读本文件，再按需跳转到 `doc/` 下的详细文档。
> 项目：会计答疑智能体（大模型 Function Calling 对接外部知识库检索服务的会计专业 AI 答疑系统）
> 文档基线版本：v4.0（M1） ｜ 维护约定见 [§9](#9-文档维护约定ai-必读)

---

## 0. 部署架构（A/B 双服务器约定，务必牢记）

> **A = 数据服务器**：公网 `8.134.97.196` / 私网 `172.22.207.228`（Alibaba Cloud Linux 3）。跑 **MySQL 8.4** + 向量化知识库 + **知识库检索服务 `:8100`**。
> **B = 应用服务器**：公网 `8.148.219.179` / 私网 `172.17.240.44`（Alibaba Cloud Linux 2）。跑 **Nginx + Next.js + FastAPI**。
> 两机通过 VPC 对等连接私网互通（可用区广州A）。
>
> - **开发环境**：直连机器A **公网** MySQL（`8.134.97.196:3306`）与知识库服务；密码等填 `backend/.env`（勿提交）。
> - **生产环境**：应用服务器 B 走 **私网** 访问 A（`172.22.207.228`）。
> - 知识库检索服务仅私网暴露 `:8100`；契约见 `doc/知识库对接文档.md`、`doc/知识库科目枚举约定.md`。

---

## 1. 快速导航（先看这里）

| 我要做什么 | 去哪看 |
|-----------|--------|
| 了解项目/技术栈 | 本文件 [§2](#2-项目概述)、[§3](#3-技术栈以代码实际版本为准) |
| 找模块代码位置与职责 | 本文件 [§4 代码地图](#4-代码地图) |
| 运行 / 测试 / 初始化数据 | 本文件 [§5 常用命令](#5-常用命令) |
| 遵守编码约定、避开已知坑 | 本文件 [§6 约定与注意事项](#6-编码约定与注意事项必读) |
| 查数据库表结构 | 本文件 [§7 数据库](#7-数据库表结构) |
| 查全部接口一览 | 本文件 [§8 接口一览](#8-接口一览28-个业务接口) → 明细见 `doc/接口文档.md` |
| 查接口请求/响应细节 | `doc/接口文档.md` |
| 查架构与开发规范 | `doc/开发文档.md` |
| 查部署与运维 | `doc/ops/部署文档.md` |
| 恢复上次工作进度（跨设备/新会话） | `doc/ops/工作状态.md` → 约定见本文件 [§10](#10-跨设备工作状态同步约定ai-必读) |

---

## 2. 项目概述

面向会计专业学生的 AI 智能答疑系统，前后端分离：

- **后端**（`backend/`，端口 8000）：FastAPI，提供认证、对话（Function Calling + 流式）、答案反馈、管理后台（含全局设置/权益/检索报表）、大模型管理、科目列表接口。
- **前端**（`frontend/`，端口 3000）：Next.js App Router，学生对话页 + 管理员后台。
- **核心链路（v4.0 M1）**：学生提问 → 前置校验（每日配额 → 单人串行 → 并发闸门+有限排队，任一不过 429）→ dashscope 大模型带 `search_cpa_knowledge` 工具流式生成 → 模型决定是否检索 → 后端调机器A 知识库检索服务 `POST /kb/search`（subject 由后端注入，每次调用写 `kb_search_logs`）→ 拼接检索结果作二轮流式回答（SSE，含 `kb_refs` 引用卡片、`suggestions` 追问建议）→ 落库知识点编号（`knowledge_point_ids`）并记录用量费用。

两大要点（v3.0）：
1. **知识库对接**：本地 ChromaDB RAG 全部移除，改为对接机器A 外部知识库检索服务；大模型通过 Function Calling 自主决定是否检索，检索失败自动降级为大模型直答（不报错）。
2. **科目体系**：本地科目 CRUD 移除，科目枚举由知识库侧维护（当前仅 `cpa_acc` = CPA 会计 online），后端硬编码注册表并通过 `GET /api/subjects` 只暴露 online 项。

v4.0 M1 试点底座新增要点：
3. **对话限流**：每日配额（users 覆盖值 ?? 全局默认）+ 单人串行 + 全局并发闸门与有限排队（线程级方案，见 `app/chat/concurrency.py`），三种情形均返回 429（文案区分）。
4. **可观测与反馈**：检索日志 `kb_search_logs`（六态状态）+ 答案反馈 `feedbacks`（点赞/点踩 UPSERT）+ 管理端报表（反馈明细/检索质量/高频知识点）。
5. **全局设置与权益**：`app_settings` K-V 表 + 内存缓存（`app/settings_store.py`）；单人权益覆盖值存 users 新增两列，生效值计算见 `app/admin/entitlements.py`。

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
| 关系数据库 | MySQL 8.4（机器A，utf8mb4） | — | 连接配置见 `backend/.env` |
| MySQL 驱动 | PyMySQL（DictCursor） | 1.1.* | `app/database.py` |
| 知识库检索 | 外部检索服务 `POST /kb/search`（HTTP） | — | `app/kb/client.py`（httpx） |
| 大模型 | dashscope SDK（通义千问 + DeepSeek 统一接入，Function Calling） | 1.20.* | `DASHSCOPE_API_KEY` |
| 认证 | JWT（python-jose）+ bcrypt（passlib） | — | `app/auth/` |
| Excel 解析 | openpyxl（学生批量导入） | 3.1.* | `app/admin/` |
| Python 环境 | uv + Python 3.11+ | — | `backend/.venv` |

> ⚠️ DeepSeek 走**阿里百炼统一接入**，复用 `DASHSCOPE_API_KEY`，模型名直接通过 dashscope `Generation.call` 调用，**无需**独立 SDK 或分支。

---

## 4. 代码地图

### 后端 `backend/app/`

| 路径 | 职责 | 关键点 |
|------|------|--------|
| `main.py` | FastAPI 应用入口，注册 6 个 router，CORS，`/api/health`（三字段） | 启动时 `init_db()` 建库建表 + 加载设置缓存 + 初始化并发闸门 |
| `config.py` | `Settings`（pydantic-settings），读 `.env` | `MYSQL_*` / `KB_*` 配置；`get_settings()` 带 `lru_cache` |
| `database.py` | MySQL 建库建表（PyMySQL + DictCursor） | `DB` 包装类保留 `db.execute()` 习惯；`get_db()`（Depends 生成器）vs `get_db_ctx()`（脚本上下文管理器）见 §6；存量库幂等补 users 新列 |
| `models.py` | 全部 Pydantic 请求/响应模型 | 新增接口先在此定义 schema |
| `settings_store.py` | `app_settings` 全局设置：内存缓存 + 类型转换（v4.0） | 启动时全量加载，PUT 更新后刷新缓存；值统一字符串落库、读时按键转 int/bool |
| `auth/` | 登录、JWT、依赖、自助改密码 | `deps.py`：`get_current_user`、`require_admin`；`router.py` 另含 `me_router`（`PUT /api/me/password`，v4.0） |
| `chat/` | 对话主流程 | `router.py`（SSE + 对话 CRUD + `POST /api/feedback`）、`qwen_service.py`（`stream_chat` Function Calling 两轮流式，含降级话术/追问建议解析）、`memory.py`（多轮历史）、`concurrency.py`（线程级并发闸门/单人串行/有限排队，v4.0） |
| `kb/` | 知识库对接（v3.0） | `client.py`（`POST /kb/search`，超时/5001 重试1次后降级；v4.0 新增：每次检索写 `kb_search_logs`、`probe()` 供健康检查探测）、`prompt.py`（`SEARCH_TOOL` schema + 结果拼接 + `collect_kp_ids`）、`subjects.py`（科目注册表 + `GET /api/subjects`） |
| `admin/` | 管理后台 | `router.py`（学生增删改查/批量、统计；v4.0 新增：全局设置 GET/PUT、单人权益、反馈明细、检索报表 kb/stats + kb/hot-kps）、`stats.py`（聚合统计）、`entitlements.py`（权益生效值：users 覆盖值 ?? 全局默认，v4.0） |
| `llm/` | 大模型管理 | `router.py`（模型 CRUD/activate/usage）、`store.py`（模型与用量数据访问 + 费用计算） |

### 前端 `frontend/src/`

| 路径 | 职责 |
|------|------|
| `app/page.tsx` | 学生对话主页（会话列表、流式对话、科目选择） |
| `app/login/page.tsx` | 登录页 |
| `app/admin/page.tsx` | 管理后台，Tab 容器（统计/学生/大模型） |
| `components/` | `AuthGuard`、`ChatInput`、`ChatWindow`（含「正在检索知识库…」提示）、`ConversationList` |
| `components/admin/` | `StatsTab`、`StudentTab`、`ModelTab` |
| `lib/api.ts` | fetch 封装：`apiGet/apiPost/apiPut/apiDelete/apiUpload` |
| `lib/auth.ts` | token 本地存储与读取 |
| `lib/sse.ts` | SSE 对话客户端 `sendChatMessage(conversationId, message, subject, callbacks)`（处理 `kb_search`/`kp_ids`/`queue`/`kb_refs`/`suggestions` 事件） |
| `types/index.ts` | 全部 TypeScript 类型（与后端 `models.py` 对应） |

---

## 5. 常用命令

> 环境：Windows + **PowerShell**。命令分隔符用 `;`，**不要用 `&&`**；PowerShell 无 `tail`/`grep`（用 `Select-Object -Last N` / `Select-String`）。

### 后端（在 `backend/` 目录）

```powershell
# 安装依赖（首次；pyproject.toml 为准，requirements.txt 同步维护）
uv sync

# 初始化默认数据（管理员 admin/admin123 + 默认模型 + 默认全局设置 app_settings，幂等）
# 需 backend/.env 已填机器A MySQL 连接信息（MYSQL_PASSWORD 勿留 CHANGE_ME）
uv run python seed.py

# 启动后端（http://localhost:8000，文档 /docs）；启动时自动建库建表
uv run uvicorn app.main:app --reload

# 运行测试（MySQL 不可达时全部 skip；测试库 answer_test 自动建表/清理）
uv run pytest -q
```

### 前端（在 `frontend/` 目录）

```powershell
npm install            # 首次
npm run dev            # http://localhost:3000
npx tsc --noEmit       # 类型检查
```

- 默认管理员账号：`admin` / `admin123`（由 `seed.py` 写入）。
- 测试库 `answer_test`（`tests/conftest.py` 自动建库建表 + teardown DROP）；机器A MySQL 不可达时全部测试 skip。
- E2E 测试（`tests/e2e/`）在后端未启动时自动 skip。

---

## 6. 编码约定与注意事项（必读）

- **数据库连接两种用法别混用**：接口内用 `Depends(get_db)`（生成器）；脚本/非请求上下文用 `with get_db_ctx() as db`（上下文管理器）。
- **SQL 占位符统一用 `%s`**（PyMySQL 风格），**不要用 `?`**；日期用 MySQL 函数（如 `CURDATE()`，不要用 SQLite 的 `DATE('now')`）。
- **PyMySQL 返回类型陷阱**：`fetchall()` 结果需 `list()` 化再传给 Pydantic；`SUM()` 返回 `Decimal`（用 `int()`/`float()` 包裹）；`DATE` 列返回 `date`、`created_at` 返回 `datetime`（作为字符串字段时需 `str()`）。
- **FastAPI 路由顺序**：静态路径要声明在动态路径之前。例如 `/api/admin/models/usage` 必须在 `/{model_id}` 之前，否则会被 `int` 参数路由拦截。
- **Function Calling subject 注入**：`search_cpa_knowledge` tool schema 只暴露 `query`/`collection`/`top_k`，**`subject` 由后端从会话上下文注入**（模型不可决定），避免模型乱填枚举。
- **KB 检索降级策略**：`app/kb/client.py` 调 `POST /kb/search`，超时或 `5001` 重试 1 次后仍失败返回 `None`，链路**降级为大模型直答（不报错）**，降级话术分档附在答案尾部（不可用/空结果两档，v4.0）；每次检索调用均写 `kb_search_logs`（六态状态，写失败不影响主链路，v4.0）；`knowledge_point_ids` 必须落库 `messages.knowledge_point_ids`（JSON 数组）。
- **对话限流三态 429（v4.0）**：`POST /api/chat` 前置校验按序执行——每日配额（生效值见 `app/admin/entitlements.py`）→ 单人串行 → 并发闸门+有限排队（`app/chat/concurrency.py`，线程级方案勿改 asyncio），三种情形文案区分；并发资源必须在 finally 中配对归还。
- **v4.0 新增路由用 `Depends(get_db)`**：存量 chat/admin 路由内的 `with get_db_ctx()` 属 P1 技术债择机偿还；仅后台任务（无请求上下文）才用 `get_db_ctx()`。
- **科目枚举不得自造**：枚举字典由知识库侧维护，见 `app/kb/subjects.py::SUBJECT_REGISTRY`（只增不改，与 `doc/知识库科目枚举约定.md` 一致）；请求 `subject` 非法时回退 `DEFAULT_SUBJECT`（`cpa_acc`）。
- **用量采集**：从 dashscope 流式响应的 `usage` 读取 `input_tokens`/`output_tokens`（Function Calling 两轮累加）；无 usage 时记 0。费用 = `tokens/1000 × 单价`，单价由管理员维护（不自动同步官方价）。
- **新增/修改接口的落点**：schema → `app/models.py`；路由 → 对应模块 `router.py`；注册 → `app/main.py`；类型 → 前端 `types/index.ts`；文档 → `doc/接口文档.md` + 本文件 §8。
- **认证**：需登录接口带 `Authorization: Bearer <token>`；管理员接口用 `Depends(require_admin)`。
- **响应格式**：成功直接返回业务数据（无外层包裹）；无数据时返回 `{"message": "ok"}`；错误返回 `{"detail": "..."}`。

---

## 7. 数据库表结构

MySQL 8.4（机器A，InnoDB，utf8mb4），建表见 `app/database.py`（`init_db()` 启动时 `CREATE DATABASE IF NOT EXISTS` + 建 8 张表，建表 SQL 含表/字段中文注释；存量库幂等补 users 新列）。存量库补注释用 `backend/scripts/add_table_comments.py`（幂等，改注释时与 `TABLES_SQL` 两处同改）。**无 `subjects` 表**（科目改为知识库侧枚举，见 §6）。

| 表 | 关键列 | 说明 |
|----|--------|------|
| `users` | `id, student_id(UNIQUE), password_hash, name, role('student'/'admin'), daily_question_limit(INT,可空), memory_enabled(TINYINT,可空), created_at` | 用户/学生；v4.0 新增两列为权益覆盖值，NULL=跟随全局默认（`app_settings`） |
| `conversations` | `id, user_id, title, subject(VARCHAR(32),可空), created_at` | 会话，`subject` 存科目枚举值（如 `cpa_acc`） |
| `messages` | `id, conversation_id, role, content, knowledge_point_ids(TEXT,可空), created_at` | 消息，`knowledge_point_ids` 存 KB 命中知识点编号 JSON 数组 |
| `model_configs` | `id, provider('ali'/'deepseek'), model_name(UNIQUE), display_name, price_in, price_out, enabled, is_active, created_at` | 模型配置，`is_active=1` 为当前模型 |
| `usage_logs` | `id, model_name, user_id, conversation_id, prompt_tokens, completion_tokens, total_tokens, cost, created_at` | 用量与费用 |
| `feedbacks` ✦ | `id, message_id(UNIQUE), user_id, rating('up'/'down'), reason(VARCHAR(500),可空), created_at` | 答案反馈（消息级点赞/点踩）；`message_id` 唯一，重复提交 UPSERT 覆盖 |
| `kb_search_logs` ✦ | `id, user_id, conversation_id(可空), subject, collection, query, result_count, kp_ids(TEXT,可空), status, elapsed_ms, created_at` | 知识库检索日志（可观测）；`status` 六态：ok/empty/timeout/http_error/code_error/degraded |
| `app_settings` ✦ | `id, setting_key(UNIQUE), setting_value(VARCHAR(255)), updated_at` | 全局设置（K-V）；值统一存字符串，读时按键转型（`app/settings_store.py`） |

> 标 ✦ 的为 v4.0 M1 新增。不迁移旧 SQLite 数据；MySQL 为全新库，首次 `seed.py` 写入管理员 + 默认模型 + 默认全局设置。

---

## 8. 接口一览（28 个业务接口）

Base URL：`http://localhost:8000`。权限：🟢 全员登录 ｜ 🔒 管理员。
**接口明细（请求/响应/示例）是 `doc/接口文档.md` 的单一职责,本节仅作分组索引。**

| 模块 | 代码位置 | 数量 | 权限 | 说明 |
|------|---------|------|------|------|
| 认证 | `app/auth/` | 3 | 公开 / 🟢 | 登录取 JWT、当前用户信息、自助改密码 `PUT /api/me/password`（v4.0） |
| 对话 | `app/chat/` | 6 | 🟢 | 流式对话（SSE，支持 `subject` 枚举，事件全集 `start/queue/kb_search/kb_refs/kp_ids/delta/suggestions/done/error`，限流三态 429）、答案反馈 `POST /api/feedback`（v4.0）、会话 CRUD |
| 管理员 | `app/admin/` | 12 | 🔒 | 学生增删改查、批量导入、使用统计；v4.0 新增：全局设置 GET/PUT、单人权益 `PUT /students/{id}/entitlements`、反馈明细 `GET /feedbacks`、检索报表 `GET /kb/stats` + `GET /kb/hot-kps` |
| 大模型管理 | `app/llm/` | 6 | 🔒 | 模型 CRUD、`activate` 切换、`usage` 用量费用 |
| 科目 | `app/kb/subjects.py` | 1 | 🟢 | `GET /api/subjects` 返回已上线科目枚举 |

> 反馈提交（`POST /api/feedback`）属对话模块（代码在 `chat/router.py`）；反馈明细/全局设置/权益/检索报表属管理员模块（代码在 `admin/router.py`）。
> 另有运维接口 `GET /api/health`（健康检查，无需认证；v4.0 升级为三字段 `status/mysql/kb`，任一依赖 fail 时 `status=degraded` 但 HTTP 仍 200，KB 探测见 `app/kb/client.py::probe`）。全部接口的路径与字段明细见 `doc/接口文档.md`。

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

---

## 10. 跨设备工作状态同步约定（AI 必读）

用户在多台电脑上交替开发，git 仓库是唯一的工作记忆总线，`doc/ops/工作状态.md` 是状态快照。AI 助手必须执行以下仪式：

1. **开工**（新会话第一个开发任务前，或用户说「开工」）：
   - 提醒/帮用户 `git pull` 同步最新代码；
   - 读 `doc/ops/工作状态.md`，按其中「待办事项」与「当前状态」恢复上下文，不要重新询问已记录的信息。
2. **收工**（用户说「收工」/「同步状态」，或阶段性任务完成时主动建议）：
   - 更新 `doc/ops/工作状态.md`：当前进度、待办增删、新踩的坑、未完成的半成品说明（含涉及文件）；
   - 提交并推送全部工作（半成品也要推，宁可脏提交不可留在本地）；无法推送时明确告知用户手动 push。
3. **状态文件写法**：只记「下次接手需要知道的事」，不写流水账；密钥绝不入内（.env 变更只写「已变更，需手动同步」）。
4. **冲突预防**：两边不同时开工；开工前先 pull，收工必 push，就不会有分叉。

