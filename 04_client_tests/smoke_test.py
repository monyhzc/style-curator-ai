# -*- coding: utf-8 -*-
"""
smoke_test.py - 生产服务全链路自动化冒烟自检工具
部署完成后运行该脚本，自动测试：健康探测、鉴权拦截、单图打分、异步批处理队列。

用法：
  python smoke_test.py
  python smoke_test.py --url http://127.0.0.1:11451 --token your_token
"""

import sys
import time
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def print_result(name: str, passed: bool, detail: str = ""):
    mark = "✅ [PASS]" if passed else "❌ [FAIL]"
    print(f"{mark} {name}")
    if detail:
        print(f"       详情: {detail}")

def main():
    parser = argparse.ArgumentParser(description="选款 AI 生产服务自动化冒烟检测")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:11451", help="服务基础 URL")
    parser.add_argument("--token", type=str, default=None, help="鉴权 Token")
    parser.add_argument("--image_url", type=str, default="http://127.0.0.1:18889/sample_tshirt.jpg", help="测试图片 URL")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    token = args.token or "jw_style_audit_prod_token_2026"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    session = requests.Session()
    session.trust_env = False  # 避免被系统 socks 代理拦截本地回环

    print("==================================================")
    print("🧪 Style Curator AI - 生产服务冒烟自动化测试")
    print(f"• 目标地址: {base_url}")
    print(f"• 鉴权认证: Bearer {token[:6]}***")
    print(f"• 测试样张: {args.image_url}")
    print("==================================================\n")

    # 1. 根路由连通性
    try:
        r = session.get(f"{base_url}/", timeout=3.0)
        print_result("1. 服务连通性检测", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        print_result("1. 服务连通性检测", False, str(e))
        print("\n❌ 服务未启动或端口不可达，请先通过 ./service.sh start 启动服务。")
        sys.exit(1)

    # 2. 鉴权防御拦截 (未传 Token 应返回 401)
    try:
        r = session.post(f"{base_url}/api/analyze", json={"image_url": args.image_url}, timeout=3.0)
        print_result("2. 401 未授权防御拦截", r.status_code == 401, f"无 Token 请求正确被拦截 (HTTP {r.status_code})")
    except Exception as e:
        print_result("2. 401 未授权防御拦截", False, str(e))

    # 3. 单图风格分析打分 (POST /api/analyze)
    t0 = time.time()
    try:
        payload = {"image_url": args.image_url, "task": "Z+"}
        r = session.post(f"{base_url}/api/analyze", json=payload, headers=headers, timeout=10.0)
        latency = round((time.time() - t0) * 1000, 1)
        if r.status_code == 200:
            data = r.json()
            prob = data.get("probability")
            print_result("3. 单图端到端打分接口", True, f"品牌: Z+ | 置信度: {prob} | 端到端耗时: {latency}ms")
        else:
            print_result("3. 单图端到端打分接口", False, f"HTTP {r.status_code} - {r.text}")
    except Exception as e:
        print_result("3. 单图端到端打分接口", False, str(e))

    # 4. 异步批处理任务提交与轮询 (POST /api/analyze/batch -> GET /api/analyze/batch/{id})
    try:
        payload = {"urls": [args.image_url, args.image_url], "task": "LIFE"}
        r = session.post(f"{base_url}/api/analyze/batch", json=payload, headers=headers, timeout=5.0)
        if r.status_code == 200:
            batch_id = r.json().get("batch_id")
            time.sleep(1.5)  # 等待后台线程处理
            poll_r = session.get(f"{base_url}/api/analyze/batch/{batch_id}", headers=headers, timeout=5.0)
            poll_data = poll_r.json()
            status_str = poll_data.get("status")
            completed = poll_data.get("completed", 0)
            print_result("4. 异步批量打分与轮询", status_str == "completed", f"批次: {batch_id} | 状态: {status_str} | 已完成: {completed}/2")
        else:
            print_result("4. 异步批量打分与轮询", False, f"提交失败 HTTP {r.status_code}")
    except Exception as e:
        print_result("4. 异步批量打分与轮询", False, str(e))

    print("\n🎉 自动化冒烟测试执行完毕！")

if __name__ == "__main__":
    main()
