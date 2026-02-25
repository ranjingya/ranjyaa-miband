# ranjyaa-miband

小米手环心率实时监测 + Windows 窗口监控 + LangChain Agent 智能问答。

## 效果图  
<img width="749" height="1262" alt="PixPin_2026-02-25_17-21-58" src="https://github.com/user-attachments/assets/0eed68e4-99f3-46b2-9574-2fb6fb9c642b" />


## 它能干什么

1. **读心率** — 通过 BLE 连接小米手环，实时读取心率数据
2. **看窗口** — 用 ctypes 调 `user32.dll` 监控 Windows 前台窗口切换
3. **传云端** — 本地数据 HTTP POST 上传到云服务器，SSE 推送到浏览器
4. **问 AI** — 内置 LangChain Agent，可以问「他在摸鱼吗」「心率怎么样」之类的问题

## 架构

```
本地 Windows                    云服务器                        浏览器
┌─────────────────┐        ┌─────────────────────┐        ┌──────────────────┐
│                 │        │                     │        │                  │
│  BLE 读取心率    │──POST──  Flask 接收 + 存储   │        │  心率折线图       │
│  ctypes 窗口监控 │──POST──  JSON 文件持久化     │        │  当前窗口卡片     │
│                 │        │                     │        │  avg/max/min     │
│                 │        │  SSE /stream  ──────────────│                  │
│                 │        │  POST /chat   ──────────────│  Agent 聊天面板   │
│                 │        │  LangChain Agent     │        │  (流式+Markdown) │
└─────────────────┘        └─────────────────────┘        └──────────────────┘
```

## 技术栈

| 层 | 技术 |
|---|------|
| BLE 通信 | bleak |
| 窗口监控 | ctypes + user32.dll |
| 云端服务 | Flask + Gunicorn (gevent) |
| 数据持久化 | JSON 文件 |
| 实时推送 | Server-Sent Events |
| AI Agent | LangChain + LangGraph ReAct |
| LLM | MiniMax M2.5（OpenAI 兼容 API） |
| 前端图表 | Canvas 手绘折线图 |
| Markdown | marked.js |

## Agent 工具

Agent 注册了 4 个 `@tool`，由 LangGraph ReAct 自动调度：

| 工具 | 干什么 |
|------|--------|
| `get_heart_rate_stats` | 心率统计（avg/max/min/趋势） |
| `get_heart_window_correlation` | 心率 × 窗口关联分析 |
| `detect_slacking` | 摸鱼检测 |
| `get_app_usage_stats` | 应用使用时长排行 |

前端聊天面板支持快捷问题按钮、流式输出、思维链展示、工具调用详情折叠。

## 项目结构

```
ranjyaa-miband/
├── local_uploader.py      # 本地：BLE 心率 + 窗口监控 → HTTP POST
│
└── cloud/
    ├── cloud_bridge.py    # Flask 服务（接收/SSE/聊天）
    ├── agent.py           # LangChain Agent（@tool + ReAct + 流式）
    ├── gun.py             # Gunicorn 配置
    ├── Dockerfile
    ├── data/              # 运行时自动创建
    │   ├── hr_history.json
    │   └── window_history.json
    └── html/
        └── frontend.html  # 单文件前端
```

## API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 |
| `/upload` | POST | 心率上传 |
| `/upload_window` | POST | 窗口切换上传 |
| `/stream` | GET | SSE 心率推送 |
| `/chat` | POST | Agent 聊天（SSE 流式） |
| `/status` | GET | 状态查询 |
| `/health` | GET | 健康检查 |
| `/reset` | POST | 重置数据 |
