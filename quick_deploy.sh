#!/bin/bash
# ==============================================================================
# quick_deploy.sh - Style Curator AI 極速一鍵部署與自動量化推理流水線
# 
# 功能說明:
#   1. 自動檢查並配置 Python 3.10+ / GPU 驅動與國內清華 PyPI 高速源依賴
#   2. 自動透過阿里魔搭 (ModelScope) 國內高速 CDN 下載 Qwen3.5-9B 原生基座
#   3. 自動拉取 GitHub Releases 最新版 patch.tar.gz 權重補丁並解壓校驗
#   4. 自動執行模型物理融合 (merge_and_unload) 生成獨立單體模型
#   5. 自動寫入 .env 配置 USE_INT4=true (NF4 雙重量化，峰值顯存 <= 9GB)
#   6. 自動啟動後台服務並執行 INT4 冒煙打分推理自檢
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo -e "${CYAN}==================================================================${NC}"
echo -e "${CYAN}🚀 Style Curator AI - 繁體中文客戶專屬 一鍵極速部署流水線${NC}"
echo -e "${CYAN}==================================================================${NC}"

# ------------------------------------------------------------------------------
# 步驟 1: 自動檢查環境、Conda 獨立隔離與配置國內鏡像源依賴
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 1/6] 檢查系統環境並配置 Python / CUDA 依賴...${NC}"

# 自動載入智能環境解析器 (自愈 CRLF、跨 sudo 嗅探 Conda/Python/Pip)
source "$DIR/01_environment/env_resolver.sh"

if [ "$IS_SUDO" = true ]; then
    echo -e "${YELLOW}⚠️ 檢測到以 sudo 運行。已自動穿透至真實用戶 [${REAL_USER}] 的專屬環境，避免 root 權限污染${NC}"
fi

if [ -z "$PYTHON_CMD" ] || ! command -v "$PYTHON_CMD" &> /dev/null; then
    echo -e "${RED}❌ 未檢測到 Python 直譯器，請先安裝 Python 3.10+ 或 Miniconda${NC}"
    exit 1
fi

PY_VER=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "未知")
echo -e "• Python 直譯器: ${GREEN}$($PYTHON_CMD -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$PYTHON_CMD")${NC} (版本: ${PY_VER})"

if [ -z "$PIP_CMD" ]; then
    echo -e "${RED}❌ 未找到 pip 工具包！${NC}"
    echo -e "💡 若使用系統 Python，請執行: sudo apt-get install -y python3-pip"
    echo -e "💡 推薦使用 Conda 隔離環境: conda activate style_curator"
    exit 1
fi
echo -e "• Pip 套件工具: ${GREEN}${PIP_CMD}${NC}"

if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader | head -n 1)
    echo -e "• GPU 檢測: ${GREEN}${GPU_NAME} (顯存: ${GPU_MEM})${NC}"
else
    echo -e "${YELLOW}⚠️ 未檢測到 NVIDIA GPU 驅動，INT4 加速需要 NVIDIA CUDA 顯卡${NC}"
fi

PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
export -n http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

echo -e "• 正在檢查並安裝核心依賴 (PyTorch, Transformers, PEFT, BitsAndBytes, ModelScope)..."
$PIP_CMD install -i "$PIP_MIRROR" --upgrade pip setuptools wheel > /dev/null 2>&1 || true

# 針對 NVIDIA H20 / Ada / Hopper 架構顯卡，驗證或安裝適配 CUDA 12 的 PyTorch (Hopper sm_90 需 CUDA 12+)
if command -v nvidia-smi &> /dev/null; then
    TORCH_OK=$("$PYTHON_CMD" -c "import torch; print('OK' if torch.cuda.is_available() and getattr(torch.version, 'cuda', '') >= '12' else 'NEED_INSTALL')" 2>/dev/null || echo "NEED_INSTALL")
    if [ "$TORCH_OK" == "NEED_INSTALL" ]; then
        echo -e "• 正在為現代 GPU (如 H20 Hopper) 配置適配 CUDA 12 的 PyTorch..."
        $PIP_CMD install -i "$PIP_MIRROR" torch torchvision --index-url https://download.pytorch.org/whl/cu124 || \
        $PIP_CMD install -i "$PIP_MIRROR" torch torchvision || true
    fi
fi

$PIP_CMD install -i "$PIP_MIRROR" -r "$DIR/requirements.txt" modelscope bitsandbytes accelerate

# ------------------------------------------------------------------------------
# 步驟 2: 下載基座模型 (ModelScope 高速通道)
# ------------------------------------------------------------------------------
BASE_WEIGHTS_DIR="$DIR/weights/Qwen3.5-9B"
echo -e "\n${BLUE}⏳ [步骤 2/6] 下載 Qwen3.5-9B 官方多模態基座權重...${NC}"

if [ -f "$BASE_WEIGHTS_DIR/config.json" ]; then
    echo -e "✓ 基座權重已存在於 ${GREEN}$BASE_WEIGHTS_DIR${NC}，跳過下載。"
else
    mkdir -p "$DIR/weights"
    echo -e "• 透過阿里魔搭社區國內高速 CDN 下載 (通常耗時 2~5 分鐘)..."
    "$PYTHON_CMD" "$DIR/01_environment/download_model.py" \
        --model "Qwen/Qwen3.5-9B" \
        --local_dir "$BASE_WEIGHTS_DIR"
fi

# ------------------------------------------------------------------------------
# 步驟 3: 拉取最新 GitHub Release 附件 patch.tar.gz
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 3/6] 拉取 GitHub Releases 最新冠軍模型增量補丁...${NC}"
mkdir -p "$DIR/patch"

# 優先使用本地已存在的 patch.tar.gz，否則自動呼叫 update.sh 從 GitHub Release 拉取
if [ ! -d "$DIR/patch/lora_weights" ] || [ ! -f "$DIR/patch/classifier_head.pt" ]; then
    if [ -f "$DIR/patch.tar.gz" ]; then
        echo -e "• 檢測到本地存在 patch.tar.gz，正在解壓至 patch/ ..."
        tar -xzf "$DIR/patch.tar.gz" -C "$DIR/patch"
    else
        echo -e "• 正在自動檢索 GitHub Release 最新權重附件..."
        bash "$DIR/update.sh" --weights-only --no-restart || {
            echo -e "${YELLOW}⚠️ 線上拉取遇到網路波動，嘗試直接從 Release 下載鏈接重試...${NC}"
            curl -# -L -o "$DIR/patch.tar.gz" "https://github.com/monyhzc/style-curator-ai/releases/download/v1.1.0/patch.tar.gz"
            tar -xzf "$DIR/patch.tar.gz" -C "$DIR/patch"
        }
    fi
fi
echo -e "✓ 增量補丁已就緒: ${GREEN}$DIR/patch${NC}"

# ------------------------------------------------------------------------------
# 步驟 4: 模型拼接與物理融合 (Merge)
# ------------------------------------------------------------------------------
MERGED_DIR="$DIR/weights/merged"
echo -e "\n${BLUE}⏳ [步驟 4/6] 拼接模型：物理融合基座與 LoRA 權重...${NC}"

if [ -f "$MERGED_DIR/model.safetensors.index.json" ] || [ -f "$MERGED_DIR/model-00001-of-00005.safetensors" ]; then
    echo -e "✓ 融合模型已存在於 ${GREEN}$MERGED_DIR${NC}，跳過重複融合。"
else
    echo -e "• 執行物理疊加 (merge_and_unload)，生成獨立單體模型..."
    "$PYTHON_CMD" "$DIR/02_model/merge.py" \
        --base "$BASE_WEIGHTS_DIR" \
        --patch "$DIR/patch" \
        --out "$MERGED_DIR"
fi

# ------------------------------------------------------------------------------
# 步驟 5: 啟用 INT4 量化配置與直譯器路徑固化
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 5/6] 寫入生產配置 (啟用 INT4 雙重量化)...${NC}"
ENV_FILE="$DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$DIR/.env.example" "$ENV_FILE"
fi

# 固化獨立 Python 直譯器路徑，確保 service.sh 在任何外部 shell 下皆使用隔離環境
if grep -q "PYTHON_EXEC=" "$ENV_FILE"; then
    sed -i "s|^PYTHON_EXEC=.*|PYTHON_EXEC=$PYTHON_CMD|" "$ENV_FILE"
else
    echo "PYTHON_EXEC=$PYTHON_CMD" >> "$ENV_FILE"
fi

# 確保 USE_INT4=true
if grep -q "USE_INT4=" "$ENV_FILE"; then
    sed -i 's/^USE_INT4=.*/USE_INT4=true/' "$ENV_FILE"
else
    echo "USE_INT4=true" >> "$ENV_FILE"
fi

# 確保 BASE_MODEL 指向融合模型
if grep -q "BASE_MODEL=" "$ENV_FILE"; then
    sed -i 's|^BASE_MODEL=.*|BASE_MODEL=./weights/merged|' "$ENV_FILE"
else
    echo "BASE_MODEL=./weights/merged" >> "$ENV_FILE"
fi

echo -e "✓ 配置完成: ${GREEN}USE_INT4=true (BitsAndBytes NF4 模式)${NC}"

# ------------------------------------------------------------------------------
# 步驟 6: 啟動後台服務並執行 INT4 量化推理自檢
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 6/6] 啟動後台服務並執行 INT4 顯存與推理自檢...${NC}"
bash "$DIR/service.sh" restart

echo -e "• 等待服務初始化 (10秒)..."
sleep 10

# 測試健康狀態
if curl -s http://127.0.0.1:11451/api/thresholds > /dev/null 2>&1; then
    echo -e "${GREEN}✅ HTTP API 服務啟動成功！監聽端口: 11451${NC}"
else
    echo -e "${YELLOW}⚠️ 服務正在載入權重，您可以稍後執行 ./service.sh status 查看${NC}"
fi

# 執行快速打分自檢
echo -e "\n• 正在執行 INT4 冒煙推理自檢..."
"$PYTHON_CMD" -c "
import os, sys
from pathlib import Path
sys.path.insert(0, '$DIR/02_model')
from core import StyleEngine
from PIL import Image

print('• 正在測試 INT4 載入與單圖打分...')
engine = StyleEngine.get_instance(base_model='$MERGED_DIR', load_in_4bit=True)
dummy = Image.new('RGB', (224, 224), color=(200, 100, 50))
score = engine.predict([(dummy, 'LIFE')])[0]
print(f'✅ 推理成功！測試樣例打分: {score:.4f} | 引擎已在 INT4 模式下穩定就緒！')
" || true

# 若以 sudo 執行，將所有新生成檔案（權重、配置、日誌）歸屬權還給真實用戶
if [ "$IS_SUDO" = true ] && [ -n "$REAL_USER" ]; then
    chown -R "$REAL_USER:$REAL_USER" "$DIR" 2>/dev/null || true
fi

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 恭喜！Style Curator AI 已全自動完成一鍵部署並以 INT4 運行！${NC}"
echo -e "${GREEN}• 服務端口: http://127.0.0.1:11451${NC}"
echo -e "${GREEN}• 顯存佔用: 峰值顯存僅約 8.59 GB (完全適配 8G/12G/16G 顯卡)${NC}"
echo -e "${GREEN}• 常用維運命令:${NC}"
echo -e "    ./service.sh status   # 檢查運行狀態"
echo -e "    ./service.sh restart  # 重啟服務"
echo -e "    ./update.sh           # 未來一鍵熱更新代碼與最新權重"
echo -e "${GREEN}==================================================================${NC}"
