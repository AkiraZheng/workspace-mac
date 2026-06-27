# config.json Schema

Layer 1 产出，Layer 2/3/4 消费。当前 schema_version: `1.0`。

## 完整 Schema

```json
{
  "schema_version": "1.0",
  "patch_source": "<用户提供的 patch 来源>",
  "kernel_repo_path": "<内核仓库绝对路径>",
  "kernel_branch": "<操作分支名（工作分支）>",
  "baseline_branch": "<基线分支名>",
  "kernel_arch": "arm64",
  "build_cmd": "make ARCH=arm64 -j$(nproc)",
  "upstream_repo_path": "<上游仓库路径 或 null>",
  "output_dir": "<输出目录，格式 $KERNEL_REPO/patchmerge/<分支名>_output>",
  "scene": "unknown|upgrade|backport",
  "user_input_original": "<用户原始输入>",
  "extracted_at": "<ISO 8601 时间戳>"
}
```

## 字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|:--:|------|------|
| `schema_version` | ✓ | string | 接口版本号，当前 `"1.0"`。Layer 2 入口校验 |
| `patch_source` | ✓ | string | patch 来源（message-id / URL / 本地路径） |
| `kernel_repo_path` | ✓ | string | 目标内核仓库绝对路径 |
| `kernel_branch` | ✓ | string | Layer 1 自动创建的工作分支名 |
| `baseline_branch` | ✓ | string | 基线分支名。openEuler 仓库常见值为 `"OLK-6.6"` 或 `"master"`；其他仓库以实际命名约定为准 |
| `kernel_arch` | ✓ | string | 固定为 `"arm64"`。本 skill 专用于 aarch64 架构，其他架构不支持 |
| `build_cmd` | ✓ | string | 编译命令，固定为 `make ARCH=arm64 -j$(nproc)` |
| `upstream_repo_path` | - | string/null | 上游仓库路径，无则为 null |
| `output_dir` | ✓ | string | 所有输出文件的根目录，格式 `$KERNEL_REPO/patchmerge/<分支名>_output`。各层从此目录读写中间结果和最终输出 |
| `scene` | ✓ | string | 合入场景：初始 `unknown`，Layer 2 步骤 3 由用户选择后设为 `upgrade` 或 `backport` |
| `user_input_original` | ✓ | string | 用户原始输入文本（用于调试和追溯） |
| `extracted_at` | ✓ | string | 配置提取时间戳 |
