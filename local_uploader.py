# 小米手环心率 - 本地数据上传程序
#
# 功能：读取手环心率 + 监控前台窗口标题，通过 HTTP POST 上传到云服务器
# 运行：uv run python local_uploader.py
#
# 架构：
#   本地 Windows (手环) → BLE → 本地 Python → HTTP POST → 云服务器
#   本地 Windows (窗口) → ctypes → 本地 Python → HTTP POST → 云服务器
#
import asyncio
import ctypes
import ctypes.wintypes
import os
import threading
import requests
from datetime import datetime
from bleak import BleakClient
import sys
import io

# ==================== 配置 ====================

# 手环配置
DEVICE_ADDRESS = os.getenv("MI_BAND_ADDRESS", "F9:C6:02:2B:B9:A4")
HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_CHAR = "00002a37-0000-1000-8000-00805f9b34fb"

# 云端配置
CLOUD_URL = os.getenv("CLOUD_URL", "https://miband.ranjyaa.top/upload")
CLOUD_WINDOW_URL = os.getenv("CLOUD_WINDOW_URL", "https://miband.ranjyaa.top/upload_window")

# 连接配置
CONNECT_TIMEOUT = 10
RETRY_INTERVAL = 5

# 全局状态
total_uploaded = 0
upload_failures = 0
current_window_title = ""  # 当前窗口标题，心率上传时附带
window_lock = threading.Lock()
stop_event = threading.Event()


# ==================== Windows 窗口监控 ====================
user32 = ctypes.windll.user32


def get_foreground_window_title():
    """用 ctypes 获取当前前台窗口标题"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def upload_window_event(title, started_at, ended_at, duration):
    """上传窗口切换事件到云端"""
    payload = {
        "window_title": title,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration": round(duration, 1),
    }
    try:
        resp = requests.post(CLOUD_WINDOW_URL, json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"[窗口] ↑ \"{title[:40]}\" ({duration:.0f}s)")
        else:
            print(f"[窗口] ✗ 上传失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"[窗口] ✗ 上传错误: {e}")


def window_monitor():
    """后台线程：每秒轮询前台窗口，窗口变化时上传切换事件"""
    global current_window_title

    last_title = get_foreground_window_title()
    last_started = datetime.now()

    with window_lock:
        current_window_title = last_title

    print(f"[窗口] 监控启动，当前: \"{last_title[:50]}\"")

    while not stop_event.is_set():
        try:
            title = get_foreground_window_title()

            if title != last_title and title:  # 窗口切换了
                now = datetime.now()
                duration = (now - last_started).total_seconds()

                # 上传上一个窗口的使用记录（至少停留1秒才记录）
                if last_title and duration >= 1.0:
                    upload_window_event(
                        last_title,
                        last_started.isoformat(),
                        now.isoformat(),
                        duration,
                    )

                last_title = title
                last_started = now

                with window_lock:
                    current_window_title = title

        except Exception as e:
            print(f"[窗口] 轮询错误: {e}")

        stop_event.wait(1)  # 每秒检查一次


# ==================== 心率数据处理 ====================
def heart_rate_callback(sender, data):
    """BLE 心率回调 - 解析并上传到云端"""
    global total_uploaded, upload_failures

    try:
        # 解析心率数据
        if len(data) >= 2:
            flags = data[0]
            if flags & 0x01:  # uint16
                heart_rate = data[1] | (data[2] << 8)
            else:  # uint8
                heart_rate = data[1]

            # 获取当前窗口标题
            with window_lock:
                window = current_window_title

            # 构建数据包（附带当前窗口标题）
            payload = {
                "heart_rate": heart_rate,
                "device_address": DEVICE_ADDRESS,
                "timestamp": datetime.now().isoformat(),
                "platform": "windows",
                "current_window": window,
            }

            # 上传到云端
            try:
                response = requests.post(
                    CLOUD_URL,
                    json=payload,
                    timeout=5,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    total_uploaded += 1
                    upload_failures = 0
                    result = response.json()
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm"
                        f" | ✓ 上传 (总数: {total_uploaded})"
                    )
                else:
                    upload_failures += 1
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm"
                        f" | ✗ HTTP {response.status_code}"
                    )

            except requests.exceptions.ConnectionError:
                upload_failures += 1
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm"
                    f" | ✗ 连接失败"
                )
            except Exception as e:
                upload_failures += 1
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm"
                    f" | ✗ {e}"
                )

    except Exception as e:
        print(f"[心率解析] 错误: {e}")


# ==================== BLE 管理 ====================
async def ble_monitor():
    """主监控循环：连接手环"""
    global total_uploaded

    print(f"[BLE] 设备地址: {DEVICE_ADDRESS}")
    print(f"[BLE] 心率上传: {CLOUD_URL}")
    print(f"[BLE] 窗口上传: {CLOUD_WINDOW_URL}")
    print("=" * 60)
    print()

    retry_count = 0
    max_retries = 3

    while True:
        try:
            print(f"[BLE] 尝试连接设备... (重试 {retry_count})")
            async with BleakClient(DEVICE_ADDRESS, timeout=CONNECT_TIMEOUT) as client:
                retry_count = 0
                print(f"[BLE] ✓ 连接成功!")
                print(f"[BLE]  设备: {client.name or 'Unknown'}")
                print(f"[BLE]  地址: {client.address}")

                # 订阅心率通知
                print(f"[BLE] 订阅心率特征...")
                await client.start_notify(HEART_RATE_CHAR, heart_rate_callback)
                print(f"[BLE] ✓ 开始接收并上传数据")
                print("=" * 60)

                # 保持连接
                while client.is_connected:
                    await asyncio.sleep(5)
                    if total_uploaded > 0 and total_uploaded % 30 == 0:
                        print(f"[状态] 已上传 {total_uploaded} 条数据")

                print(f"[BLE] 设备已断开")

        except asyncio.TimeoutError:
            print(f"[BLE] 连接超时 ({CONNECT_TIMEOUT}s)")
            retry_count += 1

        except Exception as e:
            print(f"[BLE] 连接错误: {e}")
            retry_count += 1

        finally:
            if retry_count >= max_retries:
                print(f"\n[严重] 达到最大重试次数 ({max_retries})")
                print("请检查:")
                print("  1. 手环已开启并靠近电脑")
                print("  2. 蓝牙已启用")
                print("  3. 设备地址是否正确")
                print("  4. 如首次使用，需先配对")
                break

        if retry_count < max_retries:
            print(f"[BLE] {RETRY_INTERVAL} 秒后重试...")
            await asyncio.sleep(RETRY_INTERVAL)


# ==================== 主程序 ====================
def main():
    """主入口"""
    print("=" * 60)
    print("小米手环心率 - 本地上传程序 (含窗口监控)")
    print("=" * 60)
    print(f"设备: {DEVICE_ADDRESS}")
    print(f"心率: {CLOUD_URL}")
    print(f"窗口: {CLOUD_WINDOW_URL}")
    print("=" * 60)
    print()

    # Windows UTF-8 输出支持
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # 启动窗口监控后台线程
    wt = threading.Thread(target=window_monitor, daemon=True)
    wt.start()

    # 运行 BLE 监控
    try:
        asyncio.run(ble_monitor())
    except KeyboardInterrupt:
        print("\n\n正在关闭...")
        stop_event.set()
        print(f"最终统计: 已上传 {total_uploaded} 条心率数据")
        print("程序已退出")


if __name__ == "__main__":
    main()
