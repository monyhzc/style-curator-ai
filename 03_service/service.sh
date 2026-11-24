#!/bin/bash
# ==============================================================================
# service.sh - 阶段三：Style Curator AI 生产级 HTTP 服务进程管理脚本
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$DIR/.." && pwd)"
PID_FILE="$DIR/service.pid"
LOG_FILE="$DIR/service.log"

# 優先加載根目錄或當前目錄的 .env (健壯解析行內註釋與引號)
load_env_safe() {
  local f="$1"
  [ -f "$f" ] || return 0
  while IFS='=' read -r key val || [ -n "$key" ]; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [ -z "$key" ] && continue
    key=$(echo "$key" | tr -d ' ')
    val=$(echo "$val" | sed -e 's/[[:space:]]*#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
    export "$key=$val" 2>/dev/null || true
  done < "$f"
}

if [ -f "$ROOT_DIR/.env" ]; then
  load_env_safe "$ROOT_DIR/.env"
elif [ -f "$DIR/.env" ]; then
  load_env_safe "$DIR/.env"
fi
PORT="${PORT:-11451}"

# 智能环境解析器 (支持普通用户、sudo 及任意外部 shell 无缝识别 style_curator 隔离环境)
if [ -f "$ROOT_DIR/01_environment/env_resolver.sh" ]; then
  source "$ROOT_DIR/01_environment/env_resolver.sh"
elif [ -n "$PYTHON_EXEC" ] && [ -x "$PYTHON_EXEC" ]; then
  PYTHON_CMD="$PYTHON_EXEC"
else
  PYTHON_CMD="python3"
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
      PID=$(cat "$PID_FILE")
      echo "🟢 服務運行正常 (PID: $PID，端口: $PORT)"
      if command -v ss &>/dev/null; then
        ss -tulpn 2>/dev/null | grep ":$PORT " || true
      elif command -v netstat &>/dev/null; then
        netstat -tulpn 2>/dev/null | grep ":$PORT " || true
      fi
      LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
      echo "👉 Web 審圖工作台: http://${LOCAL_IP}:${PORT}/"
    else
      echo "⚪ 服務未運行。"
    fi
    ;;

  logs)
    if [ -f "$LOG_FILE" ]; then
      tail -f -n 50 "$LOG_FILE"
    else
      echo "⚠️ 暫無日誌檔案: $LOG_FILE"
    fi
    ;;

  restart)
    bash "$BASH_SOURCE" stop
    sleep 2
    bash "$BASH_SOURCE" start
    ;;

  *)
    echo "用法: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
