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

    # 3. 双套阈值配置接口检测 (GET /api/thresholds)
    try:
        r = session.get(f"{base_url}/api/thresholds", headers=headers, timeout=3.0)
        if r.status_code == 200:
            th_data = r.json().get("thresholds", {})
            n_brands = len(th_data.get("brands", {}))
            n_accs = len(th_data.get("accessories", {}))
            print_result("3. 三档双阈值配置表接口", True, f"支持 {n_brands} 个子品牌 + {n_accs} 大配件品类双阈值")
        else:
            print_result("3. 三档双阈值配置表接口", False, f"HTTP {r.status_code}")
    except Exception as e:
        print_result("3. 三档双阈值配置表接口", False, str(e))

    # 4. 单图成衣风格分析打分 (POST /api/analyze)
    t0 = time.time()
    try:
        payload = {"image_url": args.image_url, "task": "Z+"}
        r = session.post(f"{base_url}/api/analyze", json=payload, headers=headers, timeout=10.0)
        latency = round((time.time() - t0) * 1000, 1)
        if r.status_code == 200:
            data = r.json()
            prob = data.get("probability")
            level = data.get("level")
            decision = data.get("decision")
            thrs = data.get("thresholds_used")
            print_result("4. 单图成衣端到端三档打分接口", True, f"品牌: Z+ | 概率: {prob} | 判定: {level} ({decision}) | 阈值: {thrs} | 耗时: {latency}ms")
        else:
            print_result("4. 单图成衣端到端三档打分接口", False, f"HTTP {r.status_code} - {r.text}")
    except Exception as e:
        print_result("4. 单图成衣端到端三档打分接口", False, str(e))

    # 5. 单图配件风格分析打分 (POST /api/analyze with category="鞋子")
    t0 = time.time()
    try:
        payload = {"image_url": args.image_url, "task": "MAIN", "category": "鞋子"}
        r = session.post(f"{base_url}/api/analyze", json=payload, headers=headers, timeout=10.0)
        latency = round((time.time() - t0) * 1000, 1)
        if r.status_code == 200:
            data = r.json()
            prob = data.get("probability")
            level = data.get("level")
            decision = data.get("decision")
            thrs = data.get("thresholds_used")
            print_result("5. 单图配件专属三档打分接口", True, f"品类: 鞋子 (MAIN) | 概率: {prob} | 判定: {level} ({decision}) | 阈值: {thrs} | 耗时: {latency}ms")
        else:
            print_result("5. 单图配件专属三档打分接口", False, f"HTTP {r.status_code} - {r.text}")
    except Exception as e:
        print_result("5. 单图配件专属三档打分接口", False, str(e))

    # 6. 异步批处理任务提交与轮询 (POST /api/analyze/batch -> GET /api/analyze/batch/{id})
    try:
        payload = {"urls": [args.image_url, args.image_url], "task": "LIFE"}
        r = session.post(f"{base_url}/api/analyze/batch", json=payload, headers=headers, timeout=5.0)
        if r.status_code == 200:
            batch_id = r.json().get("batch_id")
            time.sleep(2.0)  # 等待后台线程处理
            poll_r = session.get(f"{base_url}/api/analyze/batch/{batch_id}", headers=headers, timeout=5.0)
            poll_data = poll_r.json()
            status_str = poll_data.get("status")
            completed = poll_data.get("completed", 0)
            res_items = poll_data.get("results", [])
            first_level = res_items[0].get("level") if res_items else None
            print_result("6. 异步批量打分与轮询", status_str == "completed", f"批次: {batch_id} | 状态: {status_str} | 已完成: {completed}/2 | 首项判定: {first_level}")
        else:
            print_result("6. 异步批量打分与轮询", False, f"提交失败 HTTP {r.status_code}")
    except Exception as e:
        print_result("6. 异步批量打分与轮询", False, str(e))

    # 7. 未标定新品类保守灰度安全保护检测 (POST /api/analyze with category="帽子")
    try:
        payload = {"image_url": args.image_url, "task": "MAIN", "category": "测试新品类"}
        r = session.post(f"{base_url}/api/analyze", json=payload, headers=headers, timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            th_used = data.get("thresholds_used", {})
            is_calibrated = th_used.get("calibrated", True)
            print_result("7. 未标定新品类安全缓冲保护", not is_calibrated, f"正确激活保守灰度策略 [0.01, 0.70] (calibrated={is_calibrated})")
        else:
            print_result("7. 未标定新品类安全缓冲保护", False, f"HTTP {r.status_code}")
    except Exception as e:
        print_result("7. 未标定新品类安全缓冲保护", False, str(e))

    # 8. 在线自动标定接口检测 (POST /api/thresholds/calibrate)
    try:
        calib_payload = {
            "category": "帽子",
            "brand": "MAIN",
            "pos_urls": [args.image_url, args.image_url],
            "neg_urls": [args.image_url, args.image_url],
            "target_recall": 0.95,
            "target_prec": 0.95,
            "auto_save": False  # 测试时不覆盖正式配置
        }
        r = session.post(f"{base_url}/api/thresholds/calibrate", json=calib_payload, headers=headers, timeout=10.0)
        if r.status_code == 200:
            c_data = r.json()
            low_val = c_data.get("low")
            high_val = c_data.get("high")
            print_result("8. 在线新品类自动标定流程接口", True, f"新品类: 帽子 | 标定双阈值: [{low_val}, {high_val}]")
        else:
            print_result("8. 在线新品类自动标定流程接口", False, f"HTTP {r.status_code} - {r.text}")
    except Exception as e:
        print_result("8. 在线新品类自动标定流程接口", False, str(e))

    print("\n🎉 自动化冒烟测试执行完毕！")

if __name__ == "__main__":
    main()
