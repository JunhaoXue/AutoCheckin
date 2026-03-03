#!/bin/bash
# 重启 AutoCheckin 服务端
# 用法:
#   bash restart.sh       # 默认 AWS 模式 (3.144.252.203)
#   bash restart.sh cn    # 中国模式 (118.31.222.96)
set -e

cd "$(dirname "$0")"

# 部署配置
MODE="${1:-aws}"
case "$MODE" in
  cn)
    SERVER_IP="118.31.222.96"
    SERVER_PORT="8088"
    echo "=== 中国部署模式 ($SERVER_IP:$SERVER_PORT) ==="
    ;;
  *)
    SERVER_IP="3.144.252.203"
    SERVER_PORT="8088"
    echo "=== AWS 部署模式 ($SERVER_IP:$SERVER_PORT) ==="
    ;;
esac

echo "=== 拉取最新代码 ==="
git pull origin main

echo "=== 安装服务端依赖 ==="
cd server
if [ ! -d "venv" ]; then
    echo "  创建虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt -q
cd ..

echo "=== 更新 Agent 配置 ==="
sed -i "s|server_ws_url:.*|server_ws_url: \"ws://${SERVER_IP}:${SERVER_PORT}/ws/phone\"|" agent/config.yaml
echo "  server_ws_url: ws://${SERVER_IP}:${SERVER_PORT}/ws/phone"

echo "=== 重启服务 ==="
sudo systemctl restart autocheckin

echo "=== 服务状态 ==="
sudo systemctl status autocheckin --no-pager

echo ""
echo "✓ 重启完成 (${MODE}模式, ${SERVER_IP}:${SERVER_PORT})"
