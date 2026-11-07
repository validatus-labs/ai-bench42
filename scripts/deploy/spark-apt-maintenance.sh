#!/usr/bin/env bash
# Purpose: Run serialized native Spark APT maintenance, with an explicit dry run.
# Identity: root on spark-a922, normally through the owned systemd service.
# Inputs: security|weekly, optionally --dry-run; root-owned native APT policy.
# Effects: Refresh package lists; simulate or install upgrades; retain journal logs.
# Example: sudo /usr/local/libexec/ai-model/apt-maintenance security --dry-run
# Flow: validate -> root/host -> shared lock -> refresh -> security|weekly -> result.
# Failure: Stop on an unsuccessful command; never remove packages or reboot.
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l LC_ALL=C

usage() { printf 'Usage: %s security|weekly [--dry-run]\n' "$0"; }
[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 2; }
MODE="$1"
[[ "$MODE" == security || "$MODE" == weekly ]] || { usage >&2; exit 2; }
DRY_RUN=false
if [[ $# == 2 ]]; then
  [[ "$2" == --dry-run ]] || { usage >&2; exit 2; }
  DRY_RUN=true
fi
[[ $EUID -eq 0 ]] || { printf 'ERROR: run as root\n' >&2; exit 1; }
[[ "$(/usr/bin/hostname -s)" == "${MODEL_BENCH_HOSTNAME:-spark-a922}" ]] || {
  printf 'ERROR: this maintenance contract belongs to spark-a922\n' >&2; exit 1;
}
[[ -f /etc/apt/apt.conf.d/99ai-model-updates ]] || {
  printf 'ERROR: native update policy missing\n' >&2; exit 1;
}

# /var/lib is native host-maintenance state, independent of the source mirror.
/usr/bin/install -d -o root -g root -m 0700 /var/lib/ai-model-apt-maintenance
exec 9>/var/lib/ai-model-apt-maintenance/maintenance.lock
/usr/bin/flock --exclusive --wait 7200 9
printf '{"event":"start","mode":"%s","dry_run":%s,"utc":"%s"}\n' \
  "$MODE" "$DRY_RUN" "$(/usr/bin/date -u +%FT%TZ)"
on_exit() {
  local result=$?
  trap - EXIT
  local reboot=false
  [[ ! -e /run/reboot-required ]] || reboot=true
  printf '{"event":"finish","mode":"%s","dry_run":%s,"exit_code":%s,"reboot_required":%s,"utc":"%s"}\n' \
    "$MODE" "$DRY_RUN" "$result" "$reboot" "$(/usr/bin/date -u +%FT%TZ)"
  exit "$result"
}
trap on_exit EXIT

# Fail on any repository refresh error; do not continue with partially stale lists.
/usr/bin/apt-get -o DPkg::Lock::Timeout=1800 -o APT::Update::Error-Mode=any update
if [[ "$MODE" == security ]]; then
  args=(--verbose)
  [[ "$DRY_RUN" == false ]] || args+=(--dry-run)
  /usr/bin/unattended-upgrade "${args[@]}"
else
  args=(--no-remove --with-new-pkgs -o DPkg::Lock::Timeout=1800
    -o Dpkg::Options::=--force-confold)
  if [[ "$DRY_RUN" == true ]]; then args+=(--simulate); else args+=(--yes); fi
  /usr/bin/apt-get "${args[@]}" upgrade
fi
