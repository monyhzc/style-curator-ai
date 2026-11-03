# -*- coding: utf-8 -*-
"""
predict.py - 阶段四：命令行快速离线打分工具
用法：
  python 04_client_tests/predict.py --image sample.jpg --brand Z+
  python 04_client_tests/predict.py --dir ./images/ --brand LIFE
"""

import sys
import argparse
from pathlib import Path
from PIL import Image

# 自动寻址 02_model
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "02_model"))
from core import StyleEngine

def main():
    parser = argparse.ArgumentParser(description="选款 AI 快速打分工具")
    parser.add_argument("--image", type=str, help="待评测单张图片路径")
    parser.add_argument("--dir", type=str, help="待评测图片文件夹路径")
    parser.add_argument("--brand", type=str, default="LIFE", help="目标品牌 (LIFE, Z+, OUTDOOR, MAIN, JEANS, JNR, JKIDS, JSPORT)")
    parser.add_argument("--patch_dir", type=str, default=None, help="增量权重目录 (默认: ./patch)")
    args = parser.parse_args()

    engine = StyleEngine.get_instance(patch_dir=args.patch_dir)

    if args.image:
        img = Image.open(args.image).convert("RGB")
        score = engine.predict_one(img, args.brand)
        level = "非常符合" if score >= 0.8 else ("中度符合" if score >= 0.3 else "不符合")
        print(f"[{args.brand}] {args.image} -> 得分: {score:.4f} ({level})")

    elif args.dir:
        p = Path(args.dir)
        files = [f for f in sorted(p.iterdir()) if f.suffix.lower() in [".jpg", ".png", ".webp", ".jpeg"]]
        print(f"正在评测 {p} 下的 {len(files)} 张图片 (品牌: {args.brand})...\n")
        items = [(Image.open(f).convert("RGB"), args.brand) for f in files]
        scores = engine.predict(items)
        for f, s in zip(files, scores):
            level = "非常符合" if s >= 0.8 else ("中度符合" if s >= 0.3 else "不符合")
            print(f"• {f.name:25s} | 评分: {s:.4f} | 判定: {level}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
