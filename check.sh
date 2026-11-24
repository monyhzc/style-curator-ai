#!/usr/bin/env bash
# ==============================================================================
# check.sh - Style Curator AI 視覺化工作台與 API 全鏈路自動化驗收腳本
# 用法:
#   bash check.sh
#   BASE=http://127.0.0.1:11451 APP_AUTH_TOKEN='密碼' bash check.sh
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 自動讀取 .env 中的配置 (若外部環境變數未提供)
if [ -f "$DIR/.env" ]; then
    [ -z "$APP_AUTH_TOKEN" ] && APP_AUTH_TOKEN=$(grep -E "^APP_AUTH_TOKEN=" "$DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
    [ -z "$PORT" ] && PORT=$(grep -E "^PORT=" "$DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
fi

PORT="${PORT:-11451}"
APP_AUTH_TOKEN="${APP_AUTH_TOKEN:-jw_style_audit_prod_token_2026}"
BASE="${BASE:-http://127.0.0.1:$PORT}"
BASE="${BASE%/}"

JAR="$(mktemp)"
BODY="$(mktemp)"
trap 'rm -f "$JAR" "$BODY"' EXIT

FAILED=0
ok()   { echo -e "  \033[32m✓ 通過\033[0m  $1"; }
bad()  { echo -e "  \033[31m✗ 失敗\033[0m  $1"; FAILED=1; }
skip() { echo -e "  \033[33m- 跳過\033[0m  $1"; }
is()   { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1（應為 $3，實際 $2）"; fi; }
code() { curl --noproxy "*" -s -o "$BODY" -w '%{http_code}' "$@"; }

LIST="$BASE/api/results?tab=pending&filter=all&sort=id&order=desc&page=0&limit=200&brands=LIFE,OUTDOOR,Z%2B,MAIN,JEANS,JNR,JKIDS,JSPORT"

echo "=================================================="
echo "🧪 Style Curator AI - 16 項全鏈路功能自動驗收"
echo "• 測試目標: $BASE"
echo "• 認證金鑰: ${APP_AUTH_TOKEN:0:6}***"
echo "=================================================="

# 1~3: 登入與重定向
is "1 未登入打開首頁會 303 跳轉" "$(code "$BASE/")" 303
is "2 登入頁能正常打開" "$(code "$BASE/login")" 200
if grep -q '{%' "$BODY"; then bad "3 login.html 移除模板標籤檢查"; else ok "3 login.html 靜態參數解析正常"; fi

# 4~7: 認證防禦與登入校驗
is "4 未登入存取受保護 API 返回 401" "$(code "$LIST")" 401
is "5 偽造的 cookie 請求被拒絕" "$(code -H 'Cookie: gs_session=9999999999.abc' "$LIST")" 401

HEAD="$(curl --noproxy "*" -s -o /dev/null -D - --data-urlencode 'password=definitely-wrong' "$BASE/login")"
if echo "$HEAD" | grep -qi 'location:.*error=wrong'; then ok "6 密碼錯誤時給出正確提示"; else bad "6 密碼錯誤時給出正確提示"; fi

curl --noproxy "*" -s -o /dev/null -c "$JAR" --data-urlencode "password=$APP_AUTH_TOKEN" "$BASE/login"
if grep -q gs_session "$JAR"; then ok "7 密碼正確成功登入並下發 Cookie"; else bad "7 密碼正確成功登入並下發 Cookie"; fi

# 8~13: 工作台首頁與 API 調用
is "8 登入後首頁能正常打開" "$(code -b "$JAR" "$BASE/")" 200
if grep -q 'apiFetch' "$BODY"; then ok "9 首頁為審圖工作台介面"; else bad "9 首頁為審圖工作台介面"; fi
is "10 登入後存取審核列表返回 200" "$(code -b "$JAR" "$LIST")" 200
if grep -q '"results"' "$BODY" && grep -q '"total"' "$BODY"; then ok "11 審核列表回傳格式完整 (含 results 和 total)"; else bad "11 審核列表回傳格式完整"; fi

THUMB="$(grep -o '"thumb_name": *"[A-Za-z0-9._-]*"' "$BODY" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
if [ -n "$THUMB" ]; then is "12 縮略圖介面可正常存取" "$(code -b "$JAR" "$BASE/image/thumbnails/$THUMB")" 200; else skip "12 沒有可用來測試的縮略圖"; fi

is "13 攜帶 Bearer Token 外部呼叫正常" "$(code -H "Authorization: Bearer $APP_AUTH_TOKEN" "$LIST")" 200

# 14~16: 三檔標籤一致性
level() {
    code -b "$JAR" "${LIST/filter=all/filter=$2}" >/dev/null
    FOUND="$(grep -o '"level": *"[^"]*"' "$BODY" | sed 's/.*"\([^"]*\)"$/\1/' | sort -u)"
    if [ -z "$FOUND" ]; then skip "$1 資料庫暫無「$3」的測試款式"
    elif [ "$FOUND" = "$3" ] || [ "$FOUND" = "$4" ]; then ok "$1 篩選「$3」結果標籤一致"
    else bad "$1 篩選「$3」結果標籤一致（實際: $(echo $FOUND)）"; fi
}
level 14 high '非常符合' '\u975e\u5e38\u7b26\u5408'
level 15 mid '中度符合' '\u4e2d\u5ea6\u7b26\u5408'
level 16 low '不符合' '\u4e0d\u7b26\u5408'

echo "=================================================="
if [ "$FAILED" = 0 ]; then
    echo -e "\033[32m🎉 驗收完畢：全部通過！系統處於生產就緒狀態。\033[0m"
else
    echo -e "\033[31m❌ 驗收未通過，請檢查上述失敗項。\033[0m"
fi
echo "=================================================="

exit $FAILED
