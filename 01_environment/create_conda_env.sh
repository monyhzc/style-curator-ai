#!/bin/bash
# ==============================================================================
# create_conda_env.sh - 建立 Style Curator AI 專屬獨立 Conda 隔離環境
# 防止污染伺服器上其他應用與服務 (支援 NVIDIA H20 / H100 / 4090 等現代 GPU)
# ==============================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

ENV_NAME="style_curator"
PY_VER="3.10"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}🚀 Style Curator AI - 獨立 Conda 隔離環境建立腳本${NC}"
echo -e "${BLUE}==================================================================${NC}"

if ! command -v conda &> /dev/null; then
    echo -e "${RED}❌ 未檢測到 conda 指令，請先確保 Miniconda/Anaconda 已加入 PATH${NC}"
    exit 1
fi

CONDA_BASE=$(conda info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"

echo -e "\n${BLUE}⏳ [1/4] 正在檢查/建立獨立環境: ${GREEN}${ENV_NAME} (Python ${PY_VER})${NC}..."
if conda env list | grep -E "^${ENV_NAME}[[:space:]]" &> /dev/null; then
    echo -e "✓ Conda 環境 ${GREEN}${ENV_NAME}${NC} 已存在，跳過建立。"
else
    conda create -n "${ENV_NAME}" python="${PY_VER}" -y
fi

echo -e "\n${BLUE}⏳ [2/4] 啟動隔離環境: ${GREEN}${ENV_NAME}${NC}..."
conda activate "${ENV_NAME}"

echo -e "\n${BLUE}⏳ [3/4] 安裝適配現代 GPU (如 NVIDIA H20 Hopper sm_90 / 驅動 CUDA 12.8) 的 PyTorch...${NC}"
pip install -i "$PIP_MIRROR" --upgrade pip setuptools wheel
pip install -i "$PIP_MIRROR" torch torchvision --index-url https://download.pytorch.org/whl/cu124 || \
pip install -i "$PIP_MIRROR" torch torchvision

echo -e "\n${BLUE}⏳ [4/4] 安裝工程核心相依套件 (Transformers, PEFT, BitsAndBytes, ModelScope)...${NC}"
pip install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope bitsandbytes accelerate

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 獨立環境配置完成！${NC}"
echo -e "• 環境名稱: ${GREEN}${ENV_NAME}${NC}"
echo -e "• Python 路徑: ${GREEN}$(which python)${NC}"
echo -e "• 伺服器其他應用完全隔離不受任何影響！"
echo -e "${GREEN}==================================================================${NC}"
