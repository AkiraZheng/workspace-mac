# BUILD_FIX 策略指南

编译失败时的修复策略和硬性约束。

## 硬性约束

```
❌ 禁止 git reset --hard（会删除之前 commit 的 patch）
❌ 禁止 git reset --soft（会打乱 commit 历史）
❌ 禁止批量 git commit --amend（多个 patch 合并为一个 commit）
❌ 禁止自动执行编译产物生成命令（gen-sysreg.awk、生成头文件、生成配置等）
❌ 禁止覆盖手工维护的文件（如 sysreg.h、某些头文件）

✅ 允许 git rebase -i HEAD~N（回溯并修改指定范围）
✅ 允许 git commit --amend --no-edit（仅修正当前 commit）
✅ 编译验证只执行 BUILD_CMD 中定义的命令
```

## 根因定位：三重匹配

1. **文件匹配**：定位编译错误的具体文件
2. **符号匹配**：定位编译错误涉及的函数名/宏名/类型名
3. **功能匹配**：确认该符号属于哪个 patch 引入

## rebase amend 修复流程

```bash
# 1. 确定出错范围
N=<出错 patch 到当前 checkpoint 的 patch 数>

# 2. 进入交互式 rebase
git rebase -i HEAD~$N

# 3. 编辑错误文件
vim <错误文件>

# 4. 编译验证（删除旧产物避免 timestamp 跳过）
rm -f arch/arm64/boot/Image
make ARCH=$KERNEL_ARCH -j$(nproc)

# 5. 仅 stage 修改的文件
git add <只修改的文件>

# 6. amend 当前 commit
git commit --amend --no-edit

# 7. 继续 rebase
git rebase --continue
```

## 编译错误分类处理

| 错误类型 | 处理方式 |
|---------|---------|
| patch 代码本身的语法/逻辑错误 | 编辑源文件最小修复 |
| 调用不存在的符号 | 标记为缺失依赖，尝试最小适配或 stub |
| 非 patch 的 config 问题 | 临时改 .config → make → git restore .config，记录在 analyse.md |

## 手工文件保护

以下文件类型通常是手工维护的，patch 修改它们时需提示用户确认：
- `arch/arm64/include/asm/sysreg.h`
- `include/linux/kvm_host.h`
- `Makefile` / `Kconfig`

若发现编译失败需修复 → 仅修改 patch 涉及的文件，不生成新文件。
任何额外的编译/生成命令（如 awk、python 脚本生成代码）必须经用户明确确认。
