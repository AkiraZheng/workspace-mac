# Merge Patchset Command

使用 b4 从 lore.kernel.org 下载并合入 patchset 到指定源码。

## 核心约束（绝对遵守）

**【最重要】以下约束必须100%遵守：**

1. **逐个合入** - 按顺序一个一个 patch 合入
2. **逐个 commit** - 每个成功的 patch 必须单独 commit
3. **解决问题** - 遇到问题（冲突、版本不匹配等）必须解决
4. **询问用户** - 当前 patch 合入失败时，询问用户如何处理
5. **保留分支** - 合入结果分支必须保留，**绝不删除**
6. **中文输出** - 所有思考、解释、输出必须使用中文

**合入策略（按顺序尝试）：**
1. git am → 成功则 commit → 继续下一个
2. git am 失败 + 有冲突 → 解冲突 → commit → 继续下一个
3. git am 失败 + 无冲突 → 尝试 git apply --3way → commit → 继续下一个
4. 还失败 → 尝试 git apply + 手动 commit → 继续下一个
5. 全部失败 → **询问用户如何处理**

**注意**：不是跳过失败，是**必须解决当前 patch 或询问用户如何处理**。

## 安装（首次使用）

```bash
cd /path/to/patchset-merge
./install.sh
```

## 使用方式

```
/merge-patchset <patch_url> [选项]
```

## 参数

| 参数 | 说明 |
|------|------|
| `patch_url` | **必需** lore.kernel.org 上的 patch URL |

## 选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--source <目录>` | 源码 git 仓库路径 | 当前目录 `.` |
| `--branch <名称>` | merge 使用的 git 分支名 | 自动从 patch 主题生成 |

## 示例

```bash
/merge-patchset https://lore.kernel.org/lkml/xxx/
/merge-patchset https://lore.kernel.org/lkml/xxx/ --source /path/to/linux --branch my-branch
```

## 工作流程

1. **检查 b4** - 如果没有，自动安装
2. **下载 patchset** - 使用 `b4 am` 获取完整 mbox
3. **拆分 patch** - 将 mbox 拆分为单个 patch
4. **逐个合入** - 对每个 patch 尝试合入策略
5. **解决问题** - 遇到问题尝试多种方法解决
6. **询问用户** - 所有策略失败时，询问用户如何处理
7. **逐个 commit** - 每个成功的 patch 立即 commit
8. **编译验证** - 成功后编译验证
9. **生成报告** - `.patchset-diff.md` 记录差异

## 失败时询问用户

当 patch 合入失败时，会显示：

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                           Patch 合入失败                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

【Patch 1】 KVM: arm64: Introduce new flag for non-cacheable IO memory

【已尝试的策略】
  1. git am
  2. 解冲突 (保留 patch 内容)
  3. git apply --3way
  4. git apply (手动)

【错误信息】
  尝试 git apply 时失败...

【冲突文件】
  - arch/arm64/include/asm/kvm_pgtable.h
  - arch/arm64/kvm/mmu.c

请选择如何处理：
  1. 继续尝试手动解决冲突
  2. 跳过此 patch，继续下一个（不推荐）
  3. 停止整个合入流程
```

## 差异报告

合入完成后生成 `.patchset-diff.md`，记录：
- 每个 patch 的合入状态和 commit hash
- 失败的 patch、错误原因
- 解冲突记录
- 编译错误和警告

## 分支保留

**重要**：合入完成后分支会被保留！

**安全保障**：合入操作**永远不会在主干分支上进行**！
- 不指定 `--branch` 时，自动根据 patch 主题生成分支名
- 如果自动生成的分支名已存在，会自动生成带时间戳的唯一名称
- 用户指定 `--branch` 时，也会在新分支上工作（如果已存在同名分支，会自动重命名）

## 查找 patch URL

1. 访问 https://lore.kernel.org/
2. 搜索或浏览找到需要的 patch series
3. 点击任意一个 patch，复制浏览器地址栏的 URL
