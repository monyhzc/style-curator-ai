#!/bin/bash
# ==============================================================================
# env_resolver.sh - Style Curator AI 智能環境解析器
# 作用:
#   1. 自動修復所有腳本的 Windows CRLF (\r) 換行符問題
#   2. 跨用戶/跨 sudo 智能嗅探 Conda 與 Python 隔離環境 (支援普通用戶及 sudo 執行)
#   3. 統一提供穩定的 $PYTHON_CMD 與 $PIP_CMD
# ==============================================================================

# 1. 自動自愈 CRLF 換行符
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v sed &> /dev/null; then
    sed -i 's/\r$//' "$SELF_DIR"/*.sh "$SELF_DIR"/*/*.sh 2>/dev/null || true
fi

# 2. 獲取調用者的真實身份 (即使在 sudo 下也能定位真實用戶的主目錄)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    REAL_USER="$SUDO_USER"
    REAL_HOME=$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)
    [ -z "$REAL_HOME" ] && REAL_HOME="/home/$SUDO_USER"
    IS_SUDO=true
else
    REAL_USER="$USER"
    REAL_HOME="$HOME"
    IS_SUDO=false
fi

TARGET_ENV="style_curator"
PYTHON_CMD=""
PIP_CMD=""

# 3. 優先檢查 .env 中是否已固化有效的 PYTHON_EXEC
if [ -f "$SELF_DIR/.env" ]; then
    SAVED_PY=$(grep -E "^PYTHON_EXEC=" "$SELF_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
    if [ -n "$SAVED_PY" ] && [ -x "$SAVED_PY" ]; then
        PYTHON_CMD="$SAVED_PY"
    fi
fi

# 4. 若未固化，智能多層次搜尋 style_curator 專屬隔離環境
if [ -z "$PYTHON_CMD" ]; then
    # 策略 A: 當前已在 style_curator 中激活
    if [ -n "$CONDA_PREFIX" ] && [ "$(basename "$CONDA_PREFIX")" = "$TARGET_ENV" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
        PYTHON_CMD="$CONDA_PREFIX/bin/python"
    fi

    # 策略 B: 搜尋常見的 Conda 安裝路徑下的 style_curator 環境
    if [ -z "$PYTHON_CMD" ]; then
        POSSIBLE_CONDA_ROOTS=(
            "$REAL_HOME/miniconda3"
            "$REAL_HOME/anaconda3"
            "$REAL_HOME/.conda"
            "$HOME/miniconda3"
            "$HOME/anaconda3"
            "/opt/conda"
            "/usr/local/miniconda3"
            "/usr/local/anaconda3"
            "/root/miniconda3"
        )
        if command -v conda &> /dev/null; then
            POSSIBLE_CONDA_ROOTS+=("$(conda info --base 2>/dev/null)")
        fi

        for croot in "${POSSIBLE_CONDA_ROOTS[@]}"; do
            [ -z "$croot" ] && continue
            # 檢查 envs/style_curator/bin/python
            if [ -x "$croot/envs/$TARGET_ENV/bin/python" ]; then
                PYTHON_CMD="$croot/envs/$TARGET_ENV/bin/python"
                break
            fi
            # 檢查 ~/.conda/envs/style_curator/bin/python
            if [ -x "$croot/style_curator/bin/python" ]; then
                PYTHON_CMD="$croot/style_curator/bin/python"
                break
            fi
        done
    fi

    # 策略 C: 若環境尚未建立，但機器上有 conda，嘗試為該用戶自動建立
    if [ -z "$PYTHON_CMD" ]; then
        FOUND_CONDA=""
        if command -v conda &> /dev/null; then
            FOUND_CONDA=$(command -v conda)
        else
            for croot in "${POSSIBLE_CONDA_ROOTS[@]}"; do
                if [ -x "$croot/bin/conda" ]; then
                    FOUND_CONDA="$croot/bin/conda"
                    break
                fi
            done
        fi

        if [ -n "$FOUND_CONDA" ]; then
            CONDA_BASE_DIR=$(dirname "$(dirname "$FOUND_CONDA")")
            if [ -f "$CONDA_BASE_DIR/etc/profile.d/conda.sh" ]; then
                source "$CONDA_BASE_DIR/etc/profile.d/conda.sh"
                if ! conda env list | grep -E "^${TARGET_ENV}[[:space:]]" &> /dev/null; then
                    echo "• 自動為用戶 [${REAL_USER}] 建立專屬獨立隔離環境: ${TARGET_ENV} (Python 3.10)..."
                    conda create -n "$TARGET_ENV" python=3.10 -y
                fi
                if [ -x "$CONDA_BASE_DIR/envs/$TARGET_ENV/bin/python" ]; then
                    PYTHON_CMD="$CONDA_BASE_DIR/envs/$TARGET_ENV/bin/python"
                elif [ -x "$REAL_HOME/.conda/envs/$TARGET_ENV/bin/python" ]; then
                    PYTHON_CMD="$REAL_HOME/.conda/envs/$TARGET_ENV/bin/python"
                fi
            fi
        fi
    fi

    # 策略 D: 若無 Conda，嘗試嗅探系統 python3 或 python
    if [ -z "$PYTHON_CMD" ]; then
        if command -v python3 &> /dev/null; then
            PYTHON_CMD=$(command -v python3)
        elif command -v python &> /dev/null; then
            # 確保不是 Python 2
            if python -c "import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)" 2>/dev/null; then
                PYTHON_CMD=$(command -v python)
            fi
        fi
    fi

    # 策略 E: 若系統完全沒有 Python 3，嘗試自動安裝系統 Python 3
    if [ -z "$PYTHON_CMD" ]; then
        echo "⚠️ 未檢測到 Python 3，正在嘗試自動安裝基礎 Python 3 環境..."
        if [ "$EUID" -eq 0 ]; then
            if command -v apt-get &> /dev/null; then
                apt-get update -qq && apt-get install -y python3 python3-pip python3-venv > /dev/null 2>&1 || true
            elif command -v yum &> /dev/null; then
                yum install -y python3 python3-pip > /dev/null 2>&1 || true
            fi
        elif command -v sudo &> /dev/null; then
            if command -v apt-get &> /dev/null; then
                sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv > /dev/null 2>&1 || true
            elif command -v yum &> /dev/null; then
                sudo yum install -y python3 python3-pip > /dev/null 2>&1 || true
            fi
        fi
        PYTHON_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
    fi
fi

# 5. 雙向嗅探與解析 PIP_CMD (python -m pip / pip / pip3 智能對齊)
sniff_pip() {
    if [ -z "$PYTHON_CMD" ]; then
        return
    fi
    # 優先測試當前 Python 自帶的 pip 模組 (最乾淨、最不易串環境)
    if "$PYTHON_CMD" -m pip --version &> /dev/null; then
        PIP_CMD="$PYTHON_CMD -m pip"
        return
    fi
    # 測試 python 同目錄下的 pip / pip3
    local py_dir
    py_dir=$(dirname "$PYTHON_CMD")
    if [ -x "$py_dir/pip" ]; then
        PIP_CMD="$py_dir/pip"
        return
    elif [ -x "$py_dir/pip3" ]; then
        PIP_CMD="$py_dir/pip3"
        return
    fi
    # 測試全局系統 pip3 或 pip
    if command -v pip3 &> /dev/null; then
        PIP_CMD=$(command -v pip3)
        return
    elif command -v pip &> /dev/null; then
        PIP_CMD=$(command -v pip)
        return
    fi
}

sniff_pip

# 6. 若有 Python 但無 pip，自動嘗試安裝修復 pip
if [ -n "$PYTHON_CMD" ] && [ -z "$PIP_CMD" ]; then
    echo "⚠️ 檢測到 Python (${PYTHON_CMD}) 缺失 pip 模組，正在嘗試自動修復/安裝 pip..."

    # 嘗試 1: Python 內置 ensurepip
    "$PYTHON_CMD" -m ensurepip --upgrade > /dev/null 2>&1 || true
    sniff_pip

    # 嘗試 2: 包管理器自動安裝 (Ubuntu/Debian 或 CentOS)
    if [ -z "$PIP_CMD" ]; then
        if [ "$EUID" -eq 0 ]; then
            if command -v apt-get &> /dev/null; then
                apt-get update -qq && apt-get install -y python3-pip > /dev/null 2>&1 || true
            elif command -v yum &> /dev/null; then
                yum install -y python3-pip > /dev/null 2>&1 || true
            fi
        elif command -v sudo &> /dev/null; then
            if command -v apt-get &> /dev/null; then
                sudo apt-get update -qq && sudo apt-get install -y python3-pip > /dev/null 2>&1 || true
            elif command -v yum &> /dev/null; then
                sudo yum install -y python3-pip > /dev/null 2>&1 || true
            fi
        fi
        sniff_pip
    fi

    # 嘗試 3: 官方 get-pip.py 腳本安裝
    if [ -z "$PIP_CMD" ]; then
        if command -v curl &> /dev/null; then
            curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py 2>/dev/null || true
        elif command -v wget &> /dev/null; then
            wget -qO /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py 2>/dev/null || true
        fi
        if [ -f /tmp/get-pip.py ]; then
            "$PYTHON_CMD" /tmp/get-pip.py > /dev/null 2>&1 || true
            rm -f /tmp/get-pip.py
            sniff_pip
        fi
    fi
fi

# 導出給調用腳本
export PYTHON_CMD
export PIP_CMD
export REAL_USER
export REAL_HOME
export IS_SUDO
