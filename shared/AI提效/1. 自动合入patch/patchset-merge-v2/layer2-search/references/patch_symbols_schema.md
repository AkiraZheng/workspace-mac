# patch_symbols.json Schema

由 `shared-scripts/extract_patch_symbols.py` 生成，Layer 2 步骤 7 调用。供步骤 8 计算编译检查点和 merge_tasks.json 聚合使用。

## 完整 Schema

```json
{
  "0001": {
    "subject": "arm64/sysreg: Add HDBSS related register information",
    "introduced_symbols": ["HDBSSBR_EL2", "HDBSS_EL2"],
    "referenced_symbols": ["sys_reg", "read_sysreg"],
    "changed_files": ["arch/arm64/include/asm/sysreg.h", "arch/arm64/tools/sysreg"],
    "功能分类": "infra",
    "feature_signature": {
      "keywords": ["HDBSS", "FEAT_HDBSS", "Hardware Dirty Bit"],
      "scope_dirs": ["arch/arm64/kvm/", "arch/arm64/include/", "arch/arm64/tools/"]
    },
    "depends_on": [],
    "risk_level": "中",
    "review_required": "中",
    "blame_hits": [],
    "conflicts_predicted": [],
    "special_notes": "",
    "action": "apply",
    "skip_reason": ""
  }
}
```

## 字段说明

| 字段 | 来源 | 说明 |
|------|------|------|
| `subject` | 脚本 | patch 标题 |
| `introduced_symbols` | 脚本 | 本 patch 新增/修改的符号列表 |
| `referenced_symbols` | 脚本 | 本 patch 引用/调用的符号列表 |
| `changed_files` | 脚本 | 涉改文件路径列表 |
| `功能分类` | 脚本 → AI 修正 | infra/core/driver/fs/net/sound/doc/bugfix |
| `feature_signature.keywords` | AI 分析 | 语义关键词（非机械截取） |
| `feature_signature.scope_dirs` | AI 分析 | 限定搜索范围目录 |
| `depends_on` | AI 分析 | 前置 task_id 列表 |
| `risk_level` | AI 分析 | `高` / `中` / `低` |
| `review_required` | AI 分析 | `高` / `中` / `低` |
| `blame_hits` | AI 分析 | git blame 追溯的 bugfix commit 列表 |
| `conflicts_predicted` | AI 分析 | 预判冲突点 |
| `special_notes` | AI 分析 | 合入注意事项 |
| `action` | AI 分析 | `apply` / `skip` |
| `skip_reason` | AI 分析 | 若 skip，必须填写原因 |

## 功能分类规则

| 分类 | 判定规则 | 示例路径 |
|------|---------|---------|
| `infra` | `include/linux/*.h`, `include/uapi/*.h`, `arch/*/include/`, diff 中 `#define`/`typedef`/`struct` 定义行占比 > 30% | `include/linux/kvm_host.h` |
| `core` | `kernel/`, `mm/`, `arch/*/kernel/`, `arch/*/mm/`, `init/` | `kernel/sched/core.c` |
| `driver` | `drivers/`, `arch/*/mach-*/` | `drivers/gpu/arm/` |
| `fs` | `fs/`, `include/linux/fs*.h` | `fs/ext4/` |
| `net` | `net/`, `include/linux/net*.h`, `include/net/` | `net/core/dev.c` |
| `sound` | `sound/`, `include/sound/` | `sound/soc/` |
| `doc` | `Documentation/`, commit message 含 "doc"/"comment"/"documentation" | `Documentation/kvm/` |
| `bugfix` | commit message 含 "fix"/"bug"/"error"/"patch"/"Fixes:" 且独立于特性系列 | 修复补丁 |
