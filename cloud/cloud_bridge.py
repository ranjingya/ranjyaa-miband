# 小米手环心率 - 云端 Flask 桥接服务
# 功能：接收心率+窗口数据 → JSON持久化 → SSE推送 → LangChain Agent聊天
# 部署：云服务器运行，本地通过 HTTP POST 上传数据
import os
import json
import time
import atexit
import threading
from datetime import datetime
from flask import Flask, Response, jsonify, stream_with_context, request
from agent import init_agent, stream_agent

# ==================== 配置 ====================
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", 5001))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

# 数据限制
HR_HISTORY_MAX = 500
WINDOW_HISTORY_MAX = 200
SAVE_INTERVAL = 30  # 秒，定时写盘间隔

# ==================== 数据存储 ====================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HR_FILE = os.path.join(DATA_DIR, "hr_history.json")
WINDOW_FILE = os.path.join(DATA_DIR, "window_history.json")

# 全局状态
last_data = {}
data_count = 0
active_clients = 0
current_window = ""
hr_history = []       # [{hr, timestamp, window}, ...]  最近500条
window_history = []   # [{title, started_at, ended_at, duration}, ...]  最近200条
lock = threading.Lock()
stop_event = threading.Event()


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_data():
    """启动时从JSON文件加载历史数据"""
    global hr_history, window_history
    ensure_data_dir()
    try:
        if os.path.exists(HR_FILE):
            with open(HR_FILE, "r", encoding="utf-8") as f:
                hr_history = json.load(f)
            print(f"[数据] 加载心率历史: {len(hr_history)} 条")
    except Exception as e:
        print(f"[数据] 心率加载失败: {e}")
        hr_history = []

    try:
        if os.path.exists(WINDOW_FILE):
            with open(WINDOW_FILE, "r", encoding="utf-8") as f:
                window_history = json.load(f)
            print(f"[数据] 加载窗口历史: {len(window_history)} 条")
    except Exception as e:
        print(f"[数据] 窗口加载失败: {e}")
        window_history = []


def save_data():
    """将历史数据写入JSON文件"""
    ensure_data_dir()
    try:
        with lock:
            hr_snap = list(hr_history)
            win_snap = list(window_history)
        with open(HR_FILE, "w", encoding="utf-8") as f:
            json.dump(hr_snap, f, ensure_ascii=False)
        with open(WINDOW_FILE, "w", encoding="utf-8") as f:
            json.dump(win_snap, f, ensure_ascii=False)
    except Exception as e:
        print(f"[数据] 写盘失败: {e}")


def periodic_save():
    """后台定时写盘"""
    while not stop_event.is_set():
        stop_event.wait(SAVE_INTERVAL)
        if not stop_event.is_set():
            save_data()


# ==================== Flask 应用 ====================
app = Flask(__name__)


@app.route("/")
def index():
    """返回前端页面"""
    html_path = os.path.join(os.path.dirname(__file__), "./html/frontend.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>心率监测服务运行中</h1><p>请确保 ./html/frontend.html 文件存在</p>"


@app.route("/upload", methods=["POST"])
def upload():
    """接收心率数据"""
    global last_data, data_count, current_window
    try:
        data = request.get_json(force=True)
        if not data or "heart_rate" not in data:
            return jsonify({"error": "需要 heart_rate"}), 400

        data["server_timestamp"] = datetime.now().isoformat()
        data["server_time_ms"] = int(time.time() * 1000)

        with lock:
            last_data = data
            data_count += 1

            # 更新当前窗口
            win = data.get("current_window", "")
            if win:
                current_window = win

            # 存入心率历史
            hr_history.append({
                "hr": data["heart_rate"],
                "timestamp": data.get("timestamp", data["server_timestamp"]),
                "window": win,
            })
            # 限制条数
            while len(hr_history) > HR_HISTORY_MAX:
                hr_history.pop(0)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ↑ {data.get('heart_rate')} bpm | {win[:30] if win else '-'}")
        return jsonify({"status": "ok", "data_count": data_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload_window", methods=["POST"])
def upload_window():
    """接收窗口切换事件"""
    global current_window
    try:
        data = request.get_json(force=True)
        if not data or "window_title" not in data:
            return jsonify({"error": "需要 window_title"}), 400

        with lock:
            window_history.append({
                "title": data["window_title"],
                "started_at": data.get("started_at", ""),
                "ended_at": data.get("ended_at", ""),
                "duration": data.get("duration", 0),
            })
            while len(window_history) > WINDOW_HISTORY_MAX:
                window_history.pop(0)

            # 更新当前窗口（最新的窗口标题来自心率上传的current_window，
            # 但这里记录的是刚刚结束的窗口，不更新current_window）

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 窗口: \"{data['window_title'][:40]}\" ({data.get('duration', 0):.0f}s)")
        return jsonify({"status": "ok", "window_count": len(window_history)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stream")
def stream():
    """SSE推送"""
    def event_stream():
        global active_clients
        active_clients += 1

        with lock:
            if last_data:
                d = dict(last_data)
                d["active_clients"] = active_clients
                d["current_window"] = current_window
                yield f"data: {json.dumps(d)}\n\n"

        last_sent = 0
        count = 0
        while not stop_event.is_set():
            try:
                with lock:
                    if last_data and last_data.get("server_time_ms", 0) > last_sent:
                        last_sent = last_data["server_time_ms"]
                        d = dict(last_data)
                        d["active_clients"] = active_clients
                        d["current_window"] = current_window
                        yield f"data: {json.dumps(d)}\n\n"
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
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/chat", methods=["POST"])
def chat():
    """Agent 聊天 — 流式 SSE 返回"""
    try:
        data = request.get_json(force=True)
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "需要 message"}), 400

        def generate():
            for event in stream_agent(message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/status")
def status():
    return jsonify({
        "data_count": data_count,
        "active_clients": active_clients,
        "current_window": current_window,
        "hr_history_count": len(hr_history),
        "window_history_count": len(window_history),
        "last_data": last_data,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "count": data_count})


@app.route("/reset", methods=["POST"])
def reset():
    global last_data, data_count, current_window
    with lock:
        last_data = {}
        data_count = 0
        current_window = ""
        hr_history.clear()       # .clear() 保持引用不变，agent 仍指向同一个 list
        window_history.clear()
    save_data()
    return jsonify({"message": "已重置"})


# ==================== 启动 ====================
load_data()

# 定时写盘线程
save_thread = threading.Thread(target=periodic_save, daemon=True)
save_thread.start()

# 优雅退出写盘
atexit.register(save_data)


def get_current_window():
    """当前窗口标题 getter（agent 通过此函数读取）"""
    with lock:
        return current_window


# 初始化 LangChain Agent（传入共享数据引用）
init_agent(
    api_key=MINIMAX_API_KEY,
    hr_history=hr_history,
    window_history=window_history,
    get_current_window=get_current_window,
    lock=lock,
)

print("=" * 60)
print("小米手环 - 云端桥接服务")
print(f"服务: {FLASK_HOST}:{FLASK_PORT}")
print(f"Agent: {'已配置' if MINIMAX_API_KEY else '未配置 (设置 MINIMAX_API_KEY)'}")
print(f"数据: {DATA_DIR}")
print("=" * 60)
