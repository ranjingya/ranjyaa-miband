# 小米手环心率 - 云端 Flask 桥接服务
# 功能：接收本地上传的心率数据，并向前端提供 SSE
# 部署：云服务器运行，本地通过 HTTP POST 上传数据
import os
import json
import time
import threading
from datetime import datetime
from flask import Flask, Response, jsonify, stream_with_context, request
import redis

# ==================== 配置 ====================
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", 5001))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# Redis 配置
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_HOST = os.getenv("REDIS_HOST", "172.17.0.2")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "ranjing233") 
REDIS_DATABASE = int(os.getenv("REDIS_DATABASE", 0))
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "miband:heart_rate")

# 全局状态
last_data = {}
data_count = 0
active_clients = 0
redis_connected = False
redis_client = None
lock = threading.Lock()
stop_event = threading.Event()

# ==================== Redis 管理 ====================
def init_redis():
    global redis_client, redis_connected
    if not REDIS_ENABLED:
        print("[Redis] 已禁用")
        return False
    try:
        print(f"[Redis] 连接 {REDIS_HOST}:{REDIS_PORT}, db={REDIS_DATABASE}")
        # 密码为空时不传递
        redis_kwargs = {
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "db": REDIS_DATABASE,
            "decode_responses": True
        }
        if REDIS_PASSWORD:
            redis_kwargs["password"] = REDIS_PASSWORD

        redis_client = redis.Redis(**redis_kwargs)
        redis_client.ping()
        info = redis_client.info()
        redis_connected = True
        print(f"[Redis] ✓ 成功 v{info.get('redis_version', 'unknown')}")
        return True
    except Exception as e:
        redis_connected = False
        print(f"[Redis] ✗ 失败: {e}")
        return False

def publish_to_redis(data):
    global redis_connected
    if not REDIS_ENABLED:
        return False
    if not redis_connected:
        if not init_redis():
            return False
    try:
        redis_client.publish(REDIS_CHANNEL, json.dumps(data, ensure_ascii=False))
        return True
    except Exception as e:
        redis_connected = False
        return False

def redis_reconnect_loop():
    while not stop_event.is_set():
        if REDIS_ENABLED and not redis_connected:
            init_redis()
            time.sleep(10)
        else:
            time.sleep(5)

# ==================== Flask 应用 ====================
app = Flask(__name__)

@app.route('/')
def index():
    """返回前端页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), './html/frontend.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    return """
    <html>
    <body>
    <h1>心率监测服务运行中</h1>
    <p>请确保 ./html/frontend.html 文件存在</p>
    <p>访问: http://服务器IP:5001</p>
    </body>
    </html>
    """

@app.route('/upload', methods=['POST'])
def upload():
    global last_data, data_count
    try:
        data = request.get_json(force=True)
        if not data or 'heart_rate' not in data:
            return jsonify({"error": "需要 heart_rate"}), 400

        data['server_timestamp'] = datetime.now().isoformat()
        data['server_time_ms'] = int(time.time() * 1000)

        with lock:
            last_data = data
            data_count += 1

        if REDIS_ENABLED:
            publish_to_redis(data)
            status_remote = "published"
        else:
            status_remote = "direct"

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ↑ {data.get('heart_rate')} bpm ({status_remote})")
        return jsonify({"status": "ok", "data_count": data_count, "redis": status_remote})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stream')
def stream():
    def event_stream():
        global active_clients
        active_clients += 1
        if last_data:
            # 添加连接数到数据中
            data_with_clients = dict(last_data)
            data_with_clients['active_clients'] = active_clients
            yield f"data: {json.dumps(data_with_clients)}\n\n"

        last_sent = 0
        count = 0
        while not stop_event.is_set():
            try:
                with lock:
                    if last_data and last_data.get('server_time_ms', 0) > last_sent:
                        last_sent = last_data['server_time_ms']
                        # 添加连接数到数据中
                        data_with_clients = dict(last_data)
                        data_with_clients['active_clients'] = active_clients
                        yield f"data: {json.dumps(data_with_clients)}\n\n"
                        count = 0
                time.sleep(0.5)
                count += 1
                if count >= 30:
                    yield ": heartbeat\n\n"
                    count = 0
            except GeneratorExit:
                break
        active_clients -= 1

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Access-Control-Allow-Origin': '*'}
    )

@app.route('/status')
def status():
    return jsonify({
        "data_count": data_count,
        "active_clients": active_clients,
        "redis_enabled": REDIS_ENABLED,
        "redis_connected": redis_connected,
        "last_data": last_data,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
def health():
    return jsonify({"status": "ok", "redis": redis_connected, "count": data_count})

@app.route('/healthz')
def healthz():
    return "OK" if (data_count > 0 or not REDIS_ENABLED) else "Waiting", 200

@app.route('/reset', methods=['POST'])
def reset():
    global last_data, data_count
    with lock:
        last_data = {}
        data_count = 0
    return jsonify({"message": "已重置"})

# 初始化（gunicorn 启动时会执行）
if REDIS_ENABLED:
    # 启动 Redis 重连线程
    threading.Thread(target=redis_reconnect_loop, daemon=True).start()
    # 初始化 Redis 连接
    init_redis()

print("=" * 60)
print("小米手环 - 云端桥接服务")
print(f"服务启动: {FLASK_HOST}:{FLASK_PORT}")
print("Redis 状态:", "启用" if REDIS_ENABLED else "禁用")
print("=" * 60)
