#!/bin/bash
# 重启 AutoCheckin 服务端
set -e

cd "$(dirname "$0")"

echo "=== 拉取最新代码 ==="
git pull origin main

echo "=== 重启服务 ==="
sudo systemctl restart autocheckin

echo "=== 服务状态 ==="
sudo systemctl status autocheckin --no-pager

echo ""
echo "✓ 重启完成"
