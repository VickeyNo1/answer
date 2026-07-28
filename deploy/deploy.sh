#!/usr/bin/env bash
# 机器B 部署/更新脚本（幂等，root 执行）：拉代码 -> 后端同步+建表 -> 前端构建 -> 重启服务
# 用法： bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/answer}"
export PATH="$HOME/.local/bin:$PATH"

echo "==> [1/5] git pull"
cd "$APP_DIR" && git pull --ff-only

echo "==> [2/5] 后端：uv sync + 建库建表/初始化数据（幂等）"
cd "$APP_DIR/backend"
uv sync
uv run python seed.py

echo "==> [3/5] 前端：npm ci + build（读取 frontend/.env.production 注入 NEXT_PUBLIC_API_URL）"
cd "$APP_DIR/frontend"
npm ci
npm run build

echo "==> [4/5] 重启服务"
systemctl restart answer-backend
systemctl restart answer-frontend
systemctl reload-or-restart nginx

echo "==> [5/5] 健康检查（最多等 30 秒）"
ok=""
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null; then ok=1; break; fi
  sleep 1
done
if [ -n "$ok" ]; then
  echo
  echo "部署完成 ✅  外部访问： http://8.148.219.179/"
else
  echo "后端健康检查失败，请查看： journalctl -u answer-backend -n 50 --no-pager"
  exit 1
fi
