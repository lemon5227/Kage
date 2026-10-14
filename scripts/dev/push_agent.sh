#!/bin/bash
# Kage push agent: lets sandboxed assistants (Claude in its Linux VM, cheaper models) request a
# `git push` that runs on the Mac with the user's own credentials. Installed once via launchd.
#
# A request is a file  .kage-push/requests/<name>.json  containing {"branch": "<name>"}.
# Only branches matching a pattern in .kage-push/allowed.txt are pushed; never --force,
# never arbitrary commands. Results go to .kage-push/results/<name>.json and agent.log.
set -u
REPO="${KAGE_REPO:-/Users/wenbo/Kage}"
Q="$REPO/.kage-push"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
mkdir -p "$Q/requests" "$Q/results" "$Q/done"
[ -f "$Q/allowed.txt" ] || printf 'evidence/*\nclaude/*\n' > "$Q/allowed.txt"
log() { echo "$(date '+%F %T') $*" >> "$Q/agent.log"; }

for req in "$Q"/requests/*.json; do
  [ -e "$req" ] || exit 0
  name=$(basename "$req" .json)
  branch=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("branch",""))' "$req" 2>/dev/null)
  status="rejected"; detail=""
  if [[ ! "$branch" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    detail="invalid branch name"
  else
    allowed=0
    while IFS= read -r pattern; do
      [ -z "$pattern" ] && continue
      [[ "$branch" == $pattern ]] && allowed=1
    done < "$Q/allowed.txt"
    if [ "$allowed" -ne 1 ]; then
      detail="branch not in allowed.txt"
    elif ! git -C "$REPO" rev-parse --verify --quiet "refs/heads/$branch" >/dev/null; then
      detail="local branch does not exist"
    else
      out=$(git -C "$REPO" push origin "refs/heads/$branch:refs/heads/$branch" 2>&1); rc=$?
      detail="$out"
      [ $rc -eq 0 ] && status="pushed" || status="failed"
    fi
  fi
  /usr/bin/python3 - "$Q/results/$name.json" "$branch" "$status" "$detail" <<'PY'
import json, sys, time
json.dump({"branch": sys.argv[2], "status": sys.argv[3], "detail": sys.argv[4][-2000:],
           "at": time.strftime('%Y-%m-%d %H:%M:%S')}, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
PY
  mv "$req" "$Q/done/$name.json"
  log "$name $branch $status"
done
