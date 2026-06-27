---
name: linux-kernel-review
description: >
  内核 patch 合入后的专项代码 review。触发条件：patch 合入完成后、需要检查 commit message 完整性、
  代码安全性（内存/锁/错误处理）、API 兼容性、patch 意图保留情况。适用于 Linux 内核 arm64 架构。
---

# Code Review Expert — 内核 patch 合入专用

## 职责

对已合入的每个 patch commit 进行内核专项 review，在 Layer 3 步骤 5.8 被调用。review 基于 `verify_patch_intent.py` 的意图校验结果 + git 实际 diff。

## 输入

```bash
# 1. 意图校验结果（Layer 3 步骤 5.4 已执行，AI 已知退出码和输出）
verify_patch_intent.py:
  退出码 0 → + 行完整、符号完整
  退出码 1 → 部分 + 行缺失（可能是适配，需 AI 判断）
  退出码 3 → introduced_symbols 缺失（严重，立即报 P0）

# 2. 获取本次 commit 信息
git show HEAD            # diff 内容
git log -1 --format=full # commit message 完整格式
```

## 检查项

### 1. Commit message 完整性

| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| Subject | 不能空，开头应有子系统前缀（如 `arm64:`, `KVM:`, `mm:`），不超过 75 字符 | P1 |
| Signed-off-by | 至少有一个 DCO 签名，格式 `Signed-off-by: Name <email>` | P1 |
| Fixes tag | 如果原 patch 有 `Fixes:` tag，合入后不应丢失 | P2 |
| 其他 tag | Reviewed-by、Acked-by、Tested-by、Cc 等应保留 | P3 |
| 空行分隔 | Subject 和 body 之间应有空行 | P3 |

### 2. 代码安全性

| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| 内存配对 | kmalloc/kfree、alloc_pages/free_pages、kref_init/kref_put 是否成对 | P0 |
| goto cleanup | 错误路径是否跳转到正确的 cleanup label，有无遗漏释放 | P0 |
| 锁使用 | spin_lock/spin_unlock 配对，持锁期间不应睡眠（might_sleep） | P0 |
| RCU | rcu_read_lock/rcu_read_unlock 配对，rcu_dereference 使用是否正确 | P1 |
| 错误返回值 | 函数返回指针需用 IS_ERR/PTR_ERR 检查，-ENOMEM 风格一致 | P1 |
| 数组/缓冲区 | 是否有越界风险，sizeof 是否正确，snprintf 长度 | P1 |
| refcount | refcount_t 或 atomic_t 的 inc/dec 是否配对 | P1 |

### 3. API 兼容性（backport 专属）

| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| 函数存在性 | 目标内核中是否有被调用的函数原型 | P0 |
| 签名匹配 | 函数参数数量/类型是否与目标内核版本一致 | P0 |
| 宏/CONFIG | 依赖的 CONFIG_xxx 宏在目标 .config 中是否有定义 | P0 |
| 结构体字段 | 访问的结构体成员在目标内核版本中是否存在 | P1 |
| 头文件 | include 的头文件路径是否在目标内核中存在 | P2 |

### 4. Patch 意图保留

| 检查点 | 规则 | 严重度 |
|--------|------|--------|
| introduced_symbols 缺失 | verify_patch_intent exit 3 → 直接报 P0，核心功能代码丢失 | P0 |
| + 行缺失 | verify_patch_intent exit 1 → AI 逐个分析缺失行是适配差异还是意外丢失 | P1/P2 |
| + 行完整 | verify_patch_intent exit 0 → 通过 | — |

## 输出格式

```markdown
## Code Review — Patch {task_id}: {subject}

### Commit message
✅ Subject 完整
✅ Signed-off-by 存在
⚠️ P2: 缺少 Fixes tag（原 patch 有）

### 安全性
- [P0] file.c:123 kmalloc 后无对应 kfree（错误路径 goto err_cleanup 中缺少）
- [P1] file.c:456 spin_lock 后调用 might_sleep 函数

### API 兼容
- [P0] 目标内核 5.10 中 kvm_stage2_flush_range 签名不同，参数 3 为 bool 而非 int
✅ 其他 API 调用签名一致

### Patch 意图
- [P1] hdbss.c:89 缺失行 +hdbss_dbg("init done") → 调试日志，适配时去掉，可接受
✅ 其余 14/15 行完整
✅ introduced_symbols 全部存在

### 总结
P0: 2, P1: 2, P2: 1, P3: 0
建议：修复 P0 后再提交，P1 可与用户确认后处理
```

## 严重度定义

| 级别 | 含义 | 操作 |
|------|------|------|
| **P0** | 内存泄漏/越界/死锁/符号缺失/API 不兼容 → 导致编译失败或运行时崩溃 | 必须修复 |
| **P1** | 逻辑错误/锁问题/错误路径不完整/核心 `+` 行丢失 | 建议修复 |
| **P2** | Commit message 不完整/API 签名细微差异/调试代码缺失 | 信息记录 |
| **P3** | 风格/格式/次要建议 | 可选改进 |
