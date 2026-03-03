# 手机端配置教程

将一台安卓手机放在公司，自动帮你打卡。本教程以红米 Turbo 4 为例，其他安卓手机流程类似。

---

## 准备工作

- 一台安卓手机（Android 11+），长期放在公司充电
- 手机连接公司 WiFi
- 手机上登录好企业微信，并确保打卡功能在「工作台」页面可见

---

## 第一步：安装 Termux

Termux 是安卓上的 Linux 终端，我们用它来运行 Python 脚本。

1. 打开浏览器，访问 https://f-droid.org/packages/com.termux/
2. 下载并安装 Termux（**不要用 Google Play 版本**，版本过旧）
3. 同时安装 Termux:Boot（开机自启用）：https://f-droid.org/packages/com.termux.boot/
4. 打开 Termux，等待初始化完成

---

## 第二步：克隆代码 & 安装依赖

在 Termux 中逐行输入：

```bash
# 安装 git
pkg install -y git

# 克隆项目代码
git clone https://github.com/JunhaoXue/AutoCheckin.git

# 进入 agent 目录
cd AutoCheckin/agent

# 运行安装脚本（大约 5 分钟）
bash setup_termux.sh
```

安装完成后会看到 `=== Setup Complete ===`。

---

## 第三步：开启开发者选项 & 无线调试

### 3.1 开启开发者选项

1. 打开「设置」→「我的设备」→「全部参数与信息」
2. 连续点击「MIUI 版本」或「OS 版本」**7 次**
3. 看到提示"您已处于开发者模式"

### 3.2 开启无线调试

1. 打开「设置」→「更多设置」→「开发者选项」
2. 开启「USB 调试」
3. 开启「USB 调试（安全设置）」← **很重要，否则点击操作会被拒绝**
4. 开启「无线调试」，点击进入无线调试页面

---

## 第四步：ADB 配对和连接

> **必须使用分屏模式操作！** 一边是 Termux，一边是无线调试设置页面。离开无线调试页面可能导致端口关闭。

### 4.1 开启分屏

1. 从底部上滑进入多任务界面
2. 长按 Termux 图标 → 选择「分屏」
3. 另一半选择「设置」（停在无线调试页面）

### 4.2 配对

在无线调试页面点击「使用配对码配对设备」，会弹出一个窗口显示：
- **配对码**：6 位数字（如 482916）
- **配对端口**：如 192.168.1.100:41023

在 Termux 中输入：

```bash
adb pair 127.0.0.1:配对端口号
```

> 注意：用 `127.0.0.1`，不要用 WiFi IP！端口号用弹窗里的。

系统提示输入配对码，输入弹窗中的 6 位数字，回车。看到 `Successfully paired` 即成功。

### 4.3 连接

关闭配对弹窗，在无线调试主页面可以看到连接端口（如 `192.168.1.100:38957`）。

```bash
adb connect 127.0.0.1:连接端口号
```

> 注意：**连接端口 ≠ 配对端口**，不要搞混！

### 4.4 验证

```bash
adb devices
```

看到类似 `127.0.0.1:38957 device` 就说明连接成功。

---

## 第五步：初始化 uiautomator2

```bash
cd ~/AutoCheckin/agent
source venv/bin/activate
python -m uiautomator2 init
```

等待显示 `Successfully init` 即可。

---

## 第六步：启动 Agent

```bash
# AWS 服务器（默认）
bash start.sh

# 或中国服务器
bash start.sh cn
```

看到 `Agent 已启动` 说明运行成功。

查看日志确认连接正常：

```bash
tail -f logs/agent.log
```

看到 `WebSocket connected to server` 即表示已连上服务器。按 `Ctrl+C` 退出日志查看。

---

## 第七步：防止后台被杀

手机系统为了省电会杀后台进程，必须做以下设置：

### 7.1 关闭电池优化

设置 → 应用 → Termux → 电池 → 选择「无限制」

### 7.2 锁定 Termux

从底部上滑进入最近任务界面 → 找到 Termux → 往下拉卡片出现锁图标

### 7.3 开机自启（可选）

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-agent.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/AutoCheckin/agent
bash start.sh
EOF
chmod +x ~/.termux/boot/start-agent.sh
```

---

## 验证打卡

1. 用浏览器访问服务器面板（地址找管理员获取）
2. 点击「手动打卡」按钮
3. 观察手机是否：
   - 收到短信亮屏
   - 自动打开企业微信
   - 进入工作台 → 打卡 → 完成打卡
4. 面板上看到打卡成功的记录和截图

---

## 常见问题

### Q: `adb pair` 提示 Connection refused？
- 确认你用的是 `127.0.0.1`，不是 WiFi IP
- 确认在分屏模式下操作，没有离开无线调试页面
- 执行 `adb kill-server` 后重试

### Q: 打卡时提示 INJECT_EVENTS 权限错误？
- 去「开发者选项」→ 开启「USB 调试（安全设置）」
- 系统已有 adb tap 兜底方案，不影响使用

### Q: Agent 启动后提示 WebSocket 连接失败？
- 确认手机能访问服务器（公司网络未屏蔽）
- Agent 会自动重连，等一会儿看日志

### Q: 手机重启后 Agent 不工作？
- 需要重新进入「无线调试」页面开启
- 重新执行 `adb connect 127.0.0.1:新端口`（重启后端口会变）
- 重新执行 `bash start.sh` 或 `bash start.sh cn`

### Q: 如何停止 Agent？
```bash
pkill -f "python main.py"
```

### Q: 如何更新代码？
```bash
cd ~/AutoCheckin/agent
bash start.sh       # 脚本会自动 git pull 并重启
```
