#!/bin/bash
# pack.sh - 阶段二：一键生成客户交付增量包
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${1:-${PATCH_SOURCE_DIR:-$DIR/checkpoints/checkpoint-best}}"
OUT_TAR="$DIR/patch.tar.gz"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "❌ 错误: 未找到权重目录: $SOURCE_DIR"
  echo "用法: ./02_model/pack.sh <权重所在目录路径>"
  echo "示例: ./02_model/pack.sh /path/to/checkpoint-best"
  exit 1
fi

echo "📦 正在打包交付增量包 (来源: $SOURCE_DIR)..."
tar -czf "$OUT_TAR" -C "$SOURCE_DIR" lora_weights classifier_head.pt

echo "✅ 打包完成！交付文件:"
ls -lh "$OUT_TAR"
echo "👉 交付该 patch.tar.gz 给客户即可。"
