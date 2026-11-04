# -*- coding: utf-8 -*-
"""
prepare_dataset.py - 从外部图片文件夹自动构建标注 JSONL 数据集
支持自动识别品牌、分类、正反例结构，切分生成 train.jsonl 与 val.jsonl。

常见支持的文件夹结构：
1. 品牌层级：
   my_dataset/
   ├── Z+/
   │   ├── T恤/*.jpg (默认为正例 label: 1)
   │   └── 反例/T恤/*.jpg (负例 label: 0)
   └── LIFE/
       ├── 外套/*.jpg (label: 1)
       └── 反例/外套/*.jpg (label: 0)

2. 扁平二分类层级：
   my_dataset/
   ├── positive/*.jpg (label: 1)
   └── negative/*.jpg (label: 0)

用法示例：
  python prepare_dataset.py --source_dir /path/to/new_photos --out_dir /path/to/save_jsonl --val_ratio 0.15
"""

import os
import json
import random
import argparse
from pathlib import Path
from typing import List, Dict, Any

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

def scan_dataset(source_dir: Path, default_brand: str = "LIFE") -> List[Dict[str, Any]]:
    records = []
    print(f"🔍 正在扫描目录: {source_dir} ...")

    for p in source_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        parts = p.relative_to(source_dir).parts
        # 默认推断标签
        is_negative = any("反例" in part or "negative" in part.lower() or "bad" in part.lower() for part in parts)
        label = 0 if is_negative else 1

        # 尝试推断品牌
        brand = default_brand
        for b in ["JEANS", "JKIDS", "JNR", "JSPORT", "LIFE", "MAIN", "OUTDOOR", "Z+"]:
            if any(b.lower() == part.lower() for part in parts):
                brand = b
                break

        # 尝试推断品类
        category = "服饰"
        for cat in ["T恤", "外套", "长裤", "牛仔裤", "裙子", "毛衣", "卫衣", "衬衫", "短裤", "夹克"]:
            if any(cat in part for part in parts):
                category = cat
                break

        records.append({
            "abs_path": str(p.resolve()),
            "path": str(p.relative_to(source_dir)),
            "brand": brand,
            "category": category,
            "label": label
        })

    return records

def main():
    parser = argparse.ArgumentParser(description="外部图片数据集自动构建工具")
    parser.add_argument("--source_dir", type=str, required=True, help="待扫描的外部图片根目录路径")
    parser.add_argument("--out_dir", type=str, required=True, help="生成的 JSONL 文件输出目录")
    parser.add_argument("--val_ratio", type=float, default=0.15, help="验证集切分比例 (默认 0.15)")
    parser.add_argument("--brand", type=str, default="LIFE", help="当无法从路径推断时的默认品牌")
    parser.add_argument("--seed", type=int, default=42, help="随机切分种子")
    args = parser.parse_args()

    src = Path(args.source_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    records = scan_dataset(src, default_brand=args.brand)
    if not records:
        print(f"❌ 未在 {src} 中发现任何有效图片！")
        return

    random.seed(args.seed)
    random.shuffle(records)

    val_count = int(len(records) * args.val_ratio)
    val_set = records[:val_count]
    train_set = records[val_count:]

    train_file = out / "train.jsonl"
    val_file = out / "val.jsonl"

    with open(train_file, "w", encoding="utf-8") as f:
        for r in train_set:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(val_file, "w", encoding="utf-8") as f:
        for r in val_set:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pos_count = sum(1 for r in records if r["label"] == 1)
    neg_count = sum(1 for r in records if r["label"] == 0)

    print(f"\n✅ 数据集构建完毕！统计信息:")
    print(f"• 样本总数: {len(records)} (正例: {pos_count}, 负例: {neg_count})")
    print(f"• 训练集:   {len(train_set)} -> {train_file}")
    print(f"• 验证集:   {len(val_set)} -> {val_file}")

if __name__ == "__main__":
    main()
