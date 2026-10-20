#!/bin/bash
# Runs one scheduled Claude automation headlessly. Invoked by launchd; see
# scripts/install-schedules.sh. Usage: scripts/run-automation.sh NAME
set -uo pipefail

NAME="${1:?usage: run-automation.sh NAME}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$HOME/.claude-automations"
LOGS="$HOME/Library/Logs/claude-automations"
export PATH="$HOME/.local/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# An API key would disable the claude.ai connectors (Gmail) that these runs need.
unset ANTHROPIC_API_KEY

mkdir -p "$LOGS"
LOG="$LOGS/$NAME-$(date +%Y-%m-%d-%H%M).log"

COMMON_TOOLS="Read,Write,Edit,Glob,Grep,ToolSearch,Bash(date:*),Bash(mkdir:*),mcp__claude_ai_Gmail__send_message"
case "$NAME" in
  job-pipeline)
    WORKDIR="$REPO"
    MODEL="opus"
    TIMEOUT_MIN=100
    CHROME="--chrome"
    # Bash(python3 -m job_agent:*) covers every ledger subcommand, including fetch-feeds (feed-based discovery).
    TOOLS="$COMMON_TOOLS,Skill,Agent,SendMessage,WebFetch,Bash(python3 -m job_agent:*),Bash(node local-resume-companion-extension/enqueue-attach.js:*),mcp__claude-in-chrome,mcp__agent-vault__list_accounts,mcp__agent-vault__login,mcp__agent-vault__add_site_domain,mcp__agent-vault__register,mcp__agent-vault__verify_email,mcp__claude_ai_Gmail__search_threads,Bash(curl -s localhost\:9222/json/list),Bash(uv --directory /Users/jiayiyao/Desktop/agent-vault run agent-vault doctor:*)"
    PROMPT="Run the job-application-pipeline skill for today. This is an unattended run: nobody is watching, so never wait for user input; record blockers and continue."
    open -ga "Google Chrome"
    sleep 15
    ;;
  google-l4-monitor|weekly-ai-stock)
    WORKDIR="$STATE/$NAME"
    MODEL=$([ "$NAME" = weekly-ai-stock ] && echo opus || echo sonnet)
    TIMEOUT_MIN=60
    CHROME="--no-chrome"
    TOOLS="$COMMON_TOOLS,Agent,WebSearch,WebFetch,mcp__claude_ai_Robinhood__get_equity_quotes,mcp__claude_ai_Robinhood__get_equity_fundamentals,mcp__claude_ai_Robinhood__get_equity_historicals"
    PROMPT="$(cat "$REPO/automations/$NAME.md")"
    ;;
  *)
    echo "unknown automation: $NAME" >&2
    exit 2
    ;;
esac

mkdir -p "$WORKDIR"
cd "$WORKDIR" || exit 1
echo "[$(date)] starting $NAME in $WORKDIR" >>"$LOG"

claude -p "$PROMPT" \
  --model "$MODEL" \
  $CHROME \
  --permission-mode dontAsk \
  --allowedTools "$TOOLS" \
  >>"$LOG" 2>&1 &
PID=$!

# macOS has no `timeout`; enforce the run budget with a watchdog.
( sleep $((TIMEOUT_MIN * 60)); kill "$PID" 2>/dev/null && echo "[$(date)] killed after ${TIMEOUT_MIN}m" >>"$LOG" ) &
WATCHDOG=$!
wait "$PID"
STATUS=$?
kill "$WATCHDOG" 2>/dev/null

echo "[$(date)] finished $NAME with exit $STATUS" >>"$LOG"
exit "$STATUS"
