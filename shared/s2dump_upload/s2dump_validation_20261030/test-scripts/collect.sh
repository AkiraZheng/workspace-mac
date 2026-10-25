#!/bin/bash
# 用法: collect.sh <输出文件> — 捕获当前运行 VM 的 stage2 dump + meta
OUT="$1"; DIR=""
for d in /sys/kernel/debug/kvm/*/; do
    if [ -f "$d/stage2_page_tables" ]; then DIR="$d"; break; fi
done
[ -z "$DIR" ] && { echo "ERROR: no VM with stage2_page_tables found" >&2; exit 1; }
cat "$DIR/stage2_page_tables" > "$OUT"
echo "--- dump: $OUT ($(grep -c "^0x" "$OUT") lines, vm dir: $DIR)"
echo "levels=$(cat $DIR/stage2_levels 2>/dev/null) ipa_range=$(cat $DIR/ipa_range 2>/dev/null)"
