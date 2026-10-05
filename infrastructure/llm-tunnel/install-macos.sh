#!/bin/sh
# Installs the demo LLM tunnel as permanent macOS services (launchd, current user):
#   com.nova.llm-proxy   authenticated proxy → local OpenAI-compatible server (LM Studio :1234 by default)
#   com.nova.llm-tunnel  Cloudflare quick tunnel + supervisor that keeps Railway's NOVA_LLM_BASE_URL in sync
# Usage: install-macos.sh <railway-project-id> [path/to/cloudflared] [upstream-url]
# The proxy key is ~/.nova-llm-tunnel/key (created if missing: set it as NOVA_LLM_API_KEY in Railway).
set -eu
PROJECT="$1"
SRC_CLOUDFLARED="${2:-$(command -v cloudflared || true)}"
UPSTREAM="${3:-http://127.0.0.1:1234}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="$HOME/.nova-llm-tunnel"
AGENTS="$HOME/Library/LaunchAgents"
UV="$(command -v uv)"
RAILWAY="$(command -v railway)"
mkdir -p "$DIR" "$AGENTS"
chmod 700 "$DIR"
cp "$HERE/proxy.py" "$HERE/supervisor.py" "$DIR/"
[ -n "$SRC_CLOUDFLARED" ] && [ "$SRC_CLOUDFLARED" != "$DIR/cloudflared" ] && cp "$SRC_CLOUDFLARED" "$DIR/cloudflared"
chmod 755 "$DIR/cloudflared"
if [ ! -s "$DIR/key" ]; then
  (umask 077 && python3 -c "import secrets; print(secrets.token_urlsafe(40))" > "$DIR/key")
  echo "New proxy key created: set it on Railway with  railway variable set NOVA_LLM_API_KEY --stdin -s api < $DIR/key  (and worker, beat)"
fi
chmod 600 "$DIR/key"

cat > "$AGENTS/com.nova.llm-proxy.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nova.llm-proxy</string>
  <key>ProgramArguments</key><array>
    <string>$UV</string><string>run</string><string>--quiet</string>
    <string>--with</string><string>httpx</string><string>--with</string><string>starlette</string><string>--with</string><string>uvicorn</string>
    <string>uvicorn</string><string>proxy:app</string><string>--app-dir</string><string>$DIR</string>
    <string>--host</string><string>127.0.0.1</string><string>--port</string><string>11500</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PROXY_KEY_FILE</key><string>$DIR/key</string>
    <key>LLM_UPSTREAM_URL</key><string>$UPSTREAM</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:$(dirname "$UV")</string>
  </dict>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/proxy.log</string>
  <key>StandardErrorPath</key><string>$DIR/proxy.log</string>
</dict></plist>
PLIST

cat > "$AGENTS/com.nova.llm-tunnel.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nova.llm-tunnel</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$DIR/supervisor.py</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>CLOUDFLARED</key><string>$DIR/cloudflared</string>
    <key>RAILWAY</key><string>$RAILWAY</string>
    <key>RAILWAY_PROJECT</key><string>$PROJECT</string>
    <key>STATE_DIR</key><string>$DIR</string>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:$(dirname "$RAILWAY")</string>
  </dict>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/tunnel.log</string>
  <key>StandardErrorPath</key><string>$DIR/tunnel.log</string>
</dict></plist>
PLIST

for label in com.nova.llm-proxy com.nova.llm-tunnel; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
done
echo "Installed. Logs: $DIR/proxy.log, $DIR/tunnel.log. Uninstall: launchctl bootout gui/\$(id -u)/com.nova.llm-{proxy,tunnel}; rm $AGENTS/com.nova.llm-*.plist"
