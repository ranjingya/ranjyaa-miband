# 小米手环云桥接服务

## 快速启动

### 方式 1: 直接运行
```bash
python cloud_bridge.py
```

### 方式 2: Gunicorn (生产)
```bash
gunicorn -c gun.py cloud_bridge:app
```

### 方式 3: Docker
```bash
docker build -t miband-bridge .
docker run -d -p 5001:5001 \
  -e REDIS_ENABLED=false \
  --name miband-bridge miband-bridge
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASK_PORT` | `5001` | 服务端口 |
| `REDIS_ENABLED` | `false` | 是否启用 Redis |
| `REDIS_HOST` | `127.0.0.1` | Redis 地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_PASSWORD` | `""` | Redis 密码（留空表示无密码） |

## API 端点

- **`/`** - 前端页面
- **`/upload`** - 接收本地上传 (POST)
- **`/stream`** - SSE 数据流
- **`/status`** - 系统状态
- **`/health`** - 健康检查
- **`/reset`** - 重置统计数据

## 文件说明

- **cloud_bridge.py** - 主服务
- **gun.py** - Gunicorn 配置
- **Dockerfile** - Docker 部署
- **pyproject.toml** - 依赖
- **html/frontend.html** - 前端界面

## 测试

```bash
# 测试上传
curl -X POST http://localhost:5001/upload \
  -H "Content-Type: application/json" \
  -d '{"heart_rate": 75, "device_address": "F9:C6:2B:B9:A4"}'

# 查看状态
curl http://localhost:5001/status
```

## 访问

```
http://服务器IP:5001
```

---

**完整文档**: 查看上级目录的 `README.md`
