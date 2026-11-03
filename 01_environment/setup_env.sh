#!/bin/bash
# ==============================================================================
# setup_env.sh - 国内服务器一键环境初始化脚本 (清华源/阿里源高速通道)
# ==============================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}🚀 Style Curator AI - 生产环境一键初始化脚本${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未检测到 python3，请先安装 Python 3.10+ 环境${NC}"
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "• Python 解释器: ${GREEN}$(which python3) (版本: ${PY_VER})${NC}"

# 2. 检查 GPU/CUDA
if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
    echo -e "• 显卡检测: ${GREEN}${GPU_NAME}${NC}"
else
    echo -e "${YELLOW}⚠️ 未检测到 NVIDIA 驱动，将以 CPU/回退模式运行${NC}"
fi

# 3. 升级 pip 并配置国内清华源
echo -e "\n${BLUE}⏳ [1/2] 配置国内 PyPI 镜像源并更新核心基础组件...${NC}"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

# 隔离代理环境变量以防止冲突
export -n http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

# 4. 一键安装全部运行依赖与 ModelScope
echo -e "\n${BLUE}⏳ [2/2] 正在通过国内高速镜像源安装工程依赖与魔搭 ModelScope...${NC}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m pip install -i "$PIP_MIRROR" --upgrade pip setuptools wheel
python3 -m pip install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope

# 5. 自检核心依赖
echo -e "\n${BLUE}⏳ 验证安装完整性...${NC}"
python3 -c "
import torch, transformers, peft, fastapi, uvicorn, modelscope, PIL
print('✅ 全部核心组件导入成功:')
print(f'   - PyTorch: {torch.__version__} (CUDA可用: {torch.cuda.is_available()})')
print(f'   - Transformers: {transformers.__version__}')
print(f'   - PEFT: {peft.__version__}')
print(f'   - ModelScope: {modelscope.__version__}')
print(f'   - FastAPI: {fastapi.__version__}')
"

echo -e "\n${GREEN}🎉 环境初始化完毕！您可以直接运行 download_model.py 下载模型或启动服务。${NC}"
