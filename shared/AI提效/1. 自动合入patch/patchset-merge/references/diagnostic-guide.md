# 诊断参考手册

Phase 3 合入过程中出现冲突或编译失败时查阅此文件。

---

## 冲突类型分类与解决

用在策略⑦手解冲突的 Step 1 诊断阶段。

| 冲突类型 | 诊断方法 | 解决方式 |
|---------|---------|---------|
| 上下文偏移 | patch hunk 行号与目标文件对不上，但上下文内容能部分匹配 | 手动调整 `@@` 行号，或回到策略④用 `patch --fuzz` |
| 空白差异 | 内容相同但缩进/空白风格不同 | 回到策略③ `git am --ignore-whitespace` |
| 函数签名变更 | 目标仓库中函数多了参数、返回值类型变了 | 提取目标仓库签名 → 适配 patch 中的调用 → `git add` + `git commit` |
| 部分已合入 | 部分 hunk 的目标代码已存在 | 回到策略⑥ `git apply --reject`，忽略已合入的 .rej |
| 文件被移动 | 文件在目标仓库的路径不同 | `find <source> -name "basename"` 找到实际路径 → `sed` 替换 patch 中路径 |
| 头文件缺失 | patch 引用的 `#include` 在目标仓库不存在 | `find <source> -name "*.h" \| xargs grep -l "<符号>"` 找等价头文件，或从 `--upstream` 引入 |
| 结构性冲突 | 目标仓库对该文件做了大规模重构 | 分析 patch 语义意图 → AI 自行分析 → 选择最优方案执行 |

**冲突解决规则**: 优先保留 patchset 的修改内容。目标仓库中与 patchset 无关的已有代码不能擅自删除。

**检测冲突文件**:
```bash
git diff --name-only --diff-filter=U
```

---

## 编译错误分类与修复策略

用在 fix-compile loop 的步骤 3（分析错误）。

| 错误类型 | 诊断特征 | 修复方式 |
|---------|---------|---------|
| 未声明的函数 | `implicit declaration of function` / `undefined reference to` | 搜索目标仓库中该函数的声明位置 → 添加 `#include` 或在源文件中添加 `extern` 声明 |
| 类型不匹配 | `incompatible pointer type` / `expected 'X' but argument is of type 'Y'` | 检查目标仓库中函数签名的实际定义 → 在 patch 的调用处适配类型（加 cast、调整参数） |
| 结构体成员不存在 | `has no member named` | 搜索目标仓库中该结构体的实际定义 → 找到等价成员名或移除对该成员的引用 |
| 未定义的宏 | `'X' undeclared`（大写标识符） | 搜索目标仓库中该宏的定义位置 → 添加对应 `#include`，或就地 `#define`（仅当目标仓库确实没有） |
| 语法错误 | `expected ';'` / `expected '}'` | 检查冲突解决时是否引入了多余/缺少的标记 → 逐行比对冲突标记位置 |
| 重复定义 | `redefinition of` | patch 新增的符号在目标仓库已存在 → 删除 patch 中的重复定义，保留目标仓库版本 |
| 变量未使用 | `unused variable` | 如果 patch 引入了但后续代码未引用 → 保留变量（可能被后续 patch 使用），注掉 warning；如果是残留代码 → 删除 |
| 文件不存在 | `No such file or directory`（编译命令引用） | patch 新增/修改的文件未被 Makefile/Kconfig 正确引用 → 临时修改 Makefile 添加编译目标，commit 后 `git checkout -- Makefile` 还原 |
| Kconfig 依赖缺失 | `depends on` 相关错误 | 检查目标仓库的 Kconfig 层级 → 添加缺失的 config 依赖项 |
| 环境/配置问题 | `CONFIG_XXX` 未定义、Makefile 缺少目标、编译选项不兼容等，且**错误不是 patch 代码引起的** | **临时修改**：改 config/Makefile 使编译通过 → commit → 立即 `git checkout -- <被修改的配置文件>` 还原。在分析文档中记录临时修改了什么、为什么需要改 |

---

## 编译验证命令

```bash
if test -f build.sh; then
    bash build.sh 2>&1 | tail -40
elif test -f Makefile; then
    make -j$(nproc) 2>&1 | tail -40
elif test -f CMakeLists.txt; then
    mkdir -p build && cd build && cmake .. && make -j$(nproc) 2>&1 | tail -40
else
    echo "未找到 build.sh / Makefile / CMakeLists.txt，跳过编译验证"
fi
```

## 区分错误来源的方法

将错误中的符号/函数名在合入前的代码中检查：
```bash
git show HEAD^:<file> | grep "<symbol>"
# 或
grep -r "<symbol>" <source_dir>
```
对比前后差异，判断是 patch 自身代码问题还是环境/配置问题。避免使用 `git stash`（stash pop 可能重新引入已解决的冲突）。
