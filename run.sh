#!/usr/bin/env bash
# Chat2API-Plus 启动脚本
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "未发现 .env，已从 .env.example 复制一份，请编辑后重启。"
  cp .env.example .env
fi

exec python3 app.py "$@"
