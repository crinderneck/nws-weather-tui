#!/usr/bin/env bash
# Claude Code PostToolUse hook: after an edit to a Python file under src/ or
# tests/, run the fast suite (everything not marked slow, ~3 s). On failure,
# exit 2 so the failing output is fed back to Claude.
set -u
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
file="$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')"

case "$file" in
  "$root"/src/*.py|"$root"/tests/*.py) ;;
  *) exit 0 ;;
esac

python="$root/.venv/bin/python"
[ -x "$python" ] || python=python3

out="$(cd "$root" && "$python" -m pytest tests -q -x -m "not slow" -p no:cacheprovider 2>&1)"
status=$?
if [ "$status" -ne 0 ]; then
  {
    echo "Fast tests failed after editing ${file#"$root"/}:"
    printf '%s\n' "$out" | tail -n 60
    echo "(If a rendering change is intended: .venv/bin/python -m pytest --update-snapshots)"
  } >&2
  exit 2
fi
exit 0
