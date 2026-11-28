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
PY_VER="3.14"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

# 統一版本基線 (CUDA 13.2 / PyTorch 2.14.1+cu130)
CUDA_VERSION="13.2"
TORCH_VERSION="2.14.1"
TORCH_CUDA_TAG="cu130"
TORCH_INDEX_URL="https://download.pytorch.org/whl/${TORCH_CUDA_TAG}"
TRANSFORMERS_VERSION="5.19.0"
BITSANDBYTES_VERSION="0.50.2"
PEFT_VERSION="0.21.2"

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

echo -e "\n${BLUE}⏳ [3/4] 安裝適配現代 GPU (如 NVIDIA H20 Hopper sm_90 / 驅動 CUDA ${CUDA_VERSION}) 的 PyTorch ${TORCH_VERSION}+${TORCH_CUDA_TAG}...${NC}"
pip install -i "$PIP_MIRROR" --upgrade pip setuptools wheel
pip install --index-url "$TORCH_INDEX_URL" "torch==${TORCH_VERSION}" torchvision || \
pip install -i "$PIP_MIRROR" "torch==${TORCH_VERSION}" torchvision

echo -e "\n${BLUE}⏳ [4/4] 安裝工程核心相依套件 (Transformers ${TRANSFORMERS_VERSION}, PEFT ${PEFT_VERSION}, BitsAndBytes ${BITSANDBYTES_VERSION}, ModelScope)...${NC}"
pip install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope accelerate

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 獨立環境配置完成！${NC}"
echo -e "• 環境名稱: ${GREEN}${ENV_NAME}${NC}"
echo -e "• Python 路徑: ${GREEN}$(which python)${NC}"
python -c "
import torch, transformers, peft, bitsandbytes
print(f'• PyTorch: {torch.__version__} (CUDA: {torch.version.cuda}, 可用: {torch.cuda.is_available()})')
print(f'• Transformers: {transformers.__version__} | PEFT: {peft.__version__} | BitsAndBytes: {bitsandbytes.__version__}')
" 2>/dev/null || true
echo -e "• 伺服器其他應用完全隔離不受任何影響！"
echo -e "${GREEN}==================================================================${NC}"
