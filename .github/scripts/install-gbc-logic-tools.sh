#!/usr/bin/env bash
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]
archive="$RUNNER_TEMP/oss-cad-suite-linux-x64-20261112.tgz"
curl --fail --location --retry 3 --output "$archive" \
  https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-11-12/oss-cad-suite-linux-x64-20261112.tgz
printf '%s  %s\n' 346499255e3e5e6e9bf67e1d378a4e6bc249abd3de3b0caf5b57604bc8ba1752 "$archive" | sha256sum --check
mkdir -p "$RUNNER_TEMP/gbc-yosys-tools"
tar -xzf "$archive" -C "$RUNNER_TEMP/gbc-yosys-tools"
echo "$RUNNER_TEMP/gbc-yosys-tools/oss-cad-suite/bin" >> "$GITHUB_PATH"
