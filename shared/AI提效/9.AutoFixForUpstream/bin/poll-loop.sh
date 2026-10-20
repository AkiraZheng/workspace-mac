#!/bin/bash
# autofix-upstream 常驻 poll 循环(替代不可用的 cron):
#   flock 防双跑,按 series.yaml 的 poll.interval_hours 轮询。
# 启动: nohup setsid ~/autofix-upstream/bin/poll-loop.sh >> ~/autofix-upstream/poll.log 2>&1 &
# 停止: pkill -f poll-loop.sh
# 系列清单: ~/autofix-upstream/config/poll-series.list,每行 "<repo绝对路径> <series-id>"
set -uo pipefail

PROJECT_ROOT="${AFU_PROJECT_ROOT:-$HOME/autofix-upstream}"
LOCK="$PROJECT_ROOT/.poll-loop.lock"
LIST="$PROJECT_ROOT/config/poll-series.list"

exec 9>"$LOCK"
flock -n 9 || { echo "poll-loop 已在运行($(cat "$LOCK" 2>/dev/null)),退出"; exit 0; }
echo $$ > "$LOCK"

[ -f "$LIST" ] || { echo "缺少 $LIST(每行: <repo> <series-id>)"; exit 2; }

log() { echo "[$(date '+%F %T')] loop: $*"; }
log "启动,系列清单: $LIST"

while true; do
    # 间隔取所有系列的分钟粒度最小值(默认 4h)
    INTERVAL_HOURS=$(python3 - "$PROJECT_ROOT" "$LIST" <<'EOF'
import sys, yaml
from pathlib import Path
root, lst = sys.argv[1], sys.argv[2]
vals = []
for line in Path(lst).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    repo, sid = line.split()
    cfgp = Path(repo) / ".autofix" / sid / "series.yaml"
    if cfgp.is_file():
        try:
            vals.append((yaml.safe_load(cfgp.read_text()) or {}).get("poll", {}).get("interval_hours", 4))
        except Exception:
            pass
print(min(vals) if vals else 4)
EOF
)
    SLEEP=$((INTERVAL_HOURS * 3600))

    while read -r repo sid; do
        [ -z "${repo:-}" ] && continue
        case "$repo" in \#*) continue ;; esac
        bash "$PROJECT_ROOT/bin/poll.sh" "$repo" "$sid" || log "poll $sid 失败(退出码 $?),继续"
    done < "$LIST"

    log "本轮完成,休眠 ${INTERVAL_HOURS}h"
    sleep "$SLEEP"
done
