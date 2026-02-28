# AutoCheckin - 企业微信自动打卡系统

一套完整的企业微信自动打卡方案：安卓手机放在公司连接WiFi，定时自动打卡，通过Web面板远程监控和手动操控。

## 产品逻辑

### 核心场景

1. 一台安卓手机（Redmi Turbo 4）长期放在公司，连接公司WiFi
2. 每天上班/下班时间自动打开企业微信完成打卡
3. 用户通过浏览器（手机/电脑）远程查看打卡状态、手动触发打卡、查看截图

### 功能列表

| 功能 | 说明 |
|------|------|
| 定时自动打卡 | 按配置时间自动执行上班/下班打卡，带随机延时防检测 |
| 远程手动打卡 | 通过Web面板一键触发上班/下班打卡 |
| 实时状态监控 | 查看手机在线状态、电量、WiFi连接、ADB状态 |
| 打卡历史记录 | 查看历史打卡记录，包含时间、类型、成功/失败、触发方式 |
| 远程截图 | 一键获取手机当前屏幕截图 |
| 打卡时间配置 | 远程修改上班/下班时间、随机延时、周末节假日跳过 |
| 实时日志 | Web面板展示实时操作日志 |

### 打卡流程

```
定时触发 / 手动触发
       │
       ▼
  检查WiFi是否连接公司网络
       │ 是
       ▼
  唤醒屏幕 → 滑动解锁
       │
       ▼
  打开企业微信App
       │
       ▼
  点击底部"工作台"Tab
       │
       ▼
  在"内部管理"区域找到"打卡"并点击
       │
       ▼
  等待打卡页面加载（显示"你已在打卡范围内"）
       │
       ▼
  点击中间圆形打卡按钮（"上班打卡"/"下班打卡"）
       │
       ▼
  验证打卡结果 → 截图
       │
       ▼
  上报结果到服务器 → 返回手机桌面
```

### 防检测策略

- **指数分布随机延时**：打卡时间不是固定的，大多数延时较短（1-5分钟），偶尔较长，模拟真人行为
- **随机操作间隔**：UI操作之间有200-500ms的随机等待
- **节假日/周末跳过**：内置中国法定节假日表，自动跳过非工作日
- **WiFi验证**：打卡前检查是否连接公司WiFi，避免异常打卡

## 技术架构

### 系统架构图

```
手机端 (Termux + Python)                 云服务器 (FastAPI)               用户浏览器
┌────────────────────────┐              ┌───────────────────┐           ┌──────────┐
│                        │   WebSocket  │                   │   HTTP    │          │
│  APScheduler           │◄────────────►│  WebSocket Manager│◄─────────►│ Dashboard│
│  (定时任务调度)          │  手机主动连接 │  (连接管理)        │           │ (状态/   │
│                        │  NAT友好     │                   │  WebSocket│  控制)   │
│  uiautomator2          │              │  REST API         │◄─────────►│          │
│  (UI自动化)             │              │  (接口层)          │  实时推送  │          │
│                        │              │                   │           │          │
│  DeviceManager         │              │  SQLite           │           │          │
│  (ADB/设备管理)         │              │  (数据存储)        │           │          │
│                        │              │                   │           │          │
│  WebSocket Client      │              │  Jinja2 Templates │           │          │
│  (自动重连)             │              │  (页面渲染)        │           │          │
└────────────────────────┘              └───────────────────┘           └──────────┘
```

### 核心设计决策

**1. 调度器运行在手机端**

调度器（APScheduler）运行在手机上而非服务器上。即使服务器宕机或网络中断，手机仍然能按时打卡。服务器仅作为远程控制面板和日志存储。

**2. WebSocket由手机主动连接**

手机主动连接云服务器的WebSocket端点，不需要内网穿透（frp/ngrok）。手机在任何NAT网络环境下都能连通，断线自动重连（指数退避）。

**3. 无需ROOT**

使用uiautomator2通过ADB无线调试控制手机UI，不需要ROOT权限。通过Termux在手机本地运行Python脚本，ADB自连接到本机。

### 项目结构

```
autocheckin/
├── server/                          # 云服务器代码
│   ├── main.py                      # FastAPI 应用入口，挂载路由和静态文件
│   ├── api.py                       # REST API + WebSocket 端点定义
│   │   ├── GET  /api/status         # 获取设备和打卡状态
│   │   ├── GET  /api/history        # 获取打卡历史记录
│   │   ├── POST /api/checkin        # 手动触发打卡
│   │   ├── POST /api/screenshot     # 请求手机截图
│   │   ├── GET  /api/schedule       # 获取打卡时间配置
│   │   ├── PUT  /api/schedule       # 更新打卡时间配置
│   │   ├── WS   /ws/phone           # 手机Agent WebSocket端点
│   │   └── WS   /ws/dashboard       # 浏览器Dashboard WebSocket端点
│   ├── database.py                  # SQLite数据库初始化和连接管理
│   ├── models.py                    # Pydantic数据模型定义
│   ├── ws_manager.py                # WebSocket连接管理器（核心）
│   │   ├── 管理手机和浏览器的WebSocket连接
│   │   ├── 路由手机消息到数据库和浏览器
│   │   ├── 保存截图文件
│   │   └── 维护实时状态（设备状态、今日打卡）
│   ├── templates/
│   │   └── index.html               # Dashboard单页面
│   ├── static/
│   │   ├── style.css                # 移动端优先的响应式样式
│   │   └── app.js                   # 前端逻辑（WebSocket、API调用、UI更新）
│   ├── screenshots/                 # 截图存储目录（自动创建）
│   └── requirements.txt
│
├── agent/                           # 手机端代码（运行在Termux）
│   ├── main.py                      # Agent入口，包含：
│   │   ├── APScheduler定时任务调度
│   │   ├── WebSocket命令分发
│   │   ├── 心跳上报循环
│   │   ├── 节假日/工作日判断
│   │   └── 指数分布随机延时
│   ├── checkin.py                   # 打卡自动化核心逻辑
│   │   ├── perform_checkin()        # 完整打卡流程编排
│   │   ├── _open_wecom()            # 打开企业微信
│   │   ├── _go_to_workbench()       # 导航到工作台
│   │   ├── _click_checkin_entry()   # 点击打卡入口
│   │   ├── _click_checkin_button()  # 点击打卡按钮
│   │   └── _verify_checkin_result() # 验证打卡结果
│   ├── device.py                    # 设备管理
│   │   ├── ADB无线自连接
│   │   ├── uiautomator2初始化
│   │   ├── 获取电量/WiFi/屏幕状态
│   │   ├── 唤醒屏幕/解锁
│   │   └── 截图（base64编码）
│   ├── ws_client.py                 # WebSocket客户端（指数退避自动重连）
│   ├── config.yaml                  # Agent配置文件
│   ├── setup_termux.sh              # Termux一键安装脚本
│   └── requirements.txt
│
└── README.md
```

### WebSocket 消息协议

所有消息为JSON格式，包含 `type` 和 `ts` 字段。

#### 手机 → 服务器

| type | 说明 | 关键字段 |
|------|------|---------|
| `heartbeat` | 每30秒心跳 | battery_level, wifi_ssid, adb_connected |
| `checkin_result` | 打卡结果 | success, checkin_type, checkin_time, screenshot_b64, trigger |
| `device_status` | 设备完整状态 | 电量/WiFi/ADB + today_checkins + schedule |
| `screenshot_result` | 截图响应 | screenshot_b64 |
| `error` | 错误上报 | error_code, message, screenshot_b64 |

#### 服务器 → 手机

| type | 说明 | 关键字段 |
|------|------|---------|
| `checkin` | 触发打卡 | checkin_type ("上班"/"下班"/"auto") |
| `screenshot` | 请求截图 | - |
| `status` | 请求状态 | - |
| `update_schedule` | 更新打卡配置 | morning_time, evening_time, random_delay_max |

#### 服务器 → 浏览器

| type | 说明 |
|------|------|
| `init_state` | 连接时发送当前完整状态 |
| `device_update` | 设备状态更新 |
| `checkin_update` | 打卡结果更新 |
| `screenshot_update` | 新截图 |
| `connection_status` | 手机上线/离线 |

### 数据库设计（SQLite）

```sql
-- 打卡记录
checkin_logs (
    id, checkin_type, checkin_time, success,
    trigger, message, screenshot_path, created_at
)

-- 设备状态快照
device_status (
    id, battery_level, battery_charging,
    wifi_ssid, wifi_ip, screen_on, adb_connected, recorded_at
)

-- 打卡时间配置（单行）
schedule_config (
    id=1, morning_time, evening_time,
    random_delay_max, skip_weekends, skip_holidays, updated_at
)
```

### 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 服务端框架 | FastAPI | 异步高性能，原生WebSocket支持 |
| 数据库 | SQLite (aiosqlite) | 轻量，单文件，异步访问 |
| 页面渲染 | Jinja2 + 原生JS | 无前端框架依赖，轻量 |
| UI自动化 | uiautomator2 | 通过ADB控制安卓UI，无需ROOT |
| 定时调度 | APScheduler | 支持cron表达式，持久化任务 |
| 通信协议 | WebSocket | 双向实时通信，NAT友好 |
| 手机运行环境 | Termux | 安卓上的Linux终端，运行Python |

## 部署指南

### 云服务器部署

```bash
cd server
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
```

访问 `http://服务器IP:8080` 即可看到Dashboard。

生产环境建议配合nginx + HTTPS + systemd：

```bash
# /etc/systemd/system/autocheckin.service
[Unit]
Description=AutoCheckin Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/autocheckin/server
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

### 手机端部署（Redmi Turbo 4）

#### 1. 安装Termux

从 [F-Droid](https://f-droid.org/packages/com.termux/) 下载安装（不要用Google Play版本）。
同时安装 [Termux:Boot](https://f-droid.org/packages/com.termux.boot/)（开机自启）。

#### 2. 克隆代码并安装依赖

```bash
git clone git@github.com:JunhaoXue/AutoCheckin.git
cd AutoCheckin/agent
bash setup_termux.sh
```

#### 3. 配置ADB无线调试

**必须使用分屏模式**（同时看到Termux和设置页面）：

```bash
# 步骤1: 清理ADB
adb kill-server

# 步骤2: 配对（用弹窗里的配对端口和配对码）
adb pair 127.0.0.1:配对端口
# 输入6位配对码

# 步骤3: 连接（用主页面的连接端口，不是配对端口）
adb connect 127.0.0.1:连接端口

# 步骤4: 验证
adb devices
```

> **注意事项：**
> - 配对端口和连接端口是不同的，不要搞混
> - 必须用 `127.0.0.1`，不要用WiFi IP
> - 保持分屏模式，不要离开无线调试页面
> - MIUI/HyperOS切换App时可能关闭无线调试端口

#### 4. 初始化uiautomator2

```bash
source venv/bin/activate
python -m uiautomator2 init
```

#### 5. 修改配置

编辑 `config.yaml`：

```yaml
server_ws_url: "ws://你的服务器IP:8080/ws/phone"
adb_port: 连接端口号
wifi_ssid: "公司WiFi名称"
schedule:
  morning_time: "08:30"
  evening_time: "18:30"
```

#### 6. 启动Agent

```bash
source venv/bin/activate
python main.py
```

#### 7. 设置开机自启

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-agent.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home/AutoCheckin/agent
source venv/bin/activate
python main.py >> logs/agent.log 2>&1 &
EOF
chmod +x ~/.termux/boot/start-agent.sh
```

#### 8. 防止Termux被杀

- 设置 → 应用 → Termux → 电池 → 无限制
- 最近任务界面锁定Termux（下拉卡片锁定）

## 常见问题

### ADB连接被拒绝（Connection refused）
- 确认用的是 `127.0.0.1` 而不是WiFi IP
- 确认用分屏模式操作，不要离开无线调试页面
- 配对端口≠连接端口，注意区分
- 执行 `adb kill-server` 后重试

### 打卡按钮找不到
- 企业微信版本更新可能导致UI变化
- 修改 `checkin.py` 中的文本匹配规则适配新UI
- 使用截图功能排查当前页面状态

### 手机重启后Agent不工作
- 需要重新开启无线调试并配对ADB
- 确认已安装Termux:Boot和开机自启脚本
- 检查 `logs/agent.log` 排查错误

## 后续迭代方向

- [ ] 打卡结果推送（微信/钉钉/Telegram通知）
- [ ] 多设备管理（支持多台手机同时管理）
- [ ] Web面板登录认证（用户名密码）
- [ ] 自动更新节假日表（接入公共API）
- [ ] 打包为独立Android App（替代Termux方案）
- [ ] ADB断线自动重连机制优化
