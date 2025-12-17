# ranjyaa-miband - 小米手环心率实时监测系统

Windows 本地读取小米手环心率，通过 HTTP POST 上传到云端，实时推送到浏览器。

---

## 📦 安装依赖

### 云端服务器
```bash
# 仅需要云端依赖
pip install flask redis gunicorn[gevent] gevent
```

### 本地 Windows
```bash
# 使用 uv 管理（推荐）
uv sync

# 或手动安装
pip install bleak flask requests
```

---

## 🚀 快速开始

### 一、云端服务器部署

**第1步：启动云桥接服务**
```bash
# 方式 A: 直接运行（开发/测试）
python cloud_bridge.py

# 方式 B: 使用 gunicorn（生产推荐）
gunicorn -c cloud/gun.py cloud_bridge:app
```

**第2步：Docker 部署（可选）**
```bash
cd cloud
docker build -t miband-bridge .
docker run -d -p 5001:5001 \
  -e REDIS_ENABLED=false \
  --name miband-bridge miband-bridge
```

**端口说明：**
- 默认端口：`5001`
- 环境变量：`FLASK_PORT=5001`

---

### 二、本地 Windows 运行

**第1步：配置**
```python
# 编辑 local_uploader.py 顶部

# 你的手环地址（通过蓝牙设置查看）
DEVICE_ADDRESS = "F9:C6:02:2B:B9:A4"

# 你的云服务器地址
CLOUD_URL = "http://你的云服务器IP:5001/upload"
```

**第2步：运行**
```bash
# 使用 uv（推荐）
uv run python local_uploader.py

# 或直接 python（需先安装依赖）
python local_uploader.py
```

---

### 三、浏览器访问

打开浏览器访问：
```
http://你的云服务器IP:5001
```

---

## 📁 项目结构

```
ranjyaa-miband/
├── README.md                    # 使用指南
├── CLAUDE.md                    # 开发文档
├── pyproject.toml               # 根目录依赖（本地）
│
├── local_uploader.py            # 本地 Windows：BLE → HTTP POST
│
└── cloud/                       # 云端部署目录
    ├── pyproject.toml           # 云端依赖
    ├── cloud_bridge.py          # Flask 服务（接收 POST + SSE）
    ├── gun.py                   # Gunicorn 配置
    ├── Dockerfile               # Docker 部署文件
    └── html/
        └── frontend.html        # 前端界面（带在线人数显示）
```

---

## 🔧 配置说明

### 本地配置 (local_uploader.py)

```python
# 设备地址（必须修改）
DEVICE_ADDRESS = os.getenv("MI_BAND_ADDRESS", "F9:C6:02:2B:B9:A4")

# 云服务器地址（必须修改）
CLOUD_URL = os.getenv("CLOUD_URL", "http://你的IP:5001/upload")
```

**环境变量方式**
```bash
# Windows
set MI_BAND_ADDRESS=F9:C6:02:2B:B9:A4
set CLOUD_URL=http://123.45.67.89:5001/upload

# Linux/macOS
export MI_BAND_ADDRESS=F9:C6:02:2B:B9:A4
export CLOUD_URL=http://123.45.67.89:5001/upload
```

### 云端配置 (cloud_bridge.py)

```python
# Flask 端口（默认 5001）
FLASK_PORT = int(os.getenv("FLASK_PORT", 5001))

# Redis 配置（可选，默认禁用）
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")  # 无密码留空
```

**禁用 Redis（默认模式）**
```bash
# 无需修改代码，直接运行
python cloud_bridge.py
```

**启用 Redis**
```bash
export REDIS_ENABLED=true
export REDIS_PASSWORD=your_password  # 如有密码
python cloud_bridge.py
```

---

## 🔌 API 端点

### 云端服务 (cloud_bridge.py)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端 HTML 页面 |
| `/upload` | POST | 接收本地 upload 上传的心率数据 |
| `/stream` | GET | SSE 数据流（浏览器订阅） |
| `/status` | GET | 系统状态（数据量、在线人数、Redis状态） |
| `/health` | GET | 健康检查 |
| `/healthz` | GET | K8s 探针 |
| `/reset` | POST | 重置统计数据 |

### 上传数据格式

**请求 (local_uploader.py → cloud)**
```json
{
  "heart_rate": 75,
  "device_address": "F9:C6:02:2B:B9:A4",
  "timestamp": "2025-12-17T20:00:00",
  "platform": "windows"
}
```

**响应**
```json
{
  "status": "ok",
  "data_count": 123,
  "redis": "direct"  // 或 "published"
}
```

**SSE 数据格式 (cloud → 浏览器)**
```json
{
  "heart_rate": 82,
  "device_address": "F9:C6:02:2B:B9:A4",
  "timestamp": "2025-12-17T20:00:05",
  "platform": "windows",
  "server_timestamp": "2025-12-17T20:00:05.123456",
  "server_time_ms": 1734472805123,
  "active_clients": 2
}
```

---

## 🐛 故障排查

### ❌ 本地上传失败

**测试云服务器连通性**
```bash
# Windows 上测试
curl http://你的云服务器IP:5001/health

# 测试上传接口
curl -X POST http://你的云服务器IP:5001/upload \
  -H "Content-Type: application/json" \
  -d '{"heart_rate": 75}'
```

**可能原因：**
1. 云服务器防火墙未开放 5001 端口
2. `CLOUD_URL` 配置错误
3. 云服务器未启动 cloud_bridge.py

### ❌ 手环连接问题

**检查蓝牙设备**
```powershell
# PowerShell
Get-PnpDevice -Class Bluetooth
Get-PnpDevice | Where-Object {$_.FriendlyName -like "*Band*"}
```

**解决步骤：**
1. 确保手环已开启
2. 关闭手机蓝牙连接（手环只能同时连接一个设备）
3. 重启手环
4. 首次使用可能需要配对

### ❌ Docker 部署问题

**查看日志**
```bash
docker logs -f miband-bridge
```

---

## 🎯 部署清单

### 云端服务器
- [ ] 端口 5001 已开放（防火墙/安全组）
- [ ] cloud_bridge.py 运行正常
- [ ] 访问 `http://服务器IP:5001` 显示前端页面
- [ ] Redis 已安装（如需启用）

### 本地 Windows
- [ ] 修改 `DEVICE_ADDRESS` 为你的手环地址
- [ ] 修改 `CLOUD_URL` 为你的服务器地址
- [ ] 手环蓝牙已开启
- [ ] 关闭手机蓝牙连接
- [ ] `local_uploader.py` 显示 `✓ 连接成功`

### 浏览器
- [ ] 访问 `http://服务器IP:5001`
- [ ] 右上角显示在线用户数
- [ ] 心率数值实时更新

---

## 架构图

```
本地 Windows (手环)      云服务器                浏览器
┌──────────────┐      ┌──────────────┐      ┌──────────┐
│ BLE 读取      │      │              │      │          │
│ ┌──────────┐ │      │ POST /upload │◀─────│          │
│ │本地程序  │─┼─────▶│   ↔ 内存/Redis│      │          │
│ │(上传)    │ │      │              │      │          │
│ └──────────┘ │      │  SSE /stream │─────▶│  实时显示 │
│              │      │              │      │  在线人数 │
└──────────────┘      └──────────────┘      └──────────┘
```

---

## 版本信息

**版本**: v2.0.0
**架构**: HTTP POST + SSE
**端口**: 5001
**验证设备**: Xiaomi Smart Band 10 07F2
**更新日期**: 2025-12-17
