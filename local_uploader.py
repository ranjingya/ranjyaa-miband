# 小米手环心率 - 本地数据上传程序
#
# 功能：读取手环心率，通过 HTTP POST 上传到云服务器
# 运行：uv run python local_uploader.py
#
# 架构：
#   本地 Windows (手环) → BLE → 本地 Python → HTTP POST → 云服务器
#
import asyncio
import os
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

# 连接配置
CONNECT_TIMEOUT = 10
RETRY_INTERVAL = 5

# 全局状态
total_uploaded = 0
upload_failures = 0


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

            # 构建数据包
            payload = {
                "heart_rate": heart_rate,
                "device_address": DEVICE_ADDRESS,
                "timestamp": datetime.now().isoformat(),
                "platform": "windows"
            }

            # 上传到云端
            try:
                response = requests.post(
                    CLOUD_URL,
                    json=payload,
                    timeout=5,
                    headers={'Content-Type': 'application/json'}
                )

                if response.status_code == 200:
                    total_uploaded += 1
                    upload_failures = 0
                    result = response.json()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm | ✓ 上传成功 (总数: {total_uploaded}, 云端: {result.get('data_count', 'N/A')})")
                else:
                    upload_failures += 1
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm | ✗ 上传失败: HTTP {response.status_code}")

            except requests.exceptions.ConnectionError:
                upload_failures += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm | ✗ 连接失败: 无法访问 {CLOUD_URL}")
            except Exception as e:
                upload_failures += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ↓ {heart_rate} bpm | ✗ 错误: {e}")

    except Exception as e:
        print(f"[心率解析] 错误: {e}")


# ==================== BLE 管理 ====================
async def ble_monitor():
    """主监控循环：连接手环"""
    global total_uploaded

    print(f"[BLE] 设备地址: {DEVICE_ADDRESS}")
    print(f"[BLE] 云端上传: {CLOUD_URL}")
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
                    # 每 30 秒显示一次统计
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
    print("小米手环心率 - 本地上传程序")
    print("=" * 60)
    print(f"设备: {DEVICE_ADDRESS}")
    print(f"云端: {CLOUD_URL}")
    print("=" * 60)
    print()

    # Windows UTF-8 输出支持
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # 运行 BLE 监控
    try:
        asyncio.run(ble_monitor())
    except KeyboardInterrupt:
        print("\n\n正在关闭...")
        print(f"最终统计: 已上传 {total_uploaded} 条数据")
        print("程序已退出")


if __name__ == "__main__":
    main()
