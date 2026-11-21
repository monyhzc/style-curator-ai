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

# 1. 检查 Conda 隔离环境
CONDA_ENV_NAME="style_curator"
if command -v conda &> /dev/null; then
    CONDA_BASE=$(conda info --base 2>/dev/null || echo "")
    if [ -n "$CONDA_BASE" ] && [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
        CURRENT_ENV=$(basename "$CONDA_PREFIX" 2>/dev/null || echo "")
        if [ "$CURRENT_ENV" != "$CONDA_ENV_NAME" ]; then
            if ! conda env list | grep -E "^${CONDA_ENV_NAME}[[:space:]]" &> /dev/null; then
                echo -e "• 自动建立独立 Conda 隔离环境: ${GREEN}${CONDA_ENV_NAME} (Python 3.10)${NC}..."
                conda create -n "$CONDA_ENV_NAME" python=3.10 -y
            fi
            conda activate "$CONDA_ENV_NAME"
            echo -e "✓ 已切换至隔离环境: ${GREEN}${CONDA_ENV_NAME}${NC}"
        fi
    fi
fi

PYTHON_CMD="python3"
if [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    PYTHON_CMD="$CONDA_PREFIX/bin/python"
fi

if ! command -v "$PYTHON_CMD" &> /dev/null; then
    echo -e "${RED}❌ 未检测到 python3，请先安装 Python 3.10+ 环境${NC}"
    exit 1
fi
PY_VER=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "• Python 解释器: ${GREEN}$($PYTHON_CMD -c 'import sys; print(sys.executable)') (版本: ${PY_VER})${NC}"

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

"$PYTHON_CMD" -m pip install -i "$PIP_MIRROR" --upgrade pip setuptools wheel

if command -v nvidia-smi &> /dev/null; then
    TORCH_OK=$("$PYTHON_CMD" -c "import torch; print('OK' if torch.cuda.is_available() and getattr(torch.version, 'cuda', '') >= '12' else 'NEED_INSTALL')" 2>/dev/null || echo "NEED_INSTALL")
    if [ "$TORCH_OK" == "NEED_INSTALL" ]; then
        echo -e "• 正在为现代 GPU (如 H20 Hopper) 配置适配 CUDA 12 的 PyTorch..."
        "$PYTHON_CMD" -m pip install -i "$PIP_MIRROR" torch torchvision --index-url https://download.pytorch.org/whl/cu124 || \
        "$PYTHON_CMD" -m pip install -i "$PIP_MIRROR" torch torchvision || true
    fi
fi

"$PYTHON_CMD" -m pip install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope bitsandbytes accelerate

# 5. 自检核心依赖
echo -e "\n${BLUE}⏳ 验证安装完整性...${NC}"
"$PYTHON_CMD" -c "
import torch, transformers, peft, fastapi, uvicorn, modelscope, PIL
print('✅ 全部核心组件导入成功:')
print(f'   - PyTorch: {torch.__version__} (CUDA可用: {torch.cuda.is_available()})')
print(f'   - Transformers: {transformers.__version__}')
print(f'   - PEFT: {peft.__version__}')
print(f'   - ModelScope: {modelscope.__version__}')
print(f'   - FastAPI: {fastapi.__version__}')
"

echo -e "\n${GREEN}🎉 环境初始化完毕！您可以直接运行 download_model.py 下载模型或启动服务。${NC}"
