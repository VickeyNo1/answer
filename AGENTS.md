# AGENTS.md

> 本文件是 **AI 编码助手的唯一入口文档**。开始任何任务前先读本文件，再按需跳转到 `doc/` 下的详细文档。
> 项目：会计答疑智能体（大模型对接外部知识库检索服务的会计专业 AI 答疑系统）
> 文档基线版本：v4.1（答题链路重构） ｜ 维护约定见 [§9](#9-文档维护约定ai-必读)

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
| 跑 400 题基准评测（导出 Excel 交专家评分） | 本文件 [§5 批量评测](#5-常用命令) → 设计与实测发现见 `doc/plans/2026-09-07-答题链路重构.md` §11 |
| 遵守编码约定、避开已知坑 | 本文件 [§6 约定与注意事项](#6-编码约定与注意事项必读) |
| 查数据库表结构 | 本文件 [§7 数据库](#7-数据库表结构) |
| 查全部接口一览 | 本文件 [§8 接口一览](#8-接口一览43-个业务接口) → 明细见 `doc/接口文档.md` |
| 查接口请求/响应细节 | `doc/接口文档.md` |
| 查架构与开发规范 | **本文件 [§2](#2-项目概述)/[§4](#4-代码地图)/[§6](#6-编码约定与注意事项必读) 为现行权威**；`doc/开发文档.md` 停在 v3.0 已严重滞后（文件头有过时警示表），仅其开发环境/端口/部署拓扑部分仍可参考 |
| 查答题链路（意图分流/三档命中）设计 | `doc/plans/2026-09-07-答题链路重构.md` |
| 查部署与运维 | `doc/ops/部署文档.md` |
| 恢复上次工作进度（跨设备/新会话） | `doc/ops/工作状态.md` → 约定见本文件 [§10](#10-跨设备工作状态同步约定ai-必读) |

---

## 2. 项目概述

面向会计专业学生的 AI 智能答疑系统，前后端分离：

- **后端**（`backend/`，端口 8000）：FastAPI，提供认证、对话（意图分流 + 流式）、答案反馈、管理后台（含全局设置/权益/检索报表）、大模型管理、科目列表接口。
- **前端**（`frontend/`，端口 3000）：Next.js App Router，学生对话页 + 管理员后台。
- **核心链路（v4.1 答题链路重构）**：学生提问（文字或图片）→ 前置校验（每日配额 → 单人串行 → 并发闸门+有限排队，任一不过 429）→ 带图片时先视觉 OCR 转录题目 → **意图三分类**（`app/chat/intent.py`，纯规则不调 LLM）→ 按意图分流：
  - **solve（问题目）**：绕过 Function Calling，后端**确定性**执行检索阶梯（`app/chat/solver.py::run_solve`）——先查题库 `questions`，有结果则用 LLM 二次校验是否原题，据此定档 **exact（原题命中）/ similar（相似题）/ none（无匹配）**，下发 `match` 事件；**三档都必须给出完整解答**，只在依据强度与答案末尾的不确定性标注上有区别。
  - **practice（要练习题）**：检索题库并**原样呈现**，默认剪裁答案（`run_practice`）。
  - **consult（概念性问题）**：维持原路径——大模型带 `search_cpa_knowledge` 工具流式生成，由模型自主决定是否检索。
  - 三分流汇合后：拼接检索结果作一轮流式回答（SSE，含 `kb_refs` 引用卡片、`suggestions` 追问建议）→ 落库知识点编号（`knowledge_point_ids`）并记录用量费用。检索调用一律写 `kb_search_logs`，`subject` 由后端注入。
- **学生记忆（v4.0 M3）**：三层记忆——错题本（纯程序，交卷判分时自动入本）+ 薄弱点（实时 SQL 聚合，不落快照）+ 学习风格画像（LLM 覆盖式总结，每 `profile_update_interval` 轮触发）。记忆注入块 ≤300 token 拼入 system prompt。开关「控用不控记」：关时不注入/不总结，但数据照常积累。

两大要点（v3.0）：
1. **知识库对接**：本地 ChromaDB RAG 全部移除，改为对接机器A 外部知识库检索服务；检索失败自动降级为大模型直答（不报错）。~~大模型通过 Function Calling 自主决定是否检索~~ → **v4.1 起仅 consult 意图如此**，solve/practice 由后端确定性检索（见 §6）。
2. **科目体系**：本地科目 CRUD 移除，科目枚举由知识库侧维护（当前仅 `cpa_acc` = CPA 会计 online），后端硬编码注册表并通过 `GET /api/subjects` 只暴露 online 项。

v4.0 M1 试点底座新增要点：
3. **对话限流**：每日配额（users 覆盖值 ?? 全局默认）+ 单人串行 + 全局并发闸门与有限排队（线程级方案，见 `app/chat/concurrency.py`），三种情形均返回 429（文案区分）。
4. **可观测与反馈**：检索日志 `kb_search_logs`（六态状态）+ 答案反馈 `feedbacks`（点赞/点踩 UPSERT）+ 管理端报表（反馈明细/检索质量/高频知识点）。
5. **全局设置与权益**：`app_settings` K-V 表 + 内存缓存（`app/settings_store.py`）；单人权益覆盖值存 users 新增两列，生效值计算见 `app/admin/entitlements.py`。

v4.1 答题链路重构新增要点（设计说明见 `doc/plans/2026-09-07-答题链路重构.md`）：
6. **意图三分类**：solve / practice / consult，纯规则判定（`app/chat/intent.py`），**不调 LLM**；带图片直通 solve。两个方向的误判都是优雅降级（solve→consult 退回现状行为；consult→solve 多一次检索但答案依然正确），故规则足矣。
7. **solve 三档命中判定**：exact / similar / none。**不用检索分数阈值**——`score` 是重排后的排序分，不同请求间不可比（`doc/知识库对接文档.md`）；改用 LLM 二次校验（`solver.verify_same_question`）。**校验失败一律归 similar，绝不归 exact**：误报「找到原题」会让学生拿着错答案去考试。修复轮追加**相关性下限**（同一次校验顺带输出 `relevant_indexes`）：检索服务没有相关性下限，乱码 query 也返回满 top_k 条，此前 none 档实际不可达、跨章节无关题还会被当范例注入。
8. **题库答案默认剪裁**：`format_results(include_answer=False)`，需要答案的调用点必须显式传 `True`（safe-by-default：意图误判也不会漏答案）。管理端可用 `practice_reveal_answer` 在线回退，无需发版。
9. **分用途配模型**：对话/判卷/画像/校验/OCR/**评测** 六个用途的敏感度与调用量完全不同，不再共用一个模型（`llm/store.py::get_model_for`，env 覆盖，空串=跟随后台激活模型）。
10. **v4.1 修复轮（2026-09-08，端到端实测后修的 4 个 P0 + 4 个 P1）**：学生可见的三处——答案里的 **LaTeX 现在能渲染**（`remark-math` + `rehype-katex`）；**内部标头不再泄漏**进答案正文（`【题目2｜ACC-2025-Q-5.10｜…】`）；consult **没检索知识库却写了教材出处**时末尾会标「出处未经教材核对」。运维可见的四处——费用不再静默记 0（视觉模型补单价行 + 启动自检 + 删激活模型 409）、删学生全量级联。逐条见 `doc/plans/2026-09-07-答题链路重构.md` §12，契约见本文件 §6。
11. **批量评测（400 题基准题库，v4.1）**：`POST /api/admin/eval/answer`（🔒）+ `backend/scripts/batch_eval.py`，只答题不判卷，导出 Excel（金标准答案/关键得分点/依据三列并排 + 空白「专家评分」「专家备注」）交专家线下评分。**刻意不复用 `POST /api/chat`**：不落库对话、不扣配额、不占并发槽、不写 `kb_search_logs`（800 行会冲掉检索质量报表），唯一副作用是 `usage_logs` 记 `task_type='eval'` 且 `user_id` 为 NULL。⚠️ **基准治理**：题库自带「锁定后禁止用于 Prompt、RAG、工作流或模型调参」条款——结果只进效果报告；若据它调了参，必须重跑一轮新基准，否则数字失去可比性。命令见 §5，设计见 `doc/plans/2026-09-07-答题链路重构.md` §11。

---

## 3. 技术栈（以代码实际版本为准）

| 层级 | 技术 | 版本 | 位置 |
|------|------|------|------|
| 前端框架 | Next.js (App Router) | 16.2.10 | `frontend/package.json` |
| UI 库 | React | 19.2.4 | 同上 |
| 样式 | Tailwind CSS | v4 | 同上 |
| Markdown 渲染 | react-markdown + remark-gfm + **remark-math + rehype-katex（katex 样式在 `app/layout.tsx` 导入）** | — | 对话回答渲染（`components/ChatWindow.tsx::AnswerMarkdown`）。⚠️ `rehype-highlight` 只躺在 `package.json`，`src/` 里零引用，别再当它在用 |
| 后端框架 | FastAPI | 0.115.* | `backend/requirements.txt` |
| ASGI 服务器 | uvicorn[standard] | 0.30.* | 同上 |
| 关系数据库 | MySQL 8.4（机器A，utf8mb4） | — | 连接配置见 `backend/.env` |
| MySQL 驱动 | PyMySQL（DictCursor） | 1.1.* | `app/database.py` |
| 知识库检索 | 外部检索服务 `POST /kb/search`（HTTP） | — | `app/kb/client.py`（httpx） |
| 大模型调用 | **openai SDK → 阿里百炼 OpenAI 兼容端点**（通义千问 + DeepSeek 统一接入） | `openai>=1.0.0` | `app/llm/client.py::create_client()`，密钥 `DASHSCOPE_API_KEY` |
| 分用途模型 | `CHAT_MODEL`（对话回退）/ `VISION_MODEL`（OCR）/ `JUDGE_MODEL`（判卷）/ `PROFILE_MODEL`（画像）/ `VERIFY_MODEL`（题目同一性校验）/ **`EVAL_MODEL`（批量评测，v4.1）** | — | `app/config.py`；`CHAT_MODEL` 默认 `qwen3.7-flash`，仅当 `model_configs` 查不到激活模型时作回退（`llm/store.py::get_active_model`）；后四者**空串 = 跟随后台激活模型**，见 `llm/store.py::get_model_for` |
| 认证 | JWT（python-jose）+ bcrypt（passlib） | — | `app/auth/` |
| Excel 解析 | openpyxl（学生批量导入） | 3.1.* | `app/admin/` |
| Python 环境 | uv + Python 3.11+ | — | `backend/.venv` |

> ⚠️ **所有 LLM 调用一律走 `create_client()`（OpenAI 兼容端点），禁止引入 `dashscope.Generation.call`。** 迁移原因：qwen3.5+ 系列在 DashScope 原生 SDK 里要用 `MultiModalConversation`，端点按模型分叉；兼容端点一个 `base_url` 通吃。DeepSeek 亦走百炼统一接入，复用 `DASHSCOPE_API_KEY`，无需独立 SDK 或分支。**v4.1 消融实验起 `create_client(model_name)` 按模型名路由厂商**：`glm` 开头 → 智谱自有端点（`ZHIPU_API_KEY`/`ZHIPU_BASE_URL`，用户自购资源包），其余 → 百炼。
> `dashscope` 依赖已于 2026-09-08 从 `pyproject.toml` / `requirements.txt` / `uv.lock` 移除（全仓零 import）。

---

## 4. 代码地图

### 后端 `backend/app/`

| 路径 | 职责 | 关键点 |
|------|------|--------|
| `main.py` | FastAPI 应用入口，注册 11 个 router，CORS，`/api/health`（三字段） | 启动时 `init_db()` 建库建表 + 加载设置缓存 + 初始化并发闸门 + `_warn_unpriced_models()` 自检（v4.1 修复轮）：把**当前配置会调用的模型名**（`get_active_model()` + `CHAT_MODEL` + `VISION_MODEL` + 四个分用途 env，空串跳过）拿去比对 `model_configs`，缺单价行的打 WARNING——这类模型 tokens 照记但 `cost` 恒为 0，开销在报表里完全不可见。⚠️ **它是前向的，不扫 `usage_logs` 历史**，所以查不出已经发生的少报（历史欠账见 `doc/ops/工作状态.md`） |
| `config.py` | `Settings`（pydantic-settings），读 `.env` | `MYSQL_*` / `KB_*` 配置；`VISION_MODEL`（OCR 视觉模型）+ `JUDGE_MODEL`/`PROFILE_MODEL`/`VERIFY_MODEL`/`EVAL_MODEL`（分用途覆盖，空串=跟随激活模型，v4.1）；`get_settings()` 带 `lru_cache` |
| `database.py` | MySQL 建库建表（PyMySQL + DictCursor） | `DB` 包装类保留 `db.execute()` 习惯；`get_db()`（Depends 生成器）vs `get_db_ctx()`（脚本上下文管理器）见 §6；存量库幂等补 users 新列 |
| `models.py` | 全部 Pydantic 请求/响应模型 | 新增接口先在此定义 schema |
| `settings_store.py` | `app_settings` 全局设置：内存缓存 + 类型转换（v4.0） | 启动时全量加载，PUT 更新后刷新缓存；值统一字符串落库、读时按键转 int/bool；`BOOL_KEYS` 内的键按 bool 输出（v4.1 增 `practice_reveal_answer`） |
| `auth/` | 登录、JWT、依赖、自助改密码 | `deps.py`：`get_current_user`、`require_admin`；`router.py` 另含 `me_router`（`PUT /api/me/password`，v4.0） |
| `chat/` | 对话主流程 | `router.py`（SSE + 意图分流 + 对话 CRUD + `POST /api/feedback`）、**`intent.py`（意图三分类纯规则，v4.1）**、**`solver.py`（solve 三档流水线 `run_solve` + practice 出题 `run_practice` + LLM 二次校验 `verify_same_question`，v4.1；校验一次调用同时输出 `same/index`（定档）与 `relevant_indexes`（相关性下限，v4.1 修复轮）；similar/none 档补查 standards 准则原文库，2026-09-16）**、`qwen_service.py`（`extract_question_text` 图片 OCR、`build_messages`、`stream_chat` consult 路径 Function Calling、`stream_answer` 三处共用的流式生成+追问建议解析；v4.1 修复轮：`SYSTEM_PROMPT` 加「出处纪律」硬约束 + `claims_source`/`UNVERIFIED_SUFFIX` 挡住「不检索却编造教材出处」）、`memory.py`（多轮历史）、`concurrency.py`（线程级并发闸门/单人串行/有限排队，v4.0） |
| `kb/` | 知识库对接（v3.0） | `client.py`（`POST /kb/search`，超时/5001 重试1次后降级；v4.0 新增：每次检索写 `kb_search_logs`、`probe()` 供健康检查探测）、`prompt.py`（`SEARCH_TOOL` schema + 结果拼接 + `collect_kp_ids`；v4.1 新增：`content_type` 中文标注与 `prefer="solve"` 定向排序、`include_answer` 默认剪裁、`sub_question_text` 兼容字符串/对象两种子问；v4.1 修复轮新增 `MARKER_NOTICE` + `append_marker_notice()`——禁止模型把「【题目1｜…】」内部标头抄进答案）、`subjects.py`（科目注册表 + `GET /api/subjects`） |
| `admin/` | 管理后台 | `router.py`（学生增删改查/批量、统计；v4.0 新增：全局设置 GET/PUT、单人权益、反馈明细、检索报表 kb/stats + kb/hot-kps；v4.1 修复轮：`delete_student` 由只删 3 张表改为**全量级联 8 张关联表 + users 本身**，`usage_logs` 保留但置空归属，见 §6）、**`eval.py`（批量评测单题作答端点 `POST /api/admin/eval/answer`，v4.1；独立成模块而非塞进 `router.py`，因为它要 import 8 个 chat 域符号）**、`stats.py`（聚合统计）、`entitlements.py`（权益生效值：users 覆盖值 ?? 全局默认，v4.0） |
| `llm/` | 大模型管理 | **`client.py`（`create_client()` 百炼 OpenAI 兼容端点工厂，全项目唯一 LLM 入口）**、`router.py`（模型 CRUD/activate/usage；v4.1 修复轮：删除 `is_active=1` 的模型返回 **409**，否则全表无激活模型、系统静默回退到 `.env` 幻影模型名且费用恒记 0）、`store.py`（模型与用量数据访问 + 费用计算 + `record_usage(task_type=...)`；v4.1 新增 `get_model_for(task_type)` 分用途选模型、`find_unpriced_models()` 供启动自检） |
| `exam/` | 考试系统（v4.0 M2） | `router.py`（学生端 6 接口 + 管理端 3 接口）、`store.py`（组卷/暂存/交卷/掌握度/管理端数据访问）、`judger.py`（客观判分 + 主观题 LLM 异步判卷 `ThreadPoolExecutor`） |
| `profile/` | 学生记忆（v4.0 M3） | `router.py`（学生端 3 接口 + 管理端 2 接口）、`store.py`（错题本 CRUD + 画像 + 薄弱点实时聚合 + 记忆注入块构建）、`summarizer.py`（LLM 画像总结，复用 `judger._bg_executor` 线程池） |

### 后端 `backend/scripts/`（运维与评测脚本，不在 app 包内）

| 路径 | 职责 | 关键点 |
|------|------|--------|
| `batch_eval.py` | 批量评测跑批（v4.1）：读基准题库 xlsx → 逐题调 `POST /api/admin/eval/answer` → 导出 Excel 交专家线下评分 | 打 `http://localhost:8000` 而非走 Nginx（`proxy_read_timeout` 60s 会掐断长答案）；`--limit`/`--ids`/`--concurrency`(默认3)/`--resume`（JSONL checkpoint，每题落盘即 flush）；**只发题干一个内容字段**，金标准/关键得分点/依据只进导出文件，绝不进请求体；输出目录 `backend/eval_out/` 已 gitignore |
| `add_table_comments.py` | 存量库补表/字段中文注释 | 幂等；⚠️ **改字段注释要三处同改**（`TABLES_SQL` + `EXTRA_COLUMNS` + 本脚本），且存量库只有重跑本脚本才会生效，见 §7 |

### 前端 `frontend/src/`

| 路径 | 职责 |
|------|------|
| `app/page.tsx` | 学生对话主页（会话列表、流式对话、科目选择；v4.0 M2 新增 `?ask=&subject=` 预填 + 「去考试」入口） |
| `app/exam/page.tsx` | 考试页（v4.0 M2）：三步状态机——组卷→答题→成绩单（grading 5s 轮询、掌握度条、薄弱点「问 AI」、主观题异议） |
| `app/wrong-questions/page.tsx` | 错题本页（v4.0 M3）：错题列表（筛选科目/状态 + 分页）+ 重练弹窗（客观题单选/主观题文本）+ 知识点「问 AI」跳转 |
| `app/login/page.tsx` | 登录页 |
| `app/admin/page.tsx` | 管理后台，Tab 容器（统计/学生/大模型/考试/运营报表） |
| `components/` | `AuthGuard`、`ChatInput`（含 `initialValue` 预填）、`ChatWindow`（含「正在检索知识库…」提示；v4.1 修复轮：AI 答案统一走内部组件 `AnswerMarkdown` = remark-gfm + remark-math + rehype-katex，`throwOnError:false` 必留——KaTeX 渲染期抛错会让整条气泡白屏，而流式过程中 `$` 尚未闭合是常态）、`ConversationList`（删除按钮**需连点两次**确认） |
| `components/admin/` | `StatsTab`、`StudentTab`、`ModelTab`（v4.1 修复轮：激活模型不渲染删除按钮）、`ExamTab`（筛选列表→行展开详情→行内改分） |
| `lib/api.ts` | fetch 封装：`apiGet/apiPost/apiPut/apiDelete/apiUpload` |
| `lib/auth.ts` | token 本地存储与读取 |
| `lib/markdown.ts` | v4.1 修复轮新增：`normalizeMathDelimiters()` 把 `\(…\)`/`\[…\]` 归一成 `$…$`/`$$…$$`（remark-math 只认后者，线上实测两套分隔符混用）。**成对匹配再替换**，落单的 `\(` 保持原样，否则它会和正文里本来就有的美元符号配对、把中间整段中文吞进公式模式；三反引号代码块整体跳过 |
| `lib/sse.ts` | SSE 对话客户端 `sendChatMessage(conversationId, message, subject, callbacks)`（处理 `kb_search`/`kp_ids`/`queue`/`kb_refs`/`suggestions`/`ocr` 事件）。⚠️ `switch` **无 default 分支**，未列举的事件静默忽略——v4.1 的 `match` 事件即刻意不接：solve 命中档位通过答案末尾标注文案随正文渲染，故 `sse.ts` 零改动。要加徽标时在此处补 `case "match"` |
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
# ⚠️ 少了 --reload 就不会热加载：改完代码去浏览器做实测，跑的其实是旧代码（踩过）
uv run uvicorn app.main:app --reload

# 运行测试（测试库 answer_test 自动建表/清理）
# ⚠️ MySQL 不可达时**不是全部 skip**：纯函数/生成器类用例（intent、solver、verify、
#    kb prompt、model routing、eval 端点等）不依赖 DB 仍会跑，只有 DB 门控用例 skip。
#    因此「passed 不为 0」**不能**推断数据库已连通——必须看 skipped 数。
#    当前共收集 631 例；skipped 高达 300+ 即说明 MySQL 没连上，此时全部 router 集成
#    测试、settings API、OCR 集成、SSE 护栏用例都没真正执行过。
#    连通后基线（2026-09-09 实测）：569 passed / 62 skipped，62 全为 tests/e2e
#    （后端未启动自动跳过），即非 e2e 用例全绿。
#    偶发 flake：test_wrong_question_auto.py 的 fixture setup 报 1 error（单独跑与重跑
#    均全过），疑为上一个文件残留的后台判卷线程占着锁、DELETE 等待超时，不是回归。
uv run pytest -q
```

### 批量评测（在 `backend/` 目录，v4.1）

```powershell
# 先起后端（脚本打 localhost:8000，见下方注意），再跑批
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 全量跑基准题库 → 导出 Excel 交专家线下评分
# 密码走 EVAL_PASSWORD 环境变量（不传则 getpass 交互输入，别写进命令行历史）
$env:EVAL_PASSWORD="..."; uv run python scripts/batch_eval.py --xlsx "题库.xlsx"

# 常用开关：先小样冒烟，再全量
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --limit 8
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --ids T001,T057,T151
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --intent auto   # 对照组
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --resume        # 断点续跑

# 消融实验（v4.1，2026-09-16，专家要求 A/B/C × 3 模型；A=bare / B=prompt_only / C=full）
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --mode bare            # A 组，跟随 EVAL_MODEL
uv run python scripts/batch_eval.py --xlsx "题库.xlsx" --mode prompt_only --model glm-5.2
# ⚠️ --model 钉死的模型必须在 model_configs 有行，否则端点 400（防费用静默记 0）；
#    glm-* 自动走智谱端点（ZHIPU_API_KEY），其余走百炼。各组输出按 {mode}_{model} 分文件
```

> ⚠️ **三条实测约束**：① 必须打 `localhost:8000`，走 Nginx 会被 `proxy_read_timeout` 60s 掐断长答案；② `.env` 未设 `MYSQL_DB` 时写的是**生产库 `answer`**——400 题会留下约 800 行 `usage_logs`（每题一次 `eval` + 一次 `verify`，`user_id` 均为 NULL），对话表与 `kb_search_logs` 零写入；③ 实测 8 题 / 并发 3 用时 42 秒、0.044 元，400 题外推约 **35 分钟 / 2.2 元**。消融 8 组矩阵（A×3 + B×3 + C×2，C-flash 复用既有结果）= 3200 次生成，前置条件见 `doc/ops/工作状态.md`。
> ⚠️ **基准题库与评测输出都不得入库**：`backend/eval_out/` 已 gitignore，xlsx 原件放在仓库外。题库自带金标准答案，一旦提交等于把答案泄进版本历史。

### 前端（在 `frontend/` 目录）

```powershell
npm install            # 首次
npm run dev            # http://localhost:3000
npx tsc --noEmit       # 类型检查
```

- 默认管理员账号：`admin` / `admin123`（由 `seed.py` 写入）。
- 测试库 `answer_test`（`tests/conftest.py` 自动建库建表 + teardown DROP）；机器A MySQL 不可达时**仅 DB 门控用例 skip**，纯函数用例照跑（详见上方 `pytest` 注释）。
- ⚠️ **E2E 测试（`tests/e2e/`）打的是活的后端 :8000，写的是生产库 `answer`，不是 `answer_test`**：后端未启动时自动 skip（当前 62 例）。所以**跑全量 `pytest` 前必须先停掉本地后端**——2026-09-08 曾在后端起着的时候跑了全量，e2e 真的往生产库建了两个 `e2e_` 学生（id=34/36），事后专门写脚本清理。想跑 e2e 就单独跑 `uv run pytest tests/e2e -q`，并接受它污染生产库。

---

## 6. 编码约定与注意事项（必读）

- **所有 LLM 调用一律走 `app/llm/client.py::create_client()`（v4.1）**：OpenAI 兼容端点，**禁止引入 `dashscope.Generation.call` / `MultiModalConversation`**。新加 LLM 调用点时先 `from app.llm.client import create_client`，模型名从 `llm_store.get_active_model()` 或 `get_model_for(task_type)` 取；**知道模型名时传 `create_client(model_name)`**（glm 开头路由智谱自有端点，其余走百炼，2026-09-16 消融实验新增）。
- **`extra_body` 关思考参数已收口到 `completion_extra(model_name)`（2026-09-16）**：按厂商分——百炼 `{"enable_thinking": False}`、智谱 GLM `{"thinking": {"type": "disabled"}}`。`qwen_service.stream_answer`/`stream_chat` 与 `solver.verify_same_question` 已用它按模型自动选；仍硬编码 `enable_thinking` 的 3 处（`qwen_service.extract_question_text` OCR、`exam/judger.py`、`profile/summarizer.py`）只可能调百炼模型，暂不改。⚠️ 智谱 GLM-5.3 系列**强制思考**，传 disabled 会直接请求失败（且思维链按输出 token 计费）；智谱只能用 GLM-5.2 及以下。
- **题库 `answer`/`explanation` 默认剪裁（v4.1）**：`format_results(data, include_answer=False)`，需要答案的调用点**必须显式传 `True`**。当前 4 个调用点：**无条件 `True`** 仅 `run_solve` 的 exact/similar 两档（就是学生问的那道题／作范例的相似题）；`run_practice` 与 `qwen_service.stream_chat`（consult 老路径）传的是管理端开关 `practice_reveal_answer` 的值（**默认 `False`**）。契约见 `doc/知识库对接文档.md`「先答题后判卷场景务必剪裁」。剪裁时附「（参考答案与解析已省略，请先自行作答）」，且**子问对象自带的答案也会被剪**（`sub_question_text`），别从后门漏。
- **意图分流与检索 query 取法（v4.1）**：`classify_intent` 判定顺序即优先级（图片 → 强 solve 标记 → practice 标记 → 弱 solve 证据 → consult），**不可调换**——「这道练习题怎么做」必须判 solve。solve/practice 的检索 query 取 `ocr_text or req.message`，**不取组合后的 `effective_message`**（「请解答\n\n【图片识别内容】」前缀会污染向量检索），截断 1000 字符。意图与档位**本轮不落库**（`messages` 无对应列），档位靠答案末尾标注文案随 `content` 落库。
- **solve 三档判定契约（v4.1 修复轮）**：`verify_same_question` 一次调用同时产出两组信号——`same`/`index` 定 exact，`relevant_indexes` 当**相关性下限**（检索服务本身没有下限，乱码 query 也返回满 top_k 条，而 `score` 只是重排后的排序分、跨请求不可比，所以只能用模型判）。⚠️ **`relevant_indexes` 的 `None` 与 `[]` 是两种信号，别合并**：`None` = 没拿到判断（字段缺失/不是数组/序号全部越界/调用抛异常）→ 沿用旧的保守行为，全量候选注入 similar 档；`[]` = 模型明确说没有一道相关 → 不注入噪声，走 none 档独立推导。合并的后果是二选一都错：要么 none 档永不可达，要么每次校验超时都白白丢掉可用的相似题参考。因此 **none 档有两个触发条件**（题库无结果 / 候选被判定全不相关）。`same=false` 一律归 similar，**校验失败绝不归 exact**——误报「找到原题」会让学生拿着错答案去考试。
- **内部标头不得外泄（v4.1 修复轮）**：`kb/prompt.py` 给每条检索资料打的标头行（`【题目1｜ACC-2025-Q-5.10｜multiple_choice｜知识点 …】`、`【资料2｜例题｜知识点 …｜第21章 租赁 · 第1节｜…】`）是给模型定位用的内部索引，线上实测被模型原样抄进了给学生的答案。修法是在拼好的资料**末尾**追加 `MARKER_NOTICE`（`append_marker_notice()`），交代标头不外泄、要用自然语言写章节与知识点编号。两条约定别破坏：① **必须紧跟资料之后**，因为两条作答路径的资料位置不同（solve/practice 在 system prompt 中段，consult 在独立的 `tool` 消息里），只有紧跟其后「上方资料」的指代才都成立；② **不要塞进 `format_results`**，`run_solve` 的 similar/none 档会把题库与教材两段资料拼在一起（等于同一份 prompt 说两遍），且空结果时它返回 `FALLBACK_TEXT`，那时根本没有标头行可交代。
- **数据库连接两种用法别混用**：接口内用 `Depends(get_db)`（生成器）；脚本/非请求上下文用 `with get_db_ctx() as db`（上下文管理器）。
- **SQL 占位符统一用 `%s`**（PyMySQL 风格），**不要用 `?`**；日期用 MySQL 函数（如 `CURDATE()`，不要用 SQLite 的 `DATE('now')`）。
- **PyMySQL 返回类型陷阱**：`fetchall()` 结果需 `list()` 化再传给 Pydantic；`SUM()` 返回 `Decimal`（用 `int()`/`float()` 包裹）；`DATE` 列返回 `date`、`created_at` 返回 `datetime`（作为字符串字段时需 `str()`）。
- **FastAPI 路由顺序**：静态路径要声明在动态路径之前。例如 `/api/admin/models/usage` 必须在 `/{model_id}` 之前，否则会被 `int` 参数路由拦截。
- **Function Calling subject 注入**：`search_cpa_knowledge` tool schema 只暴露 `query`/`collection`/`top_k`，**`subject` 由后端从会话上下文注入**（模型不可决定），避免模型乱填枚举。
- **`log_enabled` 是评测专用开关，新增检索调用点必须继续透传（v4.1）**：`kb_client.search(..., log_enabled=False)` **只抑制 `kb_search_logs` 落库，日志照打**（开关卡在 `_log_search` 的 INSERT 之前而非函数首行——排查批量跑要看日志，要抑制的只是报表数据）。动机：批量评测 400 题 × 2 次检索 = 800 行，灌进去会把给使用方看的检索质量报表彻底冲掉。目前透传链是 `admin/eval.py` → `run_solve` / `run_practice` / `stream_chat` → `kb_client.search`（共 7 个 search 调用点：solve 3、practice 2、consult 1，另 `probe()` 不写日志）。**在这三处链路里新加检索调用时，别忘了把 `log_enabled` 一起传下去**，漏传不会报错，只会静默污染报表。普通对话路径一律用默认值 `True`。
- **KB 检索降级策略**：`app/kb/client.py` 调 `POST /kb/search`，超时或 `5001` 重试 1 次后仍失败返回 `None`，链路**降级为大模型直答（不报错）**，降级话术分档附在答案尾部；每次检索调用均写 `kb_search_logs`（六态状态，写失败不影响主链路，v4.0）；`knowledge_point_ids` 必须落库 `messages.knowledge_point_ids`（JSON 数组）。**v4.1**：solve 路径题库、教材、standards 三次检索全部返回 `None` 时改用 `DEGRADED_SUFFIX`，**不与档位标注叠加**；降级下依然必须给出完整解答（不报错、不空答）。
- **standards 准则原文库接入（2026-09-16）**：知识库侧已上线 `standards` collection（54 份准则/解释原文，含 2026 年解释第19/20号）。三处约定：① `SEARCH_TOOL` 的 collection enum 含 `standards`（consult 由模型自主选用）；② `run_solve` 的 **similar/none 档各补查一次 standards top_k=3**（query 用原始提问——题面常直接点名新解释，教材定向 query 反而丢掉该信号），exact 档保持快路径不查；③ `format_results` 对 standards 走独立的 `_format_standards` 渲染（其 chapter/section 恒空串、kp 恒空、content_type 是 article/notice_item，落 `_format_textbook` 会渲染出空标头），资料头部带「条文原文与既有记忆冲突时以原文为准」——这是针对实测 5 道 0 分题（模型旧口径 vs 2026 新解释）的定向指令。standards 检索失败（None）静默跳过，不单独算降级（降级 = 三库全空）。
- **「没资料」三档标注不可合并（v4.1 修复轮）**：`qwen_service` 现有三种末尾标注，对应三种**运维上要分开归因**的情形——`DEGRADED_SUFFIX`（查了，检索服务挂了）/ `EMPTY_SUFFIX`（查了，没命中）/ `UNVERIFIED_SUFFIX`（**压根没查**：consult 由模型自主决定是否调工具，实测它会跳过检索直接答、还顺手编出「《XX教材》第X章」）。第三档由 `claims_source()` 判定：直答正文出现教材/准则书名号、章号、知识点编号或「根据教材」一类措辞才贴标注，寒暄与纯计算讲解不贴（否则每条闲聊都多一句废话）。`SYSTEM_PROMPT` 的「出处纪律」是提示词侧的同一件事（只能逐字引用检索结果里的标题/章节/知识点编号；准则名可提但不得编条文号；没检索就不得声称教材依据），但**提示词不是护栏**，确定性标注才是。
- **对话限流三态 429（v4.0）**：`POST /api/chat` 前置校验按序执行——每日配额（生效值见 `app/admin/entitlements.py`）→ 单人串行 → 并发闸门+有限排队（`app/chat/concurrency.py`，线程级方案勿改 asyncio），三种情形文案区分；并发资源必须在 finally 中配对归还。
- **v4.0 新增路由用 `Depends(get_db)`**：存量 chat/admin 路由内的 `with get_db_ctx()` 属 P1 技术债择机偿还；仅后台任务（无请求上下文）才用 `get_db_ctx()`。
- **科目枚举不得自造**：枚举字典由知识库侧维护，见 `app/kb/subjects.py::SUBJECT_REGISTRY`（只增不改，与 `doc/知识库科目枚举约定.md` 一致）；请求 `subject` 非法时回退 `DEFAULT_SUBJECT`（`cpa_acc`）。
- **用量采集（v4.1 修正）**：走百炼 OpenAI 兼容端点后读 `usage.prompt_tokens` / `usage.completion_tokens`（**不再是 dashscope 的 `input_tokens`/`output_tokens`**）；流式调用必须传 `stream_options={"include_usage": True}`——实测 deepseek-v4-pro 等模型默认流式不回传 usage（flash/glm 会），漏传则 tokens 记 0 且 eval 行因「0 token 不记账」直接缺失（2026-09-16 消融冒烟发现，已在 `stream_answer`/`stream_chat` 两处补上）；无 usage 时记 0。费用 = `tokens/1000 × 单价`，单价由管理员维护（不自动同步官方价）。`record_usage(..., task_type=...)` 按用途分账：`chat`/`exam`/`profile`/`ocr`/`verify`/**`eval`（批量评测，v4.1）**；**verify 的用量不计入对话累计**（校验模型可能与作答模型不同，混算费用会错）。**eval 行的 `user_id` 传 NULL**（该列可空、无外键），既不把开销挂到任何学生头上，也便于事后按 `user_id IS NULL AND task_type='eval'` 一次查出；注意每道评测题会同时产生一条 `eval` 与一条 `verify`，400 题 ≈ 800 行。
- **费用静默记 0 的三条来路（v4.1 修复轮，都已堵）**：`compute_cost()` 在 `model_configs` 查不到模型行时**回退单价 0.0**（不报错、不告警），tokens 照记但 `cost` 恒为 0，这笔开销在用量报表里彻底不可见。三条来路：① **视觉模型没有单价行**——OCR 用的 `qwen-vl-max`/`qwen-vl-plus` 生产库里查无此模型，已由 `seed.py` 幂等补齐；② **删掉了唯一激活模型**——`DELETE /api/admin/models/{id}` 现对 `is_active=1` 返回 **409**「请先切换到其他模型」（前端 `ModelTab` 对激活行隐藏删除按钮，e2e 用例删完还原激活态）；③ **`.env` 里写着幻影模型名**——`CHAT_MODEL` 曾长期指着表里不存在的 `qwen3.7-max-2026-05-20`，全表无激活行时就静默回退到它。改 `.env` 模型名要同步确认表里有对应行。启动自检 `main.py::_warn_unpriced_models()` 只比对**当前配置会调用的模型名**（`get_active_model()` + `CHAT_MODEL` + `VISION_MODEL` + 四个分用途 env，空串跳过）与 `model_configs`，看到 WARNING 就去补。⚠️ **它不扫 `usage_logs` 历史**——已经按单价 0.0 写进去的行不会因为补了单价行或重启而自动修正，`cost` 是写入时算好落库的；要追回只能按 `prompt_tokens`/`completion_tokens` 手工回填。
- **`delete_student` 必须全量级联（v4.1 修复轮）**：删学生时**硬删 8 张关联表 + `users` 本身**——`messages`、`conversations`、`exam_answers`、`exams`、`feedbacks`、`wrong_questions`、`student_profiles`、`kb_search_logs`，**先删从表再删主表**（`messages`←`conversations`、`exam_answers`←`exams`）。`usage_logs` 是唯一例外：**只把 `user_id`/`conversation_id` 置 NULL，行保留**——它只有 tokens/费用/模型名、没有提问内容，删掉会让「累计费用」少报已经真实发生的开销。前 8 张则相反，存的是学生学习内容与提问痕迹（`kb_search_logs.query` 就是提问原文，属隐私），必须清干净。旧实现只删 `messages`/`conversations`/`users` 三张，线上留下了 44 条孤儿 `usage_logs`、26 条孤儿 `kb_search_logs`、1 条孤儿 `student_profiles`（已于 2026-09-09 清理完毕，见 `doc/ops/工作状态.md`）。**新增任何带 `user_id` 的表，都要同步加进这个级联列表**。
  ⚠️ **姊妹接口 `delete_conversation` 有完全同类的缺陷，截至 2026-09-09 仍未修**：`chat/router.py` 删会话只删 `messages` + `conversations`，留下 `usage_logs.conversation_id`、`kb_search_logs.conversation_id`、`feedbacks.message_id` 三类悬空引用，学生每删一次会话就累积几行。别以为「级联问题已经在 P0-B 修完了」。修之前要先定 `kb_search_logs` 的口径（硬删保隐私 vs 置空保报表），待决项见 `doc/ops/工作状态.md`。
- **测试打桩认准模块绑定（v4.1 踩过的坑）**：`solver.py` 与 `qwen_service.py` **各自** `from app.llm.client import create_client`，patch `qwen_service.create_client` 对 solve 路径**无效**，会真打百炼。反之 `kb_client` 两边都是 `from app.kb import client as kb_client`（同一模块对象），patch 一处即对两边生效。`admin/eval.py` 同理两面：`stream_chat` 是 `from ... import` 进来的**局部名**，必须 patch `app.admin.eval.stream_chat`；`solver` 是**模块对象**，patch `solver.run_solve` / `solver.run_practice` 即可。
- **桩函数写死签名 = 加参数就炸，且症状极具误导性（v4.1 踩过）**：`kb_client.search` 加 `log_enabled` 后，`tests/test_chat_sse.py` 里 `def fake_search(query, subject, collection, top_k, user_id, conversation_id)` 这种**逐参数写死、不带 `**kwargs`** 的桩直接 TypeError。更坑的是异常被 SSE 生成器吞掉，表面症状是「assistant 消息没落库」而不是报错栈。给检索/LLM 这类会演进签名的函数写桩时**一律带 `**kwargs`**；反过来说，写死签名的桩也有价值——它替你抓住了「生产代码改了契约」这件事。
- **新增/修改接口的落点**：schema → `app/models.py`；路由 → 对应模块 `router.py`；注册 → `app/main.py`；类型 → 前端 `types/index.ts`；文档 → `doc/接口文档.md` + 本文件 §8。
- **认证**：需登录接口带 `Authorization: Bearer <token>`；管理员接口用 `Depends(require_admin)`。
- **响应格式**：成功直接返回业务数据（无外层包裹）；无数据时返回 `{"message": "ok"}`；错误返回 `{"detail": "..."}`。

---

## 7. 数据库表结构

MySQL 8.4（机器A，InnoDB，utf8mb4），建表见 `app/database.py`（`init_db()` 启动时 `CREATE DATABASE IF NOT EXISTS` + 建 12 张表，建表 SQL 含表/字段中文注释；存量库幂等补 users 新列 + usage_logs.task_type 列）。存量库补注释用 `backend/scripts/add_table_comments.py`（幂等）。⚠️ **改字段注释要「三处同改」**：`database.py::TABLES_SQL`（CREATE TABLE）、`database.py::EXTRA_COLUMNS`（存量库 ADD COLUMN）、`scripts/add_table_comments.py`（MODIFY COLUMN）。且 **`EXTRA_COLUMNS` 只在列缺失时才执行**——列早就存在的生产库永远不会走到那条 ALTER，改它的注释等于没改，**必须重跑一次 `add_table_comments.py`** 才会落到线上（2026-09-09 给 `usage_logs.task_type` 加 `eval` 时发现的，当时还没重跑）。**无 `subjects` 表**（科目改为知识库侧枚举，见 §6）。

| 表 | 关键列 | 说明 |
|----|--------|------|
| `users` | `id, student_id(UNIQUE), password_hash, name, role('student'/'admin'), daily_question_limit(INT,可空), memory_enabled(TINYINT,可空), created_at` | 用户/学生；v4.0 新增两列为权益覆盖值，NULL=跟随全局默认（`app_settings`） |
| `conversations` | `id, user_id, title, subject(VARCHAR(32),可空), created_at` | 会话，`subject` 存科目枚举值（如 `cpa_acc`） |
| `messages` | `id, conversation_id, role, content, knowledge_point_ids(TEXT,可空), created_at` | 消息，`knowledge_point_ids` 存 KB 命中知识点编号 JSON 数组 |
| `model_configs` | `id, provider('ali'/'deepseek'), model_name(UNIQUE), display_name, price_in, price_out, enabled, is_active, created_at` | 模型配置，`is_active=1` 为当前模型。⚠️ `compute_cost()` 查不到模型时单价**回退 0.0**——任何会被调用的模型（含 v4.1 OCR 用的视觉模型 `qwen-vl-max`/`qwen-vl-plus`）都**必须在此表有记录**，否则 tokens 照记但 `cost` 恒为 0，这笔开销在用量报表里完全不可见。单价由管理员维护，不自动同步官方价 |
| `usage_logs` | `id, model_name, user_id(可空), conversation_id(可空), prompt_tokens, completion_tokens, total_tokens, cost, task_type(VARCHAR(16) DEFAULT 'chat'), created_at` | 用量与费用；v4.0 M2 新增 `task_type`，v4.1 取值扩为 **6 值**：`chat`（对话）/`exam`（判卷）/`profile`（画像总结）/`ocr`（图片识别）/`verify`（题目同一性校验）/**`eval`（批量评测）**。`eval` 行的 `user_id`/`conversation_id` 一律为 **NULL**（该列可空且无外键）——既不把开销挂到任何学生头上，也便于事后 `WHERE user_id IS NULL AND task_type='eval'` 一次查出全部评测行；跑 400 题基准约留 800 行（每题一次 `eval` + 一次 `verify`） |
| `feedbacks` ✦ | `id, message_id(UNIQUE), user_id, rating('up'/'down'), reason(VARCHAR(500),可空), created_at` | 答案反馈（消息级点赞/点踩）；`message_id` 唯一，重复提交 UPSERT 覆盖 |
| `kb_search_logs` ✦ | `id, user_id, conversation_id(可空), subject, collection, query, result_count, kp_ids(TEXT,可空), status, elapsed_ms, created_at` | 知识库检索日志（可观测）；`status` 六态：ok/empty/timeout/http_error/code_error/degraded。`query` 存提问原文（属隐私，删学生时必须清）。⚠️ **批量评测全程不写本表**（`kb_client.search(..., log_enabled=False)`）：400 题 × 2 次检索 = 800 行灌进去会把给使用方看的检索质量报表彻底冲掉，见 §6 |
| `app_settings` ✦ | `id, setting_key(UNIQUE), setting_value(VARCHAR(255)), updated_at` | 全局设置（K-V）；值统一存字符串，读时按键转型（`app/settings_store.py`）。当前 6 键：`daily_question_limit_default`(20) / `memory_enabled_default`(1) / `chat_concurrency`(3) / `chat_queue_size`(5) / `profile_update_interval`(20) / **`practice_reveal_answer`(0，v4.1)**；后两个 bool 键见 `BOOL_KEYS`。键与默认值的单一事实来源是 `SETTING_DEFAULTS`，`seed.py` 幂等补齐 |
| `exams` ✦✦ | `id, user_id, subject, chapter_ids(JSON,可空), status('ongoing'/'grading'/'graded'), question_count, total_score, obtained_score(DECIMAL,可空), created_at, submitted_at(可空)` | 试卷（v4.0 M2）；`idx_user_status` 索引支撑「每人仅 1 张 ongoing」 |
| `exam_answers` ✦✦ | `id, exam_id, seq, question_id, question_type, question_snapshot(TEXT), full_score, student_answer(TEXT,可空), score(DECIMAL,可空), llm_reason(TEXT,可空), disputed(TINYINT DEFAULT 0), created_at` | 试卷答题（v4.0 M2）；`uk_exam_seq(exam_id,seq)` 唯一；`question_snapshot` 存题目全量 JSON（含答案解析） |
| `student_profiles` ✦✦✦ | `user_id(INT PK), style_profile(VARCHAR 500,可空), dialog_count_since_update(INT DEFAULT 0), updated_at(DATETIME)` | 学生学习风格画像（v4.0 M3）；一人一行；`style_profile` 为 LLM 生成的画像文本（硬限 200 字符） |
| `wrong_questions` ✦✦✦ | `id, user_id, subject, question_id(VARCHAR 32), question_snapshot(TEXT), my_answer(TEXT,可空), wrong_count(INT DEFAULT 1), mastered(TINYINT DEFAULT 0), last_wrong_at(DATETIME), source_exam_id(INT,可空), last_mastered_at(DATETIME,可空)` | 错题本（v4.0 M3）；`uk_user_question(user_id,question_id)` 唯一 → UPSERT；`idx_user_mastered(user_id,mastered)` 索引 |

> 标 ✦ 的为 v4.0 M1 新增；✦✦ 为 v4.0 M2 新增；✦✦✦ 为 v4.0 M3 新增。不迁移旧 SQLite 数据；MySQL 为全新库，首次 `seed.py` 写入管理员 + 默认模型 + 默认全局设置。

---

## 8. 接口一览（43 个业务接口）

Base URL：`http://localhost:8000`。权限：🟢 全员登录 ｜ 🔒 管理员。
**接口明细（请求/响应/示例）是 `doc/接口文档.md` 的单一职责,本节仅作分组索引。**

| 模块 | 代码位置 | 数量 | 权限 | 说明 |
|------|---------|------|------|------|
| 认证 | `app/auth/` | 3 | 公开 / 🟢 | 登录取 JWT、当前用户信息、自助改密码 `PUT /api/me/password`（v4.0） |
| 对话 | `app/chat/` | 6 | 🟢 | 流式对话 `POST /api/chat`（SSE，入参支持 `subject` 枚举与 `image_base64` 图片题目；v4.1 意图三分流 solve/practice/consult；事件全集 `start/queue/ocr/kb_search/kb_refs/kp_ids/match/delta/suggestions/done/error`，其中 `ocr` 为 v4.0 图片识别、**`match` 为 v4.1 solve 命中档位**；限流三态 429）、答案反馈 `POST /api/feedback`（v4.0）、会话 CRUD |
| 管理员 | `app/admin/` | 12 | 🔒 | 学生增删改查、批量导入、使用统计；v4.0 新增：全局设置 GET/PUT、单人权益 `PUT /students/{id}/entitlements`、反馈明细 `GET /feedbacks`、检索报表 `GET /kb/stats` + `GET /kb/hot-kps` |
| 大模型管理 | `app/llm/` | 6 | 🔒 | 模型 CRUD、`activate` 切换、`usage` 用量费用 |
| 科目 | `app/kb/subjects.py` | 1 | 🟢 | `GET /api/subjects` 返回已上线科目枚举 |
| 考试 | `app/exam/` | 9 | 🟢 / 🔒 | v4.0 M2 新增：学生端 6 个（创建/暂存/交卷/列表/详情/异议）+ 管理端 3 个（列表筛选/详情/复核改分） |
| 学生记忆 | `app/profile/` | 5 | 🟢 / 🔒 | v4.0 M3 新增：学生端 3 个（错题本列表/重练判分/我的画像）+ 管理端 2 个（学生画像/全校错题统计） |
| 批量评测 | `app/admin/eval.py` | 1 | 🔒 | v4.1 新增：`POST /api/admin/eval/answer` 单题作答，返回结构化档位/引用/用量，供 `scripts/batch_eval.py` 跑基准题库并导出 Excel 交专家线下评分。**不落库对话、不扣配额、不占并发槽、不写 `kb_search_logs`**，唯一持久化副作用是 `usage_logs` 记 `task_type='eval'` 且 `user_id` 为 NULL |

> 反馈提交（`POST /api/feedback`）属对话模块（代码在 `chat/router.py`）；反馈明细/全局设置/权益/检索报表属管理员模块（代码在 `admin/router.py`）。
> **v4.1 答题链路重构本身未新增/未删除任何 HTTP 接口**：变化全在 `POST /api/chat` 的内部链路（意图分流）与 SSE 事件类型（新增 `match`）上，`PUT /api/admin/settings` 则多了一个可写键 `practice_reveal_answer`。**42 → 43 的那一个是重构之后为基准题库评测加的 `POST /api/admin/eval/answer`**（见上表末行）。
> 另有运维接口 `GET /api/health`（健康检查，无需认证；v4.0 升级为三字段 `status/mysql/kb`，任一依赖 fail 时 `status=degraded` 但 HTTP 仍 200，KB 探测见 `app/kb/client.py::probe`）。全部接口的路径与字段明细见 `doc/接口文档.md`。

---

## 9. 文档维护约定（AI 必读）

保持文档与代码同步，是本项目文档架构的核心目标：

1. **改代码即改文档**：任何接口/表结构/模块/命令/依赖版本变化，必须在同一次改动中更新受影响文档。
2. **单一事实来源**：
   - 接口明细只写在 `doc/接口文档.md`；本文件 §8 只维护「一览」。
   - 技术栈版本以 `frontend/package.json` / `backend/requirements.txt` 为准，文档引用需与其一致。
   - **全部文档只放 `doc/` 一个目录**（设计/方案类放 `doc/plans/`，运维类放 `doc/ops/`），**不得新建平级的 `docs/`**。2026-08 曾误建 `docs/plans/` 导致设计文档分裂两处，已于本轮归并。
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

