#!/usr/bin/env bash
# Greenfield, version-pinned, idempotent Playwright MCP/Chromium research tool.
# Install: sudo bash tools/rollout/install-playwright-research.sh --greenfield --user cosmos
# Verify:  bash tools/rollout/install-playwright-research.sh --verify-only
# This does NOT modify the existing central Playwright/Brave/Deep-Research service.
set -Eeuo pipefail
umask 022

APP=modelbench-playwright
ROOT=/opt/modelbench-playwright
BIN=/usr/local/bin/modelbench-playwright-mcp
MCP_VERSION=0.0.83
MCP_COMMIT=f183dad4a52965583e3cc1d59b88cdc279e2e57d
NODE_VERSION=22.22.2
NODE_SHA_ARM64=e9e1930fd321a470e29bb68f30318bf58e3ecb4acb4f1533fb19c58328a091fe
NODE_SHA_X64=88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a
TOOL_ORIGINS='https://docs.python.org;https://developer.mozilla.org;https://www.rfc-editor.org;https://datatracker.ietf.org;https://playwright.dev'
ACCOUNT=cosmos
MODE=plan
GREENFIELD=0
DEEP_ROOT=''
STAGE=''

log() { printf '[%s] %s\n' "$APP" "$*"; }
fail() { printf '[%s] ERROR: %s\n' "$APP" "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: install-playwright-research.sh [--plan|--greenfield|--install|--verify-only|--smoke|--print-client] [--user USER] [--deep-research-root DIR]
 --plan                 Show pins/paths; no mutations (default).
 --greenfield           Install signed distro prerequisites and pinned tool; requires root.
 --install              Install pinned tool; prerequisites already present; requires root.
 --verify-only          Verify pinned release, manifest, launcher, browser, no mutations.
 --smoke                Verify and launch local data: Chromium page as operations user.
 --print-client         Show shared MCP client configuration; no mutations.
 --user USER            Existing unprivileged user (default cosmos).
 --deep-research-root   Check EXISTING Deep-Research validator; no unpinned install.
This intentionally installs one SHARED BINARY but starts one ISOLATED browser
session per model trial. No shared HTTP listener, no account creation, no
App-Update registration, no external Gold access or private browser profiles.
HELP
}
while (($#)); do
  case "$1" in
    --plan) MODE=plan; shift ;;
    --greenfield) MODE=install; GREENFIELD=1; shift ;;
    --install) MODE=install; shift ;;
    --verify-only) MODE=verify; shift ;;
    --smoke) MODE=smoke; shift ;;
    --print-client) MODE=client; shift ;;
    --user) (($# >= 2)) || fail '--user needs an argument'; ACCOUNT="$2"; shift 2 ;;
    --deep-research-root) (($# >= 2)) || fail '--deep-research-root needs a path'; DEEP_ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done
[[ "$ACCOUNT" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail 'invalid service-user name'
[[ "$(uname -s)" == Linux ]] || fail 'Linux only'
case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64; NODE_SHA="$NODE_SHA_ARM64" ;;
  x86_64|amd64) ARCH=x64; NODE_SHA="$NODE_SHA_X64" ;;
  *) fail 'unsupported architecture: pinned Node only supports Linux ARM64/x64' ;;
esac
RELEASE_NAME="mcp-$MCP_VERSION-${MCP_COMMIT:0:12}-node-$NODE_VERSION-$ARCH"
RELEASE="$ROOT/releases/$RELEASE_NAME"
TARGET="releases/$RELEASE_NAME"

check_user() {
  local entry
  entry="$(getent passwd "$ACCOUNT" || true)"
  [[ -n "$entry" ]] || fail "create the non-root $ACCOUNT account separately; will not auto-create users"
  (( $(id -u "$ACCOUNT") > 0 )) || fail 'service user cannot be root'
  GROUP="$(id -gn "$ACCOUNT")"
  HOME_DIR="$(cut -d: -f6 <<<"$entry")"
  [[ -d "$HOME_DIR" && "$HOME_DIR" != / && "$HOME_DIR" != /root ]] || fail 'operations home invalid'
}
prerequisites() {
  local cmd
  for cmd in curl git tar xz sha256sum runuser getent id cut stat readlink realpath install cmp grep sed chmod chown mv mktemp flock; do
    command -v "$cmd" >/dev/null || fail "missing prerequisite $cmd; use --greenfield"
  done
}
check_deep_research() {
  [[ -n "$DEEP_ROOT" ]] || return 0
  local canonical validator
  canonical="$(realpath -e "$DEEP_ROOT")" || fail 'Deep-Research path does not exist'
  validator="$canonical/scripts/validate_coverage.py"
  [[ -f "$validator" && -r "$validator" && ! -L "$validator" ]] || fail 'Deep-Research coverage validator missing'
  log "Deep-Research source checked (not installed or enabled), validator SHA256: $(sha256sum "$validator" | cut -d' ' -f1)"
  log 'Any extra Deep-Research tools must be separately pinned and enabled for every trial.'
}
bootstrap_os_packages() {
  [[ -r /etc/os-release ]] || fail 'cannot determine OS'
  # shellcheck source=/dev/null
  . /etc/os-release
  case "$ID:$VERSION_ID" in
    ubuntu:24.04*)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y ca-certificates curl git tar xz-utils coreutils util-linux python3 \
        libnss3 libnspr4 libgbm1 libxkbcommon0 libgtk-3-0t64 libatk1.0-0t64 \
        libatk-bridge2.0-0t64 libasound2t64 libx11-xcb1 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libpango-1.0-0 libcairo2 libdrm2
      ;;
    rocky:10*)
      dnf -y install ca-certificates curl git tar xz coreutils util-linux python3 \
        nss nspr atk at-spi2-atk gtk3 mesa-libgbm alsa-lib glib2 \
        libX11 libXcomposite libXdamage libXfixes libXrandr pango cairo
      ;;
    *) fail "--greenfield accepts Ubuntu 24.04 or Rocky Linux 10; got $ID $VERSION_ID" ;;
  esac
}
runtime_integrity() {
  [[ -d "$RELEASE" && ! -L "$RELEASE" ]] || fail 'missing or symlinked pinned release'
  [[ "$(stat -c '%U:%G' "$RELEASE")" == root:root ]] || fail 'release must be root-owned'
  [[ -x "$RELEASE/node/bin/node" ]] || fail 'pinned Node binary missing'
  [[ -r "$RELEASE/mcp/package-lock.json" && -r "$RELEASE/mcp/cli.js" ]] || fail 'MCP runtime missing'
  [[ -r "$RELEASE/MANIFEST" ]] || fail 'runtime manifest missing'
  grep -Fxq "mcp_commit=$MCP_COMMIT" "$RELEASE/MANIFEST" || fail 'source pin mismatch'
  grep -Fxq "mcp_version=$MCP_VERSION" "$RELEASE/MANIFEST" || fail 'MCP pin mismatch'
  grep -Fxq "node_version=$NODE_VERSION" "$RELEASE/MANIFEST" || fail 'Node pin mismatch'
  grep -Fxq "node_archive_sha256=$NODE_SHA" "$RELEASE/MANIFEST" || fail 'Node checksum pin mismatch'
  local recorded_node_sha observed_node_sha recorded_browser_sha browser_binary
  recorded_node_sha="$(sed -n 's/^node_executable_sha256=//p' "$RELEASE/MANIFEST")"
  observed_node_sha="$(sha256sum "$RELEASE/node/bin/node" | cut -d' ' -f1)"
  [[ -n "$recorded_node_sha" && "$recorded_node_sha" == "$observed_node_sha" ]] || fail 'Node executable changed'
  grep -Fxq "tool_allowed_origins=$TOOL_ORIGINS" "$RELEASE/MANIFEST" || fail 'origin policy mismatch'
  local expected actual chromium cli
  expected="$(sed -n 's/^npm_lock_sha256=//p' "$RELEASE/MANIFEST")"
  actual="$(sha256sum "$RELEASE/mcp/package-lock.json" | cut -d' ' -f1)"
  [[ -n "$expected" && "$expected" == "$actual" ]] || fail 'lock file changed'
  [[ "$("$RELEASE/node/bin/node" --version)" == "v$NODE_VERSION" ]] || fail 'Node version drift'
  cli="$("$RELEASE/node/bin/node" "$RELEASE/mcp/cli.js" --version)" || fail 'MCP binary failed'
  [[ "$cli" == "$MCP_VERSION" || "$cli" == "Version $MCP_VERSION" ]] || fail "MCP version drift: $cli"
  chromium="$(PLAYWRIGHT_BROWSERS_PATH="$RELEASE/browsers" "$RELEASE/node/bin/node" -e "process.stdout.write(require('$RELEASE/mcp/node_modules/playwright').chromium.executablePath())")" || fail 'cannot resolve Chromium'
  [[ -x "$chromium" ]] || fail "Chromium binary unavailable: $chromium"
  recorded_browser_sha="$(sed -n 's/^chromium_executable_sha256=//p' "$RELEASE/MANIFEST")"
  [[ -n "$recorded_browser_sha" && "$recorded_browser_sha" == "$(sha256sum "$chromium" | cut -d' ' -f1)" ]] || fail 'Chromium executable changed'
}
verify_install() {
  runtime_integrity
  [[ -L "$ROOT/current" && "$(readlink "$ROOT/current")" == "$TARGET" ]] || fail 'wrong or absent current pointer'
  [[ -x "$BIN" && ! -L "$BIN" && "$(stat -c '%U:%G' "$BIN")" == root:root ]] || fail 'launcher is absent/untrusted'
  grep -Fq 'MODELBENCH_RUN_ID' "$BIN" || fail 'unexpected launcher contents'
  log "pinned release verified: $RELEASE_NAME"
}
smoke() {
  check_user
  runuser -u "$ACCOUNT" -- env HOME="$HOME_DIR" \
    PLAYWRIGHT_BROWSERS_PATH="$RELEASE/browsers" \
    MODEL_PLAYWRIGHT_MODULE="$RELEASE/mcp/node_modules/playwright" \
    "$RELEASE/node/bin/node" - <<'NODE'
const {chromium} = require(process.env.MODEL_PLAYWRIGHT_MODULE);
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    await page.goto('data:text/html,<html><title>ModelBench ready</title></html>');
    if (await page.title() !== 'ModelBench ready') throw Error('wrong title');
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exit(1); });
NODE
  log 'Chromium local smoke PASS (no network required)'
}
client_help() {
  cat <<'CLIENT'
# Shared Codex MCP fragment; use the SAME executable and policy for ALL models:
[mcp_servers.playwright_research]
command = "/usr/local/bin/modelbench-playwright-mcp"
[mcp_servers.playwright_research.env]
MODELBENCH_RUN_ID = "REPLACE_WITH_IMMUTABLE_RUN_ID"
MODELBENCH_RUN_OUTPUT_DIR = "/absolute/private/isolated/trial/build/browser"

# Kilo/OpenCode/etc: supply the same command and env in their native MCP config.
# IMPORTANT: Worker must also enforce external egress deny/allow rules, prevent
# access to reference repositories, other model trials and HPI TEST/EVAL Gold.
CLIENT
}

if [[ "$MODE" == plan ]]; then
  log "Pinned Playwright MCP $MCP_VERSION @ $MCP_COMMIT"
  log "Pinned Node $NODE_VERSION ($ARCH), archive SHA256 $NODE_SHA"
  log "Release: $RELEASE"
  log "Public command: $BIN"
  log "Research origins: $TOOL_ORIGINS"
  log 'No changes to existing Playwright-MCP HTTP, Brave, systemd or App-Update.'
  exit 0
fi
if [[ "$MODE" == client ]]; then client_help; exit 0; fi
if [[ "$MODE" == install ]] && (( EUID != 0 )); then
  fail 'installation needs root; the resulting browser must NEVER run as root'
fi
if [[ "$MODE" == install ]] && (( GREENFIELD )); then
  # OS changes only under explicitly requested greenfield mode.
  if [[ -d "$RELEASE" && -L "$ROOT/current" && -x "$BIN" ]]; then
    prerequisites
    verify_install
    log 'unchanged installation; no OS package refresh'
    exit 0
  fi
  bootstrap_os_packages
fi
prerequisites
check_deep_research
if [[ "$MODE" == verify ]]; then verify_install; exit 0; fi
if [[ "$MODE" == smoke ]]; then verify_install; smoke; exit 0; fi
[[ "$MODE" == install ]] || fail 'invalid operation'
check_user
install -d -o root -g root -m 0755 "$ROOT" "$ROOT/releases" /usr/local/bin
exec 9>"$ROOT/.installer.lock"
flock -n 9 || fail 'another rollout is active'

# On interrupted rollouts a fully verified release can be reused. Never
# overwrite an unknown release, conflicting launcher or different current.
if [[ -d "$RELEASE" ]]; then
  runtime_integrity
else
  [[ ! -e "$RELEASE" && ! -L "$RELEASE" ]] || fail 'unsafe release collision'
  STAGE="$(mktemp -d "$ROOT/releases/.stage.XXXXXXXX")"
  cleanup() {
    if [[ -n "$STAGE" && -d "$STAGE" && "$STAGE" == "$ROOT"/releases/.stage.* ]]; then
      rm -rf -- "$STAGE"
    fi
  }
  trap cleanup EXIT
  chown "$ACCOUNT:$GROUP" "$STAGE"
  chmod 0700 "$STAGE"
  NODE_ARCHIVE="node-v$NODE_VERSION-linux-$ARCH.tar.xz"
  curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --retry 3 \
    --max-time 240 "https://nodejs.org/dist/v$NODE_VERSION/$NODE_ARCHIVE" \
    -o "$STAGE/$NODE_ARCHIVE"
  printf '%s  %s\n' "$NODE_SHA" "$STAGE/$NODE_ARCHIVE" | sha256sum -c - >/dev/null || fail 'Node SHA256 mismatch'
  runuser -u "$ACCOUNT" -- mkdir "$STAGE/node"
  runuser -u "$ACCOUNT" -- tar -xJf "$STAGE/$NODE_ARCHIVE" -C "$STAGE/node" --strip-components=1
  rm -- "$STAGE/$NODE_ARCHIVE"
  [[ "$("$STAGE/node/bin/node" --version)" == "v$NODE_VERSION" ]] || fail 'Node extraction failed'
  runuser -u "$ACCOUNT" -- git clone -q --depth 1 --branch "v$MCP_VERSION" \
    https://github.com/microsoft/playwright-mcp.git "$STAGE/mcp"
  [[ "$(git -C "$STAGE/mcp" rev-parse HEAD)" == "$MCP_COMMIT" ]] || fail 'upstream source SHA mismatch'
  [[ "$("$STAGE/node/bin/node" -p "require('$STAGE/mcp/package.json').version")" == "$MCP_VERSION" ]] || fail 'package pin mismatch'
  [[ -r "$STAGE/mcp/package-lock.json" ]] || fail 'upstream lock missing'
  runuser -u "$ACCOUNT" -- env HOME="$HOME_DIR" PATH="$STAGE/node/bin:/usr/bin:/bin" \
    npm --prefix "$STAGE/mcp" ci --omit=dev --ignore-scripts --no-audit --no-fund
  runuser -u "$ACCOUNT" -- env HOME="$HOME_DIR" PATH="$STAGE/node/bin:/usr/bin:/bin" \
    PLAYWRIGHT_BROWSERS_PATH="$STAGE/browsers" \
    "$STAGE/node/bin/node" "$STAGE/mcp/node_modules/playwright/cli.js" install chromium
  # Local headless smoke before publishing; real website access is unnecessary.
  runuser -u "$ACCOUNT" -- env HOME="$HOME_DIR" PLAYWRIGHT_BROWSERS_PATH="$STAGE/browsers" \
    MODEL_PLAYWRIGHT_MODULE="$STAGE/mcp/node_modules/playwright" \
    "$STAGE/node/bin/node" - <<'NODE'
const {chromium} = require(process.env.MODEL_PLAYWRIGHT_MODULE);
(async () => {
  const b = await chromium.launch({headless:true});
  try {
    const p = await b.newPage();
    await p.goto('data:text/html,<title>greenfield-ready</title>');
    if (await p.title() !== 'greenfield-ready') throw Error('browser smoke failed');
  } finally { await b.close(); }
})().catch(e => { console.error(e.message); process.exit(1); });
NODE
  cat >"$STAGE/MANIFEST" <<EOF
mcp_commit=$MCP_COMMIT
mcp_version=$MCP_VERSION
node_version=$NODE_VERSION
node_archive_sha256=$NODE_SHA
node_executable_sha256=$(sha256sum "$STAGE/node/bin/node" | cut -d' ' -f1)
chromium_executable_sha256=$(PLAYWRIGHT_BROWSERS_PATH="$STAGE/browsers" "$STAGE/node/bin/node" -e "process.stdout.write(require('$STAGE/mcp/node_modules/playwright').chromium.executablePath())" | xargs sha256sum | cut -d' ' -f1)
npm_lock_sha256=$(sha256sum "$STAGE/mcp/package-lock.json" | cut -d' ' -f1)
tool_allowed_origins=$TOOL_ORIGINS
EOF
  rm -rf -- "$STAGE/mcp/.git"
  chown -R root:root "$STAGE"
  chmod -R go-w "$STAGE"
  chmod 0755 "$STAGE"
  mv -- "$STAGE" "$RELEASE"
  STAGE=''
  runtime_integrity
fi

# A dedicated STDIO tool is safer for independent model trials than one
# shared HTTP MCP process with shared cookies/tabs/tool state.
TMP="$(mktemp /usr/local/bin/.modelbench-research.XXXXXXXX)"
cat >"$TMP" <<'WRAPPER'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
(( EUID != 0 )) || { echo 'Research browser cannot run as root' >&2; exit 2; }
[[ "${MODELBENCH_RUN_ID:-}" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'MODELBENCH_RUN_ID required' >&2; exit 2; }
[[ -n "${MODELBENCH_RUN_OUTPUT_DIR:-}" && "$MODELBENCH_RUN_OUTPUT_DIR" == /* ]] || { echo 'Absolute run output directory required' >&2; exit 2; }
[[ ! -L "$MODELBENCH_RUN_OUTPUT_DIR" ]] || { echo 'Output symlink forbidden' >&2; exit 2; }
install -d -m 0700 -- "$MODELBENCH_RUN_OUTPUT_DIR"
REL="$(realpath -e /opt/modelbench-playwright/current)"
[[ "$REL" == /opt/modelbench-playwright/releases/* ]] || exit 2
export PLAYWRIGHT_BROWSERS_PATH="$REL/browsers"
# Playwright's allowed-origins is NOT a network security boundary.
# The coordinator must also enforce an egress firewall/allowlist externally.
exec "$REL/node/bin/node" "$REL/mcp/cli.js" \
  --headless --isolated --block-service-workers --no-webmcp \
  --codegen=none --image-responses=omit \
  --allowed-origins='https://docs.python.org;https://developer.mozilla.org;https://www.rfc-editor.org;https://datatracker.ietf.org;https://playwright.dev' \
  --output-dir="$MODELBENCH_RUN_OUTPUT_DIR" "$@"
WRAPPER
chmod 0755 "$TMP"
chown root:root "$TMP"
if [[ -e "$BIN" || -L "$BIN" ]]; then
  [[ -f "$BIN" && ! -L "$BIN" && "$(stat -c '%U:%G' "$BIN")" == root:root ]] || fail 'unsafe launcher collision'
  cmp -s "$TMP" "$BIN" || fail 'existing launcher differs; explicit reconciliation needed'
  rm -- "$TMP"
else
  mv -- "$TMP" "$BIN"
fi
if [[ -L "$ROOT/current" ]]; then
  [[ "$(readlink "$ROOT/current")" == "$TARGET" ]] || fail 'current points to a different release'
elif [[ -e "$ROOT/current" ]]; then
  fail 'current pointer collision'
else
  ln -s -- "$TARGET" "$ROOT/.current.pending"
  mv -T -- "$ROOT/.current.pending" "$ROOT/current"
fi
verify_install
log "installed: $BIN"
log "next: --print-client, then freeze matching model tool budgets"
