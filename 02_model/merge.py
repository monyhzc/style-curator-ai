# -*- coding: utf-8 -*-
"""
merge.py - 官方 Qwen 基座与增量 LoRA 权重一键融合脚本
将官方下载的原版 Qwen3.5-9B 与 138MB 增量包物理叠加，生成免 PEFT 依赖的完整单体模型。

用法：
  python merge.py --base ./Qwen3.5-9B --patch ./patch --out ./qwen_style_merged
"""

import shutil
import argparse
from pathlib import Path
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
from peft import PeftModel

def main():
    parser = argparse.ArgumentParser(description="官方 Qwen 基座与增量包融合工具")
    parser.add_argument("--base", type=str, default="./Qwen3.5-9B", help="官方 Qwen3.5-9B 模型目录")
    parser.add_argument("--patch", type=str, default="./patch", help="解压后的 138MB 增量包目录")
    parser.add_argument("--out", type=str, default="./qwen_style_merged", help="合并后完整模型的输出目录")
    args = parser.parse_args()

    base_dir = Path(args.base)
    patch_dir = Path(args.patch)
    out_dir = Path(args.out)

    print(f"==================================================")
    print(f"🧩 启动模型权重物理融合")
    print(f"• 官方基座: {base_dir}")
    print(f"• 增量补丁: {patch_dir}")
    print(f"• 输出路径: {out_dir}")
    print(f"==================================================\n")

    print("⏳ [1/4] 正在加载官方 Qwen3.5-9B 基座...")
    base_model = AutoModelForImageTextToText.from_pretrained(
        base_dir,
        torch_dtype=torch.bfloat16,
        device_map="cpu"
    )

    lora_dir = patch_dir / "lora_weights" if (patch_dir / "lora_weights").exists() else patch_dir
    print(f"⏳ [2/4] 正在挂载增量 LoRA: {lora_dir}")
    lora_model = PeftModel.from_pretrained(base_model, str(lora_dir))

    print("⏳ [3/4] 正在执行权重数学叠加 (merge_and_unload)...")
    merged_model = lora_model.merge_and_unload()

    print(f"⏳ [4/4] 正在导出独立完整权重至: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_model.save_pretrained(str(out_dir), safe_serialization=True)

    # 附带保存处理器和打分头
    try:
        proc = AutoProcessor.from_pretrained(base_dir)
        proc.save_pretrained(str(out_dir))
    except Exception:
        pass

    head_path = patch_dir / "classifier_head.pt"
    if head_path.exists():
        shutil.copy(head_path, out_dir / "classifier_head.pt")

    print("\n✅ 融合成功！客户可以直接使用该完整模型，无需再加载 PEFT。")

if __name__ == "__main__":
    main()
