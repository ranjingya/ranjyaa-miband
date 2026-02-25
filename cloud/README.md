# cloud - 云端服务

Flask 服务，负责接收本地上传的心率/窗口数据，SSE 实时推送，LangChain Agent 聊天。

## 文件

| 文件 | 说明 |
|------|------|
| `cloud_bridge.py` | Flask 主服务（路由、SSE、数据持久化） |
| `agent.py` | LangChain Agent（4 个 @tool + ReAct + 流式输出） |
| `gun.py` | Gunicorn 配置（gevent worker） |
| `Dockerfile` | Docker 部署 |
| `html/frontend.html` | 单文件前端（心率图表 + 窗口 + 聊天面板） |
| `data/` | 运行时自动创建，JSON 持久化（hr_history / window_history） |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASK_HOST` | `0.0.0.0` | 监听地址 |
| `FLASK_PORT` | `5001` | 端口 |
| `MINIMAX_API_KEY` | （必须） | MiniMax API 密钥 |

## API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 |
| `/upload` | POST | 心率上传 |
| `/upload_window` | POST | 窗口切换上传 |
| `/stream` | GET | SSE 心率推送 |
| `/chat` | POST | Agent 聊天（SSE 流式） |
| `/status` | GET | 状态 |
| `/health` | GET | 健康检查 |
| `/reset` | POST | 重置数据 |
