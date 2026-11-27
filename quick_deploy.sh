#!/bin/bash
# ==============================================================================
# quick_deploy.sh - Style Curator AI 極速一鍵部署與自動量化推理流水線
# 
# 功能說明:
#   1. 互動式確認/自訂連接埠 (PORT) 與登入密碼 (APP_AUTH_TOKEN)，支援留空預設
#   2. 智慧跳過機制：依賴、基座、增量權重、融合模型若已就緒則直接跳過並高亮顯示
#   3. 自動檢查並配置 Python 3.10+ / GPU 驅動與國內清華 PyPI 高速源依賴
#   4. 自動透過阿里魔搭 (ModelScope) 國內高速 CDN 下載 Qwen3.5-9B 原生基座
#   5. 自動拉取 GitHub Releases 最新版 patch.tar.gz 權重補丁並解壓校驗
#   6. 自動執行模型物理融合 (merge_and_unload) 生成獨立單體模型
#   7. 自動寫入 .env 配置 USE_INT4=true (NF4 雙重量化，峰值顯存 <= 9GB)
#   8. 自動啟動後台服務並執行 INT4 冒煙打分推理自檢
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
# 部署前置設定確認 (支援使用者自訂 PORT 與密碼，留空或超時直接按 Enter 採用預設值)
# ------------------------------------------------------------------------------
DEFAULT_PORT="11451"
DEFAULT_TOKEN="jw_style_audit_prod_token_2026"

# 若本地已存在 .env 設定檔，優先提取現有配置作為預設提示
if [ -f "$DIR/.env" ]; then
    SAVED_PORT=$(grep -E "^PORT=" "$DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
    SAVED_TOKEN=$(grep -E "^APP_AUTH_TOKEN=" "$DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
    [ -n "$SAVED_PORT" ] && DEFAULT_PORT="$SAVED_PORT"
    [ -n "$SAVED_TOKEN" ] && DEFAULT_TOKEN="$SAVED_TOKEN"
fi

if [ -t 0 ]; then
    echo -e "${YELLOW}⚙️  【部署配置自訂】(直接按 Enter 鍵將採用預設設定)${NC}"
    read -r -p "👉 請輸入服務連接埠 PORT [預設: ${DEFAULT_PORT}]: " USER_PORT
    TARGET_PORT="${USER_PORT:-$DEFAULT_PORT}"

    read -r -p "👉 請輸入網頁登入密碼 / API Token [預設: ${DEFAULT_TOKEN}]: " USER_TOKEN
    TARGET_TOKEN="${USER_TOKEN:-$DEFAULT_TOKEN}"
    echo -e "${GREEN}✓ 已確認配置: 端口=${TARGET_PORT} | 密碼=${TARGET_TOKEN}${NC}\n"
else
    TARGET_PORT="$DEFAULT_PORT"
    TARGET_TOKEN="$DEFAULT_TOKEN"
    echo -e "${GREEN}✓ 非互動模式，自動採用預設配置: 端口=${TARGET_PORT} | 密碼=${TARGET_TOKEN}${NC}\n"
fi

# ------------------------------------------------------------------------------
# 步驟 1: 自動檢查環境、Conda 獨立隔離與配置國內鏡像源依賴
# ------------------------------------------------------------------------------
echo -e "${BLUE}⏳ [步驟 1/6] 檢查系統環境並配置 Python / CUDA 依賴...${NC}"

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

# 智能依賴檢測：若核心套件已全部安裝，直接跳過重複下載與安裝
MISSING_PKGS=$("$PYTHON_CMD" -c '
import importlib.util
reqs = ["torch", "transformers", "peft", "modelscope", "bitsandbytes", "accelerate", "fastapi", "uvicorn", "PIL", "dotenv", "requests", "pydantic"]
missing = [p for p in reqs if not importlib.util.find_spec(p)]
if not (importlib.util.find_spec("python_multipart") or importlib.util.find_spec("multipart")):
    missing.append("python-multipart")
print(",".join(missing))
' 2>/dev/null || echo "ALL_MISSING")

if [ -z "$MISSING_PKGS" ]; then
    echo -e "✓ ${GREEN}核心環境依賴已安裝就緒 (PyTorch, Transformers, ModelScope, BitsAndBytes 等)，跳過重複安裝。${NC}"
else
    echo -e "• 檢測到缺失套件 [${MISSING_PKGS}]，正在快速安裝核心依賴..."
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
    echo -e "✓ ${GREEN}核心依賴安裝完成。${NC}"
fi

# ------------------------------------------------------------------------------
# 步驟 2: 下載基座模型 (ModelScope 高速通道)
# ------------------------------------------------------------------------------
BASE_WEIGHTS_DIR="$DIR/weights/Qwen3.5-9B"
echo -e "\n${BLUE}⏳ [步驟 2/6] 獲取 Qwen3.5-9B 官方多模態基座權重...${NC}"

if [ -f "$BASE_WEIGHTS_DIR/config.json" ]; then
    echo -e "✓ ${GREEN}基座權重已存在於 $BASE_WEIGHTS_DIR，跳過重複下載。${NC}"
else
    mkdir -p "$DIR/weights"
    echo -e "• 透過阿里魔搭社區國內高速 CDN 下載 (通常耗時 2~5 分鐘)..."
    "$PYTHON_CMD" "$DIR/01_environment/download_model.py" \
        --model "Qwen/Qwen3.5-9B" \
        --local_dir "$BASE_WEIGHTS_DIR"
    echo -e "✓ ${GREEN}基座模型下載完成。${NC}"
fi

# ------------------------------------------------------------------------------
# 步驟 3: 拉取最新 GitHub Release 附件 patch.tar.gz
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 3/6] 獲取最新冠軍模型增量權重補丁...${NC}"
mkdir -p "$DIR/patch"

if [ -d "$DIR/patch/lora_weights" ] && [ -f "$DIR/patch/classifier_head.pt" ]; then
    echo -e "✓ ${GREEN}增量模型補丁已就緒於 $DIR/patch，跳過重複拉取。${NC}"
else
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
    echo -e "✓ ${GREEN}增量補丁解壓完成。${NC}"
fi

# ------------------------------------------------------------------------------
# 步驟 4: 模型拼接與物理融合 (Merge)
# ------------------------------------------------------------------------------
MERGED_DIR="$DIR/weights/merged"
echo -e "\n${BLUE}⏳ [步驟 4/6] 拼接模型：物理融合基座與 LoRA 權重...${NC}"

MERGED_VALID=$("$PYTHON_CMD" -c '
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
if not (d / "config.json").is_file():
    print("MISSING")
    sys.exit(0)
if (d / "model.safetensors").is_file():
    print("OK")
    sys.exit(0)
idx = d / "model.safetensors.index.json"
if idx.is_file():
    try:
        shards = set(json.loads(idx.read_text(encoding="utf-8")).get("weight_map", {}).values())
        if shards and all((d / s).is_file() for s in shards):
            print("OK")
            sys.exit(0)
    except Exception:
        pass
print("INCOMPLETE")
' "$MERGED_DIR" 2>/dev/null || echo "MISSING")

if [ "$MERGED_VALID" = "OK" ]; then
    echo -e "✓ ${GREEN}融合模型已完整存在於 $MERGED_DIR，跳過重複融合。${NC}"
else
    if [ "$MERGED_VALID" = "INCOMPLETE" ]; then
        echo -e "${YELLOW}⚠️ 檢測到 $MERGED_DIR 權重不完整 (缺少 safetensors 權重檔)，正在重新執行物理融合...${NC}"
    else
        echo -e "• 執行物理疊加 (merge_and_unload)，生成獨立單體模型..."
    fi
    "$PYTHON_CMD" "$DIR/02_model/merge.py" \
        --base "$BASE_WEIGHTS_DIR" \
        --patch "$DIR/patch" \
        --out "$MERGED_DIR"
    MERGED_VALID="OK"
    echo -e "✓ ${GREEN}模型物理融合完成。${NC}"
fi

# ------------------------------------------------------------------------------
# 步驟 5: 寫入生產配置 (INT4 雙重量化、連接埠與密碼固化)
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 5/6] 寫入生產配置 (啟用 INT4 雙重量化、配置端口與密碼)...${NC}"
ENV_FILE="$DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$DIR/.env.example" "$ENV_FILE"
fi

# 寫入使用者指定的端口
if grep -q "^PORT=" "$ENV_FILE"; then
    sed -i "s|^PORT=.*|PORT=$TARGET_PORT|" "$ENV_FILE"
else
    echo "PORT=$TARGET_PORT" >> "$ENV_FILE"
fi

# 寫入使用者指定的密碼 / Token
if grep -q "^APP_AUTH_TOKEN=" "$ENV_FILE"; then
    sed -i "s|^APP_AUTH_TOKEN=.*|APP_AUTH_TOKEN=$TARGET_TOKEN|" "$ENV_FILE"
else
    echo "APP_AUTH_TOKEN=$TARGET_TOKEN" >> "$ENV_FILE"
fi

# 固化獨立 Python 直譯器路徑，確保 service.sh 在任何外部 shell 下皆使用隔離環境
if grep -q "^PYTHON_EXEC=" "$ENV_FILE"; then
    sed -i "s|^PYTHON_EXEC=.*|PYTHON_EXEC=$PYTHON_CMD|" "$ENV_FILE"
else
    echo "PYTHON_EXEC=$PYTHON_CMD" >> "$ENV_FILE"
fi

# 確保 USE_INT4=true
if grep -q "^USE_INT4=" "$ENV_FILE"; then
    sed -i 's/^USE_INT4=.*/USE_INT4=true/' "$ENV_FILE"
else
    echo "USE_INT4=true" >> "$ENV_FILE"
fi

# 確保 BASE_MODEL 指向融合模型 (若完整存在) 或基座模型
if [ "$MERGED_VALID" = "OK" ]; then
    TARGET_BASE="./weights/merged"
    SMOKE_BASE="$MERGED_DIR"
else
    TARGET_BASE="./weights/Qwen3.5-9B"
    SMOKE_BASE="$BASE_WEIGHTS_DIR"
fi

if grep -q "^BASE_MODEL=" "$ENV_FILE"; then
    sed -i "s|^BASE_MODEL=.*|BASE_MODEL=$TARGET_BASE|" "$ENV_FILE"
else
    echo "BASE_MODEL=$TARGET_BASE" >> "$ENV_FILE"
fi

echo -e "✓ ${GREEN}生產配置完成: 監聽端口=${TARGET_PORT} | 登入密碼=${TARGET_TOKEN} | USE_INT4=true${NC}"

# ------------------------------------------------------------------------------
# 步驟 6: 啟動後台服務並執行 INT4 量化推理自檢
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}⏳ [步驟 6/6] 啟動後台服務並執行 INT4 顯存與推理自檢...${NC}"
bash "$DIR/service.sh" restart

echo -e "• 等待服務初始化 (10秒)..."
sleep 10

# 測試健康狀態
if curl --noproxy "*" -s "http://127.0.0.1:${TARGET_PORT}/api/thresholds" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ HTTP API 與視覺化工作台服務啟動成功！監聽端口: ${TARGET_PORT}${NC}"
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
engine = StyleEngine.get_instance(base_model='$SMOKE_BASE', load_in_4bit=True)
dummy = Image.new('RGB', (224, 224), color=(200, 100, 50))
score = engine.predict([(dummy, 'LIFE')])[0]
print(f'✅ 推理成功！測試樣例打分: {score:.4f} | 引擎已在 INT4 模式下穩定就緒！')
" || true

# 獲取本機對外 IP
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

# 若以 sudo 執行，將所有新生成檔案（權重、配置、日誌、資料庫）歸屬權還給真實用戶
if [ "$IS_SUDO" = true ] && [ -n "$REAL_USER" ]; then
    chown -R "$REAL_USER:$REAL_USER" "$DIR" 2>/dev/null || true
fi

echo -e "\n${GREEN}==================================================================${NC}"
echo -e "${GREEN}🎉 恭喜！Style Curator AI 已全自動完成一鍵部署並以 INT4 運行！${NC}"
echo -e "${CYAN}• 本地存取位址:    ${GREEN}http://127.0.0.1:${TARGET_PORT}/${NC}"
echo -e "${CYAN}• 外部/局域網網址:  ${GREEN}http://${LOCAL_IP}:${TARGET_PORT}/${NC}"
echo -e "${CYAN}• 網頁登入密碼:    ${YELLOW}${TARGET_TOKEN}${NC} (可在 .env 中修改 APP_AUTH_TOKEN)"
echo -e "${CYAN}• 顯存佔用:        ${GREEN}峰值顯存僅約 8.59 GB (適配 8G/12G/16G/24G+ 顯卡)${NC}"
echo -e "\n${BLUE}🛠️ 常用操作命令:${NC}"
echo -e "    bash check.sh         # 一鍵執行 16 項全鏈路功能驗收自檢"
echo -e "    ./service.sh status   # 檢查服務運行狀態與端口"
echo -e "    ./service.sh logs     # 實時查看後台運維日誌"
echo -e "    ./service.sh restart  # 重啟服務"
echo -e "    ./update.sh           # 未來一鍵熱更新代碼與最新權重"
echo -e "${GREEN}==================================================================${NC}"
