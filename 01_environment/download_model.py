# -*- coding: utf-8 -*-
"""
download_model.py - 国内魔搭社区 (ModelScope) 官方基座模型一键下载工具
利用阿里国内高速 CDN 节点，无需翻墙直连满速下载 Qwen 系列大模型。

用法：
  python download_model.py --model Qwen/Qwen3.5-9B --local_dir ./weights/Qwen3.5-9B
"""

import os
import sys
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="ModelScope 国内高速基座模型下载工具")
    parser.add_argument("--model", type=str, default="Qwen/Qwen3.5-9B", help="ModelScope 模型库 ID (默认: Qwen/Qwen3.5-9B)")
    parser.add_argument("--local_dir", type=str, default="./weights/Qwen3.5-9B", help="本地保存目标路径 (默认: ./weights/Qwen3.5-9B)")
    parser.add_argument("--revision", type=str, default="master", help="模型版本分支 (默认: master)")
    parser.add_argument("--force", action="store_true", help="如果已存在是否强制覆盖重新下载")
    args = parser.parse_args()

    local_path = Path(args.local_dir).resolve()

    # 检查是否已存在完整模型
    if local_path.exists() and not args.force:
        has_config = (local_path / "config.json").exists()
        has_weights = any(local_path.glob("*.safetensors")) or any(local_path.glob("*.bin"))
        if has_config and has_weights:
            print(f"✅ 检测到本地已存在有效模型: {local_path}，跳过下载。")
            print("👉 如需强制重新下载，请添加 --force 参数。")
            return

    try:
        from modelscope import snapshot_download
    except ImportError:
        print("❌ 未安装 modelscope 库，请先执行: pip install modelscope")
        sys.exit(1)

    print("==================================================")
    print("🇨🇳 正在通过魔搭社区 (ModelScope) 国内节点下载基座模型")
    print(f"• 模型 ID:   {args.model}")
    print(f"• 版本分支:  {args.revision}")
    print(f"• 保存目标:  {local_path}")
    print("==================================================\n")

    local_path.mkdir(parents=True, exist_ok=True)

    try:
        downloaded_dir = snapshot_download(
            model_id=args.model,
            revision=args.revision,
            local_dir=str(local_path)
        )
        print(f"\n🎉 模型下载完成！本地存储路径:")
        print(f"👉 {downloaded_dir}")
    except Exception as e:
        print(f"\n❌ 下载失败: {e}")
        print("💡 提示: 请检查网络连接或确认该模型在 ModelScope 上的公开状态。")
        sys.exit(1)

if __name__ == "__main__":
    main()
