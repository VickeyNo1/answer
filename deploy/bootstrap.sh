#!/usr/bin/env bash
# 机器B 首次环境初始化（Alibaba Cloud Linux 2 / RHEL 系，root 执行）
# 用法： bash deploy/bootstrap.sh   （或先 chmod +x）
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/answer}"
# 无 SSH key 时改用 https：https://github.com/VickeyNo1/answer.git
REPO="${REPO:-git@github.com:VickeyNo1/answer.git}"

echo "==> [1/4] 安装系统依赖 (git, nginx)"
if command -v dnf >/dev/null 2>&1; then
  dnf install -y git nginx
else
  yum install -y git nginx
fi

echo "==> [2/4] 安装 Node.js 20 (NodeSource)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
  if command -v dnf >/dev/null 2>&1; then dnf install -y nodejs; else yum install -y nodejs; fi
fi
node -v && npm -v

echo "==> [3/4] 安装 uv (自带管理 Python 3.11)"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo "==> [4/4] 拉取代码到 $APP_DIR"
mkdir -p "$(dirname "$APP_DIR")"
if [ -d "$APP_DIR/.git" ]; then
  ( cd "$APP_DIR" && git pull --ff-only )
else
  git clone "$REPO" "$APP_DIR"
fi

cat <<EOF

bootstrap 完成。接下来手动执行一次（仅首次）：
  1) 创建后端生产配置： $APP_DIR/backend/.env
       复制 backend/.env.example 并改为机器A 私网：
         MYSQL_HOST=172.22.207.228
         MYSQL_USER=answer / MYSQL_PASSWORD=<真实密码> / MYSQL_DB=answer
         KB_BASE_URL=http://172.22.207.228:8100
         CORS_ORIGINS=http://8.148.219.179
         DASHSCOPE_API_KEY / JWT_SECRET_KEY 填真实值
  2) 创建前端生产配置： $APP_DIR/frontend/.env.production
         NEXT_PUBLIC_API_URL=http://8.148.219.179
  3) 安装 systemd 服务与 Nginx：
         cp $APP_DIR/deploy/answer-backend.service  /etc/systemd/system/
         cp $APP_DIR/deploy/answer-frontend.service /etc/systemd/system/
         cp $APP_DIR/deploy/nginx-answer.conf       /etc/nginx/conf.d/answer.conf
         systemctl daemon-reload
         systemctl enable answer-backend answer-frontend nginx
  4) 首次构建并启动： bash $APP_DIR/deploy/deploy.sh
EOF
