#!/bin/bash
# autofix-upstream 部署脚本(仿 patch-merge-workflow 的部署模式)
#   1) rsync 项目 -> ~/autofix-upstream (PROJECT_ROOT,本地运行,解 SSHFS 慢盘)
#   2) 注册 Claude Code plugin(~/.claude/skills/autofix-upstream 单目录布局)
#   3) 环境依赖检查(python/b4/patch-merge-workflow)
# 绝不删除/覆盖任何第三方 skill(历史事故教训)。
set -euo pipefail

SRC_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${AFU_PROJECT_ROOT:-$HOME/autofix-upstream}"
PLUGIN_DIR="$HOME/.claude/skills/autofix-upstream"
MIN_CLAUDE_MAJOR=2 MIN_CLAUDE_MINOR=1 MIN_CLAUDE_PATCH=157

log() { echo "[install] $*"; }
die() { echo "[install] 错误: $*" >&2; exit 1; }

# ---------- 1) 部署 PROJECT_ROOT ----------
log "源: $SRC_ROOT"
log "部署到: $PROJECT_ROOT"
mkdir -p "$PROJECT_ROOT"
rsync -a --delete \
    --exclude='.git' --exclude='.claude' --exclude='.pytest_cache' \
    --exclude='__pycache__' --exclude='.DS_Store' --exclude='poll.log' \
    --exclude='.poll-loop.lock' \
    "$SRC_ROOT"/ "$PROJECT_ROOT"/
mkdir -p "$PROJECT_ROOT/config"
[ -f "$PROJECT_ROOT/config/poll-series.list" ] || cat > "$PROJECT_ROOT/config/poll-series.list" <<'EOF'
# 常驻 poll 的系列清单,每行: <repo绝对路径> <series-id>
# /home/akira/code/linux/linux hdbss-v6
EOF
chmod +x "$PROJECT_ROOT"/bin/*.sh 2>/dev/null || true

# ---------- 2) Claude Code plugin 注册 ----------
if command -v claude >/dev/null 2>&1; then
    VER=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    log "claude 版本: ${VER:-未知}"
    if [ -n "$VER" ]; then
        read -r MA MI PA <<< "$(echo "$VER" | tr '.' ' ')"
        if [ "${MA:-0}" -lt "$MIN_CLAUDE_MAJOR" ] || \
           [ "${MA:-0}" -eq "$MIN_CLAUDE_MAJOR" -a "${MI:-0}" -lt "$MIN_CLAUDE_MINOR" ] || \
           [ "${MA:-0}" -eq "$MIN_CLAUDE_MAJOR" -a "${MI:-0}" -eq "$MIN_CLAUDE_MINOR" -a "${PA:-0}" -lt "$MIN_CLAUDE_PATCH" ]; then
            log "警告: claude >= $MIN_CLAUDE_MAJOR.$MIN_CLAUDE_MINOR.$MIN_CLAUDE_PATCH 才支持单目录 plugin,当前 $VER,仍继续"
        fi
    fi
    if [ -d "$PLUGIN_DIR" ] && [ ! -f "$PLUGIN_DIR/.claude-plugin/plugin.json" ]; then
        die "$PLUGIN_DIR 已存在且不是本 plugin(无 .claude-plugin/plugin.json),拒绝覆盖 —— 请人工检查"
    fi
    if [ -f "$PLUGIN_DIR/.claude-plugin/plugin.json" ] && \
       ! grep -q '"autofix-upstream"' "$PLUGIN_DIR/.claude-plugin/plugin.json"; then
        die "$PLUGIN_DIR 属于其它 plugin,拒绝覆盖 —— 请人工检查"
    fi
    mkdir -p "$PLUGIN_DIR"
    rsync -a --delete --exclude='.claude' "$PROJECT_ROOT/skills"/ "$PLUGIN_DIR/skills"/
    rsync -a "$PROJECT_ROOT/.claude-plugin"/ "$PLUGIN_DIR/.claude-plugin"/
    log "plugin 已注册: $PLUGIN_DIR(skills: $(ls "$PLUGIN_DIR/skills" | tr '\n' ' '))"
    log "重启 Claude Code session 后 /autofix-upstream 可用"
else
    log "警告: 未找到 claude CLI,跳过 plugin 注册"
fi

# ---------- 3) 依赖检查 ----------
python3 -c "import yaml"        2>/dev/null || log "警告: 缺 pyyaml(dnf install python3-pyyaml)"
python3 -c "import jsonschema"  2>/dev/null || log "警告: 缺 jsonschema(dnf install python3-jsonschema)"
python3 -c "import pytest"      2>/dev/null || log "警告: 缺 pytest(dnf install python3-pytest),仅影响自测"
command -v b4 >/dev/null 2>&1   || log "警告: 缺 b4(pip install b4);lore 拉取也可走 curl 兜底"
[ -d "$HOME/patch-merge-workflow" ] || log "警告: 缺 ~/patch-merge-workflow(init 模式合入依赖它,import/poll/finalize 不需要)"

( cd "$PROJECT_ROOT" && python3 -m compileall -q harness/ ) || die "harness 语法检查失败"
log "harness 语法检查通过"

# ---------- 4) 使用提示 ----------
cat <<EOF

部署完成。
  PROJECT_ROOT : $PROJECT_ROOT
  系列工作区   : <内核repo>/.autofix/<series-id>/
  定时 poll    : nohup setsid $PROJECT_ROOT/bin/poll-loop.sh >> $PROJECT_ROOT/poll.log 2>&1 &
                 (机器重启后需手动拉起;清单见 config/poll-series.list)
  命令         : /autofix-upstream <init|import|poll|triage|fix|status|finalize>
  自测         : cd $PROJECT_ROOT && python3 -m pytest tests/ -v
EOF
