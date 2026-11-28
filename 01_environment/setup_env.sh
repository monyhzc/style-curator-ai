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

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 统一版本基线 (Python 3.14 / CUDA 13.2 / PyTorch 2.14.1+cu130)
PYTHON_VERSION="3.14"
CUDA_VERSION="13.2"
TORCH_VERSION="2.14.1"
TORCH_CUDA_TAG="cu130"
TORCH_INDEX_URL="https://download.pytorch.org/whl/${TORCH_CUDA_TAG}"
TRANSFORMERS_VERSION="5.19.0"
BITSANDBYTES_VERSION="0.50.2"
PEFT_VERSION="0.21.2"

# 1. 载入智能环境解析器 (自动识别 style_curator 隔离环境与 Pip 命令)
source "$DIR/01_environment/env_resolver.sh"

if [ -z "$PYTHON_CMD" ] || ! command -v "$PYTHON_CMD" &> /dev/null; then
    echo -e "${RED}❌ 未检测到 python3，请先安装 Python ${PYTHON_VERSION}+ 环境${NC}"
    exit 1
fi
PY_VER=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "未知")
echo -e "• Python 解释器: ${GREEN}$($PYTHON_CMD -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$PYTHON_CMD")${NC} (版本: ${PY_VER})"
if ! "$PYTHON_CMD" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
    echo -e "${YELLOW}⚠️ 当前 Python ${PY_VER} 低于基线 ${PYTHON_VERSION}，建议先执行: bash 01_environment/create_conda_env.sh${NC}"
fi
echo -e "• Pip 工具路径:  ${GREEN}${PIP_CMD}${NC}"

# 2. 检查 GPU/CUDA
if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
    echo -e "• 显卡检测: ${GREEN}${GPU_NAME}${NC}"
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '[:space:]')
    if [ -n "$DRIVER_VER" ]; then
        DRIVER_MAJOR="${DRIVER_VER%%.*}"
        if [ "$DRIVER_MAJOR" -lt 580 ] 2>/dev/null; then
            echo -e "${YELLOW}⚠️ 当前 NVIDIA 驱动 ${DRIVER_VER} 低于 CUDA 13.x 最低要求 (>= 580)，请先升级驱动 (CUDA ${CUDA_VERSION} 建议 590+)${NC}"
        else
            echo -e "• CUDA 驱动: ${GREEN}${DRIVER_VER} (支持 CUDA ${CUDA_VERSION} / PyTorch ${TORCH_VERSION}+${TORCH_CUDA_TAG})${NC}"
        fi
    fi
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

$PIP_CMD install -i "$PIP_MIRROR" --upgrade pip setuptools wheel > /dev/null 2>&1 || true

if command -v nvidia-smi &> /dev/null; then
    TORCH_OK=$("$PYTHON_CMD" -c "
import re, torch
ver = tuple(int(x) for x in re.findall(r'\d+', torch.__version__.split('+')[0])[:3])
cuda = tuple(int(x) for x in re.findall(r'\d+', torch.version.cuda or '0')[:2])
print('OK' if torch.cuda.is_available() and ver >= (2, 14, 1) and cuda >= (13, 0) else 'NEED_INSTALL')
" 2>/dev/null || echo "NEED_INSTALL")
    if [ "$TORCH_OK" == "NEED_INSTALL" ]; then
        echo -e "• 正在为现代 GPU (如 H20 Hopper) 配置 PyTorch ${TORCH_VERSION}+${TORCH_CUDA_TAG} (CUDA ${CUDA_VERSION})..."
        $PIP_CMD install --index-url "$TORCH_INDEX_URL" "torch==${TORCH_VERSION}" torchvision || \
        $PIP_CMD install -i "$PIP_MIRROR" "torch==${TORCH_VERSION}" torchvision || true
    fi
fi

$PIP_CMD install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope accelerate

# 5. 自检核心依赖
echo -e "\n${BLUE}⏳ 验证安装完整性...${NC}"
"$PYTHON_CMD" -c "
import torch, transformers, peft, bitsandbytes, fastapi, uvicorn, modelscope, PIL
print('✅ 全部核心组件导入成功:')
print(f'   - PyTorch: {torch.__version__} (CUDA: {torch.version.cuda}, 可用: {torch.cuda.is_available()})')
print(f'   - Transformers: {transformers.__version__}')
print(f'   - PEFT: {peft.__version__}')
print(f'   - BitsAndBytes: {bitsandbytes.__version__}')
print(f'   - ModelScope: {modelscope.__version__}')
print(f'   - FastAPI: {fastapi.__version__}')
"

echo -e "\n${GREEN}🎉 环境初始化完毕！您可以直接运行 download_model.py 下载模型或启动服务。${NC}"
