# 会计答疑智能体 - 后端服务

FastAPI + SQLite + ChromaDB + 通义千问大模型，面向会计专业学生的 AI 智能答疑系统。

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI 0.115+ | 异步高性能 Web 框架 |
| ASGI 服务器 | uvicorn | 支持 HTTP/1.1 + SSE |
| 数据库 | SQLite 3 (WAL 模式) | 嵌入式，零运维 |
| 向量数据库 | ChromaDB 0.5+ | 嵌入式，cosine 相似度 |
| 大模型 | 通义千问 (DashScope SDK) | 对话生成 + 文本向量化 |
| 认证 | JWT (python-jose) | 无状态令牌认证 |
| 密码加密 | bcrypt (原生库) | 安全哈希 |
| 包管理 | uv | Python 虚拟环境与依赖管理 |

## 目录结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口，CORS + 路由注册
│   ├── config.py               # pydantic-settings 配置管理
│   ├── database.py             # SQLite 连接 + 建表 + WAL 模式
│   ├── models.py               # Pydantic 数据模型
│   ├── auth/                   # 认证模块 (登录、JWT)
│   ├── chat/                   # 对话模块 (SSE 流式、多轮记忆)
│   ├── knowledge/              # 知识库模块 (文档上传、向量化检索)
│   └── admin/                  # 管理员模块 (学生 CRUD、统计)
├── tests/
│   ├── conftest.py             # 单元测试 fixtures (TestClient)
│   ├── test_*.py               # 单元测试 (97 个)
│   └── e2e/                    # E2E 端到端测试
│       ├── conftest.py         # E2E 共享 fixtures (HTTP 工具、SSE 解析)
│       ├── test_e2e_health.py     # 健康检查 (2 个)
│       ├── test_e2e_auth.py       # 认证模块 (9 个)
│       ├── test_e2e_knowledge.py  # 知识库模块 (11 个)
│       ├── test_e2e_chat.py       # 对话模块 (20 个)
│       ├── test_e2e_admin.py     # 管理员模块 (22 个)
│       └── test_e2e_frontend.py  # 前端页面 (3 个)
├── data/                       # 运行时数据 (自动创建)
│   ├── app.db                  # SQLite 数据库
│   └── chroma_db/              # ChromaDB 持久化
├── uploads/                    # 上传文件临时目录
├── seed.py                     # 初始化管理员账号脚本
├── pyproject.toml              # 项目配置 + 依赖声明
├── uv.lock                     # uv 锁定文件
├── .env                        # 环境变量 (不入版本控制)
└── .env.example                # 环境变量模板
```

## 快速开始

### 1. 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (Python 包管理工具)
- Node.js >= 18 (前端开发用)

### 2. 安装 uv

```powershell
# Windows PowerShell (推荐)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 验证安装
uv --version
```

### 3. 后端初始化

```powershell
cd d:\code\answer\backend

# 用 uv 创建虚拟环境 (Python 3.11)
uv venv --python 3.11

# 同步依赖 (自动读取 pyproject.toml)
uv sync

# 复制环境变量模板并编辑
Copy-Item .env.example .env
# 编辑 .env，填入你的 DASHSCOPE_API_KEY

# 初始化管理员账号
uv run python seed.py
# 输出: 管理员账号创建成功！学号: admin  密码: admin123
```

### 4. 启动后端

```powershell
cd d:\code\answer\backend

# 开发模式 (热重载)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式 (去掉 --reload)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 访问 API 文档 (Swagger UI)
# http://localhost:8000/docs
```

### 5. 启动前端

```powershell
cd d:\code\answer\frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 访问前端
# http://localhost:3000
```

### 6. 运行测试

```powershell
cd d:\code\answer\backend

# 运行全部单元测试 (97 个，无需服务器运行)
uv run pytest tests/ -v --ignore=tests/e2e

# 运行 E2E 端到端测试 (需要后端服务器运行在 localhost:8000)
# 先启动后端:
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
# 另开终端运行 E2E:
uv run pytest tests/e2e/ -v

# 运行单个模块的 E2E 测试
uv run pytest tests/e2e/test_e2e_auth.py -v
uv run pytest tests/e2e/test_e2e_chat.py -v

# 运行前端 E2E 测试 (需要前后端都运行)
# 前端: cd frontend && npm run dev
uv run pytest tests/e2e/test_e2e_frontend.py -v

# 运行所有测试 (单元 + E2E)
uv run pytest tests/ -v
```

## 环境变量配置

编辑 `backend/.env` 文件：

```env
# 通义千问 API Key (必填，从阿里云 DashScope 控制台获取)
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# JWT 密钥 (生产环境务必更换为随机字符串)
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24

# 数据库路径 (相对路径相对于 backend/ 目录)
DATABASE_URL=./data/app.db

# ChromaDB 向量数据库路径
CHROMA_DB_PATH=./data/chroma_db

# 上传文件目录与大小限制
UPLOAD_DIR=./uploads
MAX_FILE_SIZE_MB=10

# CORS 允许的前端域名 (多个用逗号分隔)
CORS_ORIGINS=http://localhost:3000

# 对话模型名称 (DashScope 模型)
CHAT_MODEL=qwen-plus
```

## 端口规划

| 端口 | 服务 | 说明 |
|------|------|------|
| 8000 | FastAPI 后端 | REST API + SSE 流式对话 |
| 3000 | Next.js 前端 | 页面渲染 |
| 443 | DashScope API | 通义千问对话 + Embedding (外部 HTTPS) |

## API 接口概览

| 模块 | 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|------|
| 健康 | GET | `/api/health` | 无 | 健康检查 |
| 认证 | POST | `/api/auth/login` | 无 | 登录获取 JWT |
| 认证 | GET | `/api/auth/me` | JWT | 获取当前用户信息 |
| 对话 | POST | `/api/chat` | JWT | SSE 流式对话 |
| 对话 | POST | `/api/conversations` | JWT | 新建对话 |
| 对话 | GET | `/api/conversations` | JWT | 对话列表 |
| 对话 | GET | `/api/conversations/{id}` | JWT | 消息历史 |
| 对话 | DELETE | `/api/conversations/{id}` | JWT | 删除对话 |
| 知识库 | POST | `/api/knowledge/upload` | JWT | 上传文档 |
| 知识库 | GET | `/api/knowledge/documents` | JWT | 文档列表 |
| 知识库 | DELETE | `/api/knowledge/documents/{name}` | JWT | 删除文档 |
| 管理 | POST | `/api/admin/students` | Admin | 创建学生 |
| 管理 | GET | `/api/admin/students` | Admin | 学生列表 |
| 管理 | PUT | `/api/admin/students/{id}` | Admin | 修改学生 |
| 管理 | DELETE | `/api/admin/students/{id}` | Admin | 删除学生 |
| 管理 | POST | `/api/admin/students/batch` | Admin | 批量导入 |
| 管理 | GET | `/api/admin/stats` | Admin | 使用统计 |

完整接口文档见 `doc/接口文档.md`。

## 运维指南

### 数据备份

```powershell
# 备份 SQLite 数据库
Copy-Item d:\code\answer\backend\data\app.db d:\backup\app_$(Get-Date -Format "yyyyMMdd").db

# 备份 ChromaDB 向量数据
Copy-Item -Recurse d:\code\answer\backend\data\chroma_db d:\backup\chroma_db_$(Get-Date -Format "yyyyMMdd")
```

### 日志管理

uvicorn 默认输出到标准输出。生产环境建议重定向到日志文件：

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 | Tee-Object -FilePath logs/uvicorn_$(Get-Date -Format "yyyyMMdd").log
```

### 常见问题

**Q: 启动时报 `ModuleNotFoundError: No module named 'app'`**  
A: 确保在 `backend/` 目录下运行命令，且使用 `uv run` 而非直接 `python`。

**Q: E2E 测试全部 SKIPPED**  
A: E2E 测试需要后端服务器运行在 `localhost:8000`。先启动后端再运行 E2E 测试。

**Q: 对话接口返回 500 错误**  
A: 检查 `.env` 中的 `DASHSCOPE_API_KEY` 是否正确配置。通义千问 API 需要有效的 API Key。

**Q: 前端 E2E 测试 SKIPPED**  
A: 前端测试需要 `localhost:3000` 运行 Next.js 开发服务器。

**Q: `bcrypt` 相关错误**  
A: 本项目使用原生 `bcrypt` 库（非 passlib），确保 `uv sync` 已正确安装依赖。

### 生产部署建议

1. **后端**: 使用 `uvicorn` 直接运行或通过 `gunicorn + uvicorn worker` 多进程部署
2. **前端**: `npm run build` 后由 Nginx 托管静态文件，或部署到 Vercel
3. **数据**: 定期备份 `data/app.db` 和 `data/chroma_db/` 目录
4. **安全**: 生产环境务必更换 `JWT_SECRET_KEY`，修改默认管理员密码
5. **反向代理**: Nginx 反向代理 + HTTPS 证书

### 添加新依赖

```powershell
cd d:\code\answer\backend

# 添加运行时依赖
uv add <package_name>

# 添加开发依赖
uv add --dev <package_name>

# uv.lock 会自动更新
```
