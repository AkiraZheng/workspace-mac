# 用户交互指南

## 交互流程

Layer 1 负责：解析用户输入 → 校验路径 → 配置 .config → 确认 → 生成 config.json。

### 步骤序列

1. **解析用户输入**：从用户一句话描述中提取 `patch_source`、`kernel_repo_path`、`kernel_branch`、`upstream_repo_path`
2. **路径校验**：验证目标仓库存在且是 git repo，上游仓库可选
3. **基线分支检测**：自动检测干净基线分支（优先级：OLK-6.6 > master > main），若无干净基线则问询用户
4. **创建工作分支**：从基线创建 `patch_merge_{FEATURE}` 工作分支，若已存在加 `_v2` / `_v3` 后缀
5. **.config 来源配置**：
   - 检查 `$KERNEL_REPO/.patchmerge/config_preference.json` 是否有上次配置，可复用
   - 选项 1：使用已有 .config
   - 选项 2：提供完整 .config 文件路径 → cp → olddefconfig
   - 选项 3：增量 config 片段 → merge_config.sh → olddefconfig
6. **架构检测**：从 .config 提取 `KERNEL_ARCH`，生成 `BUILD_CMD`
7. **场景确认**：展示完整配置给用户确认
8. **写入 config.json**：落盘到 `$KERNEL_REPO/patch_analysis/config.json`（固定入口），其余输出文件放入 `$KERNEL_REPO/patchmerge/<分支名>_output/`

## 错误处理

| 错误类型 | 退出码 | 处理方式 |
|---------|--------|---------|
| 目标仓库不存在 | 10 | 输出错误，中止 |
| 目标仓库非 git repo | 11 | 输出错误，中止 |
| 用户指定分支不存在 | 12 | 输出错误，中止 |
| 用户指定分支不干净 | 13 | 输出错误，中止 |
| 手动输入基线分支不存在 | 14 | 输出错误，中止 |
| 用户中止操作 | 15 | 输出提示，中止 |
| 无效选择 | 16 | 输出错误，中止 |
| 切换基线分支失败 | 17 | 输出错误，中止 |
| 创建工作分支失败 | 18 | 输出错误，中止 |
| 用户拒绝确认 | 20 | 输出配置，中止 |

## .config 偏好机制

`$KERNEL_REPO/.patchmerge/config_preference.json` 保存用户上次选择的 .config 来源配置。后续执行时优先复用，用户可选择清除重新配置。

```json
{
  "option": 2,
  "full_config_path": "/home/user/my-kernel.config",
  "base_config": null,
  "incremental_path": null,
  "last_used": "2026-05-30T12:00:00Z"
}
```
