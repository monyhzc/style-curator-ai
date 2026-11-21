#!/bin/bash
# ==============================================================================
# service.sh - 阶段三：Style Curator AI 生产级 HTTP 服务进程管理脚本
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$DIR/.." && pwd)"
PID_FILE="$DIR/service.pid"
LOG_FILE="$DIR/service.log"

# 优先加载根目录或当前目录的 .env
if [ -f "$ROOT_DIR/.env" ]; then
  export $(grep -v '^#' "$ROOT_DIR/.env" | xargs)
elif [ -f "$DIR/.env" ]; then
  export $(grep -v '^#' "$DIR/.env" | xargs)
fi
PORT="${PORT:-11451}"

# 智能寻找可用 Python 直译器 (优先寻找 style_curator 专属 Conda 隔离环境)
PYTHON_CMD="python3"
if [ -n "$PYTHON_EXEC" ] && [ -x "$PYTHON_EXEC" ]; then
  PYTHON_CMD="$PYTHON_EXEC"
elif command -v conda &> /dev/null && [ -x "$(conda info --base 2>/dev/null)/envs/style_curator/bin/python" ]; then
  PYTHON_CMD="$(conda info --base 2>/dev/null)/envs/style_curator/bin/python"
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
  PYTHON_CMD="$CONDA_PREFIX/bin/python"
fi

case "$1" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
      echo "⚠️ 服务已在运行中 (PID: $(cat "$PID_FILE")，端口: $PORT)"
      exit 0
    fi
    echo "🚀 正在启动 Style Curator AI 生产服务..."
    echo "• 解释器: $PYTHON_CMD"
    echo "• 监听端口: $PORT"
    echo "• 运行日志: $LOG_FILE"
    cd "$DIR"
    nohup "$PYTHON_CMD" -u app.py < /dev/null > "$LOG_FILE" 2>&1 &
    PID=$!
    disown $PID 2>/dev/null || true
    echo $PID > "$PID_FILE"
    sleep 2
    if kill -0 $PID 2>/dev/null; then
      echo "✅ 服务已成功在后台启动 (PID: $PID)"
      echo "👉 查看实时日志: tail -f $LOG_FILE"
    else
      echo "❌ 启动失败，请检查日志: cat $LOG_FILE"
      exit 1
    fi
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      echo "🛑 正在停止服务 (PID: $PID)..."
      kill "$PID" 2>/dev/null || true
      rm -f "$PID_FILE"
      sleep 1
    fi
    # 强制清理占用端口的残留进程
    fuser -k "${PORT}/tcp" 2>/dev/null || true
    echo "✅ 服务已停止。"
    ;;

  status)
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
      echo "🟢 服务运行正常 (PID: $(cat "$PID_FILE")，端口: $PORT)"
      netstat -tulpn 2>/dev/null | grep ":$PORT " || ss -tulpn 2>/dev/null | grep ":$PORT " || true
    else
      echo "⚪ 服务未运行。"
    fi
    ;;

  restart)
    $0 stop
    sleep 2
    $0 start
    ;;

  *)
    echo "用法: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
