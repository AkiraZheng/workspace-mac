#!/bin/bash
# T-GE-03/04/05 校验 — 用法: check-ge.sh <数据目录>
DIR="${1:-/home/zt/olk-data}"
UPPER=0x0000080000000000
for f in "$DIR"/*.txt; do
    name=$(basename "$f"); prev_end=""; first=1
    ok_cont=PASS; ok_upper=PASS; ok_geom=PASS
    while read -r line; do
        case "$line" in "---"*) continue;; esac
        range=$(echo "$line" | awk "{print \$1}")
        [ -z "$range" ] && continue
        start=${range%%-*}; end=${range##*-}
        lvl=$(echo "$line" | awk "{print \$3}")
        szu=$(echo "$line" | awk "{print \$2}")
        sz=${szu//[KMGT]/}
        case "$szu" in *K) bytes=$((sz*1024));; *M) bytes=$((sz*1048576));; *G) bytes=$((sz*1073741824));; *) bytes=$szu;; esac
        if [ $first -eq 1 ]; then first=0; else
            [ "$start" != "$prev_end" ] && { ok_cont=FAIL; echo "  [$name] 断裂: $prev_end -> $start"; }
        fi
        prev_end=$end
        case "$lvl" in 1) g=1073741824;; 2) g=2097152;; 3) g=4096;; *) g=0;; esac
        if [ $g -gt 0 ] && [ $((bytes % g)) -ne 0 ]; then ok_geom=FAIL; echo "  [$name] 粒度违规: $szu lvl=$lvl"; fi
    done < "$f"
    [ "$prev_end" == "$UPPER" ] || { ok_upper=FAIL; echo "  [$name] 上界不符: $prev_end"; }
    printf "%-18s cont=%-4s upper=%-4s geom=%s\n" "$name" $ok_cont $ok_upper $ok_geom
done
