#!/usr/bin/env bash
# Run as validatus on Spark. Validates and deploys one JSON-defined model.
# Input: model ID (default kolibri-1). Effects: runtime release and owned systemd service.
# ./scripts/bootstrap.sh kolibri-1
# profile -> vllmctl deploy -> isolated venv -> systemd -> health / rollback
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec /usr/bin/python3 -B "${package_dir}/vllmctl.py" deploy "${1:-kolibri-1}"
