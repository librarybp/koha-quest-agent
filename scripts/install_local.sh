#!/usr/bin/env bash
# Install the Koha Library Guide on the same Ubuntu PC as Koha.
# Usage: sudo bash scripts/install_local.sh               (auto-detects hardware)
#        sudo bash scripts/install_local.sh --local-model  (force Ollama on this PC)
set -euo pipefail

APP=/opt/koha-quest-agent
SRC="$(cd "$(dirname "$0")/.." && pwd)"
SVC_USER=koha-quest

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

echo "== 1. System packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl openssl >/dev/null

echo "== 2. Copy files to $APP"
install -d "$APP"
if [ "$SRC" != "$APP" ]; then cp -r "$SRC"/. "$APP"/; fi
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$SVC_USER"

echo "== 3. Python environment"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "== 4. Can this PC run the model?"
RAM_GB=$(awk '/MemTotal/ {printf "%d", ($2/1024/1024)+0.5}' /proc/meminfo)
HAS_AVX=no; grep -qw avx /proc/cpuinfo && HAS_AVX=yes
LOCAL=no
if [ "${1:-}" = "--local-model" ]; then LOCAL=yes
elif [ "$HAS_AVX" = yes ] && [ "$RAM_GB" -ge 16 ]; then LOCAL=yes; fi
echo "   RAM ${RAM_GB} GB, AVX: $HAS_AVX -> local model: $LOCAL"

echo "== 5. Settings (.env)"
if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"
  sed -i "s|^AGENT_SECRET=.*|AGENT_SECRET=$(openssl rand -hex 32)|" "$APP/.env"
fi
chmod 600 "$APP/.env"
chown -R "$SVC_USER":"$SVC_USER" "$APP"

if [ "$LOCAL" = yes ]; then
  echo "== 6. Ollama on this PC"
  MODEL=qwen2.5:7b; [ "$RAM_GB" -lt 16 ] && MODEL=qwen2.5:1.5b
  sed -i "s|^LLM_BASE_URL=.*|LLM_BASE_URL=http://127.0.0.1:11434/v1|; s|^LLM_MODEL=.*|LLM_MODEL=$MODEL|" "$APP/.env"
  command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
  systemctl enable --now ollama >/dev/null 2>&1 || true
  ollama pull "$MODEL"
else
  echo "== 6. Skipping Ollama: this PC is too slow for a language model."
  echo "   Set LLM_BASE_URL in .env to Ollama on a stronger PC (http://<that-PC-IP>:11434/v1)"
  echo "   or to a hosted OpenAI-compatible API. See comments in .env."
fi

echo "== 7. Service"
cat > /etc/systemd/system/koha-quest-agent.service <<EOF
[Unit]
Description=Koha Library Guide (MCP agent)
After=network-online.target ollama.service

[Service]
User=$SVC_USER
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
ExecStart=$APP/venv/bin/python $APP/agent.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable koha-quest-agent >/dev/null

if grep -q '^KOHA_CLIENT_ID=replace-me' "$APP/.env"; then
  echo
  echo "Installed. Next:"
  echo "  1. sudo nano $APP/.env   (KOHA_BASE_URL, KOHA_CLIENT_ID, KOHA_CLIENT_SECRET, OPAC_ORIGIN)"
  echo "  2. cd $APP && sudo -u $SVC_USER venv/bin/python scripts/check_koha.py <test_patron_id>"
  echo "  3. sudo systemctl start koha-quest-agent"
else
  systemctl restart koha-quest-agent
  echo "Installed and started. Status: systemctl status koha-quest-agent"
fi
