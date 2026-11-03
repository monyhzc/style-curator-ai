#!/bin/bash
# 根目录全局便捷管理快捷脚本
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/03_service/service.sh" "$@"
