#!/usr/bin/env bash
# ដំឡើង Qoder CLI ដោយស្វ័យប្រវត្តិ រួចផ្ទៀងផ្ទាត់ថាប្រើបាន។
#   ./scripts/install_qoder.sh          → VPS/Cloud Shell: ដំឡើង ឬ បញ្ជាក់ថាមានស្រាប់
#   VERCEL=1 ./scripts/install_qoder.sh → Serverless: រំលង (exit 0 ទ always)
set -euo pipefail

# ⚠️ Platform Detection — Serverless គ្មាន filesystem អចិន្ត៚យ ហើយ build មិនត្រូវការ CLI ទេ
if [ -n "${VERCEL:-}" ] || [ -n "${VERCEL_ENV:-}" ] || [ -n "${NETLIFY:-}" ] || [ -n "${AWS_LAMBDA_FUNCTION_NAME:-}" ]; then
  echo "⏭️  Serverless platform detected — រំលងការដំឡើង Qoder CLI"
  echo "    (Qoder CLI ដំណើរការបានតែលើ VPS/Cloud Shell/Render/Railway ដែលមាន filesystem និរន្តរភាព)"
  exit 0
fi

BIN_NAME="${QODER_CLI_BIN:-qodercli}"
INSTALL_URL="https://qoder.com/install"
LOCAL_BIN="$HOME/.local/bin"

found=""
for candidate in "$BIN_NAME" qodercli qoder; do
  if command -v "$candidate" >/dev/null 2>&1; then
    found="$candidate"
    break
  fi
done

if [ -z "$found" ]; then
  echo "⚠️  រកមិនឃើញ '$BIN_NAME' — កំពុងដំឡើងពី $INSTALL_URL ..."
  curl -fsSL "$INSTALL_URL" | bash
  export PATH="$LOCAL_BIN:$PATH"
  command -v "$BIN_NAME" >/dev/null 2>&1 || found="qodercli"
fi

# បន្ថែម PATH ទៅ ~/.bashrc បើកូវវាខ្វះ (ទើប login ថ្មីរកឃើញ)
if [ -f "$HOME/.bashrc" ] && ! grep -qF 'export PATH="$HOME/.local/bin:$PATH"' "$HOME/.bashrc"; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >>"$HOME/.bashrc"
  echo "➕ បានបន្ថែម ~/.local/bin ទៅ ~/.bashrc"
fi
export PATH="$LOCAL_BIN:$PATH"

if ! command -v "$BIN_NAME" >/dev/null 2>&1; then
  echo "❌ នៅតែរកមិនឃើញ '$BIN_NAME' ក្រោយដំឡើង។" >&2
  echo "   សូមរត់: curl -fsSL $INSTALL_URL | bash ដោយខ្លួនឯង រួចមើល Error។" >&2
  echo "   ឬបើកឃ្លាំងរួច កំណត់ QODER_CLI_BIN ក្នុង .env ទៅផ្លូវពិត (ឧ. $LOCAL_BIN/qodercli)" >&2
  exit 1
fi

resolved="$(command -v "$BIN_NAME")"
echo "✅ Qoder CLI: $resolved"
echo "   Version: $("$BIN_NAME" --version 2>&1 | head -1)"
if [ -n "${QODER_PROXY_SKIP_LOGIN:-}" ]; then
  echo "   (រំលងការពិនិត្យ login)"
elif "$BIN_NAME" status 2>&1 | grep -qiE 'not logged in|please login|unauthor'; then
  echo "⚠️  មិនទាន់ login — សូមរត់: $BIN_NAME login" >&2
  exit 1
fi
echo "🎉 ត្រៀមរួចសម្រាប់ ./scripts/run_qoder_proxy.sh"
