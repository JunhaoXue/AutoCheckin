#!/data/data/com.termux/files/usr/bin/bash
# AutoCheckin Agent 启动脚本
# 用法: bash start.sh

cd "$(dirname "$0")"

# 获取 wakelock 防止息屏后被杀
termux-wake-lock

# 创建日志目录
mkdir -p logs

# 拉取最新代码
git pull

# 激活虚拟环境
source venv/bin/activate

# 杀掉旧进程（如果有的话）
pkill -f "python main.py" 2>/dev/null
sleep 1

# 后台启动
nohup python main.py >> logs/agent.log 2>&1 &

echo "Agent 已启动 (PID: $!)"
echo "查看日志: tail -f logs/agent.log"
echo "停止脚本: pkill -f 'python main.py'"
