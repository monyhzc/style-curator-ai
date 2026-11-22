#!/bin/bash
# ==============================================================================
# update.sh - Style Curator AI 生产环境代码与模型权重全自动无缝更新脚本
# 
# 功能说明:
#   1. 自动执行 git pull 更新最新业务代码、接口定义、Prompt 与双阈值配置
#   2. 自动检索 GitHub Release 最新版本 (或指定 tag)，获取增量补丁 patch.tar.gz
#   3. 对比本地版本，若有新版本则自动下载、校验、备份并无缝热替换到 ./patch/
#   4. 若后台服务正在运行，自动优雅重启生效 (零手动干预运维)
#
# 用法:
#   ./update.sh                 # 标准更新 (代码 + 最新权重)
#   ./update.sh --code-only     # 仅更新 Git 代码，不更新权重
#   ./update.sh --weights-only  # 仅更新模型权重，不拉取代码
#   ./update.sh --tag v1.0.0    # 回滚/指定更新到特定 Release 版本的权重
#   ./update.sh --force         # 即使版本相同也强制重新下载并解压权重
#   ./update.sh --no-restart    # 更新后不自动重启正在运行的服务
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

REPO_OWNER="monyhzc"
REPO_NAME="style-curator-ai"
API_BASE="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}"

# 参数解析
UPDATE_CODE=true
UPDATE_WEIGHTS=true
SPECIFIC_TAG=""
FORCE=false
AUTO_RESTART=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --code-only)
      UPDATE_WEIGHTS=false
      shift
      ;;
    --weights-only)
      UPDATE_CODE=false
      shift
      ;;
    --tag)
      SPECIFIC_TAG="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --no-restart)
      AUTO_RESTART=false
      shift
      ;;
    -h|--help)
      echo "用法: $0 [--code-only] [--weights-only] [--tag <version>] [--force] [--no-restart]"
      exit 0
      ;;
    *)
      echo "未知参数: $1 (查看帮助: $0 --help)"
      exit 1
      ;;
  esac
done

echo "=================================================================="
echo "🔄 Style Curator AI - 生产环境一键自动更新流水线"
echo "=================================================================="

# 检查当前服务运行状态
SERVICE_WAS_RUNNING=false
PID_FILE="$DIR/03_service/service.pid"
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
  SERVICE_WAS_RUNNING=true
  echo "• 当前服务状态: 🟢 运行中 (PID: $(cat "$PID_FILE"))"
else
  echo "• 当前服务状态: ⚪ 未运行"
fi

# ------------------------------------------------------------------------------
# 阶段 1: 更新 Git 仓库代码
# ------------------------------------------------------------------------------
if [ "$UPDATE_CODE" = true ]; then
  echo -e "\n>>> 阶段 1: 正在拉取 GitHub 仓库最新代码..."
  if [ -d ".git" ]; then
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo "• 当前分支: $CURRENT_BRANCH"
    
    # 检查是否有未提交的本地修改
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
      echo "⚠️ 提示: 本地工作区存在修改，正在尝试保留更新..."
    fi

    git fetch origin "$CURRENT_BRANCH"
    LOCAL_HASH=$(git rev-parse HEAD)
    REMOTE_HASH=$(git rev-parse "origin/$CURRENT_BRANCH")

    if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
      echo "✓ 代码已是最新 (Commit: ${LOCAL_HASH:0:7})"
    else
      echo "• 发现远端新提交 (${LOCAL_HASH:0:7} -> ${REMOTE_HASH:0:7})，正在拉取..."
      git pull --ff-only origin "$CURRENT_BRANCH"
      echo "✓ 代码更新完成！"
    fi
    # 自动修复所有脚本的换行符 (CRLF -> LF) 并恢复执行权限
    sed -i 's/\r$//' "$DIR"/*.sh "$DIR"/*/*.sh 2>/dev/null || true
    chmod +x "$DIR"/*.sh "$DIR"/*/*.sh 2>/dev/null || true
  else
    echo "⚠️ 当前目录非 Git 仓库，跳过 git pull。"
  fi
else
  echo -e "\n>>> 阶段 1: 已跳过代码更新 (--weights-only)"
fi

# ------------------------------------------------------------------------------
# 阶段 2: 查询 GitHub Release 并更新模型权重
# ------------------------------------------------------------------------------
if [ "$UPDATE_WEIGHTS" = true ]; then
  echo -e "\n>>> 阶段 2: 正在检索 GitHub Release 模型权重补丁..."

  if [ -n "$SPECIFIC_TAG" ]; then
    RELEASE_URL="${API_BASE}/releases/tags/${SPECIFIC_TAG}"
    echo "• 目标版本: 指定 Tag [${SPECIFIC_TAG}]"
  else
    RELEASE_URL="${API_BASE}/releases/latest"
    echo "• 目标版本: 最新稳定版 (Latest Release)"
  fi

  # 通过 GitHub API 获取 Release JSON 元数据并解析
  PARSED_INFO=$(curl -sL \
    -H "Accept: application/vnd.github+json" \
    -H "User-Agent: StyleCuratorUpdater/1.0" \
    "$RELEASE_URL" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tag = data.get('tag_name')
    if not tag:
        sys.exit(1)
    
    download_url = None
    size_mb = 0
    for a in data.get('assets', []):
        if a.get('name') == 'patch.tar.gz':
            download_url = a.get('browser_download_url')
            size_mb = round(a.get('size', 0) / (1024*1024), 1)
            break
            
    if not download_url:
        sys.exit(2)
        
    print(f'{tag}|{download_url}|{size_mb}')
except Exception:
    sys.exit(3)
" 2>/dev/null || true)

  if [ -z "$PARSED_INFO" ]; then
    echo "❌ 错误: 获取 GitHub Release 元数据失败，请检查网络或 Tag 是否存在。"
    if [ "$UPDATE_CODE" = false ]; then
      exit 1
    fi
  else
    IFS="|" read -r REMOTE_TAG DOWNLOAD_URL ASSET_SIZE <<< "$PARSED_INFO"
    echo "• 远端最新 Release: $REMOTE_TAG"
    echo "• 权重补丁大小:     ${ASSET_SIZE} MB"
    echo "• 权重下载直链:     $DOWNLOAD_URL"

    # 读取本地当前安装的权重版本
    LOCAL_VERSION_FILE="$DIR/patch/.version"
    LOCAL_VERSION=""
    if [ -f "$LOCAL_VERSION_FILE" ]; then
      LOCAL_VERSION=$(cat "$LOCAL_VERSION_FILE" | tr -d '[:space:]')
    fi
    echo "• 本地当前安装版本: ${LOCAL_VERSION:-'未知/早期版本'}"

    # 判断是否需要更新权重
    NEED_UPDATE=false
    if [ "$FORCE" = true ]; then
      NEED_UPDATE=true
      echo "• 触发强制更新 (--force)"
    elif [ ! -d "$DIR/patch/lora_weights" ] || [ ! -f "$DIR/patch/classifier_head.pt" ]; then
      NEED_UPDATE=true
      echo "• 本地缺失必要权重文件 (patch/lora_weights 或 classifier_head.pt)，需要下载"
    elif [ "$LOCAL_VERSION" != "$REMOTE_TAG" ]; then
      NEED_UPDATE=true
      echo "• 发现权重版本差异 (${LOCAL_VERSION} -> ${REMOTE_TAG})，需要更新"
    fi

    if [ "$NEED_UPDATE" = true ]; then
      TMP_ARCHIVE="$DIR/patch.tar.gz.download"
      echo -e "\n📥 正在下载 ${REMOTE_TAG} 权重补丁 (${ASSET_SIZE} MB)..."
      
      # 使用 curl 下载并显示标准进度
      curl -# -L -o "$TMP_ARCHIVE" "$DOWNLOAD_URL"

      # 校验压缩包完整性
      echo "🔍 正在校验压缩包完整性..."
      if ! tar -tzf "$TMP_ARCHIVE" >/dev/null 2>&1; then
        echo "❌ 错误: 下载的文件损坏或非标准 tar.gz 压缩包，已取消更新！"
        rm -f "$TMP_ARCHIVE"
        exit 1
      fi

      # 备份旧权重 (安全容灾)
      if [ -d "$DIR/patch" ]; then
        echo "📦 正在安全备份旧权重至 patch.bak..."
        rm -rf "$DIR/patch.bak"
        cp -r "$DIR/patch" "$DIR/patch.bak"
      fi

      # 解压覆盖
      echo "🚀 正在部署解压新权重至 patch/..."
      mkdir -p "$DIR/patch"
      tar -xzf "$TMP_ARCHIVE" -C "$DIR/patch"

      # 写入版本标记
      echo "$REMOTE_TAG" > "$DIR/patch/.version"
      rm -f "$TMP_ARCHIVE"
      echo "✅ 权重热替换完成！当前版本: ${REMOTE_TAG}"
    else
      echo "✓ 本地权重与远端 Release 一致 (${LOCAL_VERSION})，无需重新下载 128MB 补丁。"
    fi
  fi
else
  echo -e "\n>>> 阶段 2: 已跳过权重更新 (--code-only)"
fi

# ------------------------------------------------------------------------------
# 阶段 3: 优雅重启服务
# ------------------------------------------------------------------------------
if [ "$SERVICE_WAS_RUNNING" = true ] && [ "$AUTO_RESTART" = true ]; then
  echo -e "\n>>> 阶段 3: 正在优雅重启后台推理服务以载入最新代码与权重..."
  bash "$DIR/service.sh" restart
  echo "✅ 服务已成功重启并载入最新版本！"
elif [ "$SERVICE_WAS_RUNNING" = false ]; then
  echo -e "\n>>> 阶段 3: 服务此前处于停止状态，如需启动请运行:"
  echo "    ./service.sh start"
fi

echo -e "\n🎉 全部更新流程执行完毕！"
echo "=================================================================="
