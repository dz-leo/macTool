#!/bin/bash
# Mac 工具管理台 · 一键启动
# 双击即可：服务已在后台运行 → 直接打开工作台；没在 → 自动拉起后台服务。
# 服务由 launchd 托管时，关掉这个终端窗口不影响使用。

URL="http://127.0.0.1:8899"
DIR="$(cd "$(dirname "$0")" && pwd)"

# 1) 服务已在线 → 直接打开浏览器收工
if curl -s -o /dev/null --max-time 1 "$URL/api/ping" 2>/dev/null; then
  open "$URL"
  exit 0
fi

# 2) 已安装 LaunchAgent 但进程没起（比如手动 unload 过）→ 用 launchd 拉起
if [ -f "$HOME/Library/LaunchAgents/com.mactool.bridge.plist" ]; then
  launchctl load -w "$HOME/Library/LaunchAgents/com.mactool.bridge.plist" 2>/dev/null
  for i in $(seq 1 20); do
    if curl -s -o /dev/null --max-time 1 "$URL/api/ping" 2>/dev/null; then
      open "$URL"; exit 0
    fi
    sleep 0.5
  done
fi

# 3) 兜底：nohup 后台启动（脱离终端会话，关窗口不杀进程）
PY=""
for c in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$c" ]; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  osascript -e 'display alert "Mac 工具管理台" message "没有找到 python3，请先安装 Xcode 命令行工具。"'
  exit 1
fi

cd "$DIR" || exit 1
nohup "$PY" mactool-bridge.py >> /tmp/mactool-bridge.log 2>&1 &

for i in $(seq 1 20); do
  if curl -s -o /dev/null --max-time 1 "$URL/api/ping" 2>/dev/null; then
    open "$URL"
    osascript -e 'display notification "服务已在后台运行，关掉终端也没事" with title "Mac 工具管理台"'
    exit 0
  fi
  sleep 0.5
done

osascript -e 'display alert "Mac 工具管理台" message "服务启动失败，日志在 /tmp/mactool-bridge.err"'
exit 1
