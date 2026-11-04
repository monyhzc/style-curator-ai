#!/bin/bash
# ==============================================================================
# run_train.sh - 阶段五：模型训练与增量后训练快速启动脚本
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$DIR/05_training:$PYTHONPATH"

# 示例 1：从外部已有的 JSONL 开始微调
# python 05_training/train.py \
#   --train_data /path/to/train.jsonl \
#   --val_data /path/to/val.jsonl \
#   --output_dir ./training_output \
#   --epochs 3 \
#   --batch_size 8 \
#   --lr 2e-5

# 示例 2：后续加入新数据时，从现有最佳权重继续增量后训练 (热启动)
# python 05_training/train.py \
#   --train_data /path/to/new_incremental_data.jsonl \
#   --val_data /path/to/val.jsonl \
#   --resume_from /path/to/previous_checkpoint_best \
#   --output_dir ./continual_output \
#   --epochs 2 \
#   --batch_size 8 \
#   --lr 1e-5

echo "👉 请编辑本脚本取消注释相应命令，或直接运行: python 05_training/train.py --help"
python "$DIR/05_training/train.py" --help
