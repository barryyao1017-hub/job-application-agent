#!/bin/bash
# Installs (or reinstalls) the launchd schedules for scripts/run-automation.sh.
# Times are local (America/Los_Angeles). A run missed while the Mac was asleep
# fires once on wake. Usage: scripts/install-schedules.sh [--uninstall]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/claude-automations"
mkdir -p "$AGENTS" "$LOGS"

# name|StartCalendarInterval dicts
# The daily job pipeline is a Claude desktop scheduled task (job-application-pipeline-daily)
# because it needs Chrome, Gmail and the to-do artifact; remove its old launchd job.
launchctl bootout "gui/$(id -u)/com.jiayiyao.claude.job-pipeline" 2>/dev/null || true
rm -f "$AGENTS/com.jiayiyao.claude.job-pipeline.plist"

SCHEDULES=(
  "google-l4-monitor|<dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict><dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>"
  "weekly-ai-stock|<dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>"
)

for entry in "${SCHEDULES[@]}"; do
  name="${entry%%|*}"
  intervals="${entry#*|}"
  label="com.jiayiyao.claude.$name"
  plist="$AGENTS/$label.plist"

  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$plist"
    echo "removed $label"
    continue
  fi

  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$REPO/scripts/run-automation.sh</string>
    <string>$name</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>$intervals</array>
  <key>StandardOutPath</key><string>$LOGS/$name.launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$name.launchd.log</string>
</dict>
</plist>
EOF
  plutil -lint "$plist" >/dev/null
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "installed $label"
done
