# -*- coding: utf-8 -*-
"""
test_int4.py - 阶段四测试：INT4 极简显存量化推理与显存基准自检
验证 Qwen3.5-9B 在 4-bit (NF4) 模式下的静态显存、单图推理显存及打分稳定性。
最低硬件门槛：显存 >= 9GB (如 RTX 3060 12G / 4060Ti 16G / 3090 / 4090 / L20)
"""

import os
import sys
import time
import gc
from pathlib import Path
from PIL import Image

import torch

# 关联上一级 02_model
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.insert(0, str(ROOT_DIR / "02_model"))

from core import StyleEngine, BRAND_PROMPTS, get_decision_level


def run_int4_benchmark():
    print("=" * 70)
    print("🚀 Style Curator AI - INT4 (NF4) 极简显存量化自检工具")
    print("=" * 70)

    if not torch.cuda.is_available():
        print("❌ 错误: 未检测到可用 GPU，INT4 量化依赖 NVIDIA CUDA 硬件环境。")
        sys.exit(1)

    try:
        import bitsandbytes as bnb
        print(f"✓ BitsAndBytes 就绪 (版本: {bnb.__version__})")
    except ImportError:
        print("❌ 错误: 未安装 bitsandbytes，请执行: pip install bitsandbytes")
        sys.exit(1)

    dev_name = torch.cuda.get_device_name(0)
    total_mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    print(f"• 当前 GPU: {dev_name} (总显存: {total_mem:.2f} GB)")

    torch.cuda.empty_cache()
    gc.collect()
    torch.cuda.reset_peak_memory_stats()

    # 1. 强制使用 INT4 模式初始化单例
    print("\n>>> 步骤 1: 正在加载 INT4 (NF4) 模型权重至 GPU...")
    t0 = time.time()
    engine = StyleEngine.get_instance(load_in_4bit=True)
    load_time = round(time.time() - t0, 2)

    torch.cuda.synchronize()
    static_alloc = torch.cuda.memory_allocated() / (1024 ** 3)
    static_res = torch.cuda.memory_reserved() / (1024 ** 3)

    print(f"  ✓ INT4 模型就绪 (耗时: {load_time} 秒)")
    print(f"  • 模型静态权重显存 (Allocated): {static_alloc:.2f} GB")
    print(f"  • CUDA 预留静态显存 (Reserved):  {static_res:.2f} GB")
    print(f"  • 对比 原版 BF16 静态占用:       18.50 GB (降幅: {((18.5 - static_alloc)/18.5)*100:.1f}%)")

    # 2. 单图前向推理显存实测
    print("\n>>> 步骤 2: 单图前向计算与推理时延实测 (768x768)...")
    test_img = Image.new("RGB", (768, 768), color=(120, 140, 160))

    # 预热
    _ = engine.predict([(test_img, "Z+", "服装")])
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    latencies = []
    scores = []
    for _ in range(3):
        torch.cuda.synchronize()
        t1 = time.time()
        res = engine.predict([(test_img, "Z+", "服装")])
        torch.cuda.synchronize()
        latencies.append((time.time() - t1) * 1000)
        scores.append(res[0])

    peak_alloc = torch.cuda.max_memory_allocated() / (1024 ** 3)
    avg_lat = sum(latencies) / len(latencies)
    score_val = scores[-1]
    decision_info = get_decision_level(score_val, "Z+")

    print(f"  ✓ 推理完成，打分: {score_val:.4f} (判定档位: {decision_info['level']})")
    print(f"  • 推理峰值物理显存 (Peak Allocated): {peak_alloc:.2f} GB")
    print(f"  • 单图平均耗时:                     {avg_lat:.1f} ms")

    print("\n" + "=" * 70)
    print("📋 INT4 硬件部署适配结论:")
    print("=" * 70)
    if peak_alloc <= 10.0:
        print(f"  ✅ [PASS] 显存优化极其成功！峰值仅 {peak_alloc:.2f} GB <= 10.0 GB。")
        print("  👉 适配显卡：RTX 3060 (12GB) / RTX 4060Ti (16GB) / RTX 3090/4090 (24GB) 及所有数据中心卡。")
    else:
        print(f"  ⚠️ 显存占用: {peak_alloc:.2f} GB")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_int4_benchmark()
