---
name: download-patches
description: 从邮件列表下载 patch 的完整工作流。支持 openEuler (HyperKitty)、lore.kernel.org 等邮件归档系统。涵盖 mbox 下载、b4 工具使用、手动提取等方法。
---

# 邮件列表 Patch 下载指南

本 skill 提供从邮件列表归档系统下载 patch 的完整方法，适用于 openEuler、Linux 内核等使用邮件列表开发的开源项目。

---

## 一、方法选择决策树

```
需要下载 patch？
├── 知道 Message-ID？
│   ├── 是 → 方法 1 (b4) 或 方法 2 (手动构造 URL)
│   └── 否 → 先查找 Message-ID（见"查找 Message-ID"章节）
│
├── 有邮件列表网页链接？
│   ├── openEuler (mailweb.openeuler.org) → 方法 3 (HyperKitty 提取)
│   ├── lore.kernel.org → 方法 4 (lore 提取)
│   └── 其他 HyperKitty → 方法 3
│
└── 只有邮件内容？
    └── 方法 5 (从邮件原文提取)
```

---

## 二、查找 Message-ID

### 2.1 从邮件网页查找

1. 打开邮件详情页
2. 查找 `Message-ID:` 字段，通常在邮件头部
3. 或在 URL 中查找（HyperKitty 的 URL 通常包含 message hash）
4. 或在 "Use email software" 链接的 `In-Reply-To=` 参数中查找

**示例：**
```
Message-ID: <20260904055338.1208603-1-zhengtian10@huawei.com>
```

### 2.2 从邮件客户端查找

- **Thunderbird**: 右键邮件 → 查看消息源代码
- **Gmail**: 更多 → 显示原始邮件
- **Outlook**: 文件 → 属性 → Internet 邮件头

### 2.3 从邮件列表归档查找

访问邮件列表归档页面，搜索邮件标题或作者。

---

## 三、方法 1：b4 工具（推荐）

`b4` 是 Linux 内核社区推荐的 patch 提取工具，能自动处理 series 依赖关系。

### 3.1 安装

```bash
# 通过 pip 安装
pip3 install b4

# 或通过包管理器
apt install b4  # Debian/Ubuntu
dnf install b4  # Fedora/openEuler
```

### 3.2 基本用法

```bash
# 通过 Message-ID 下载整个 series
b4 am -o /path/to/output/ <message-id>

# 示例
b4 am -o ./patches/ "20260904055338.1208603-1-zhengtian10@huawei.com"

# 下载指定版本
b4 am -o ./patches/ -v 5 "20260904055338.1208603-1-zhengtian10@huawei.com"

# 只下载 cover letter
b4 am -o ./patches/ --no-partial-reroll "20260904055338.1208603-1-zhengtian10@huawei.com"
```

### 3.3 配置 b4

创建 `~/.config/b4.conf`：

```ini
[b4]
# 默认使用 lore.kernel.org
midmask = https://lore.kernel.org/r/%s
```

### 3.4 注意事项

- `b4` 默认从 lore.kernel.org 获取邮件
- openEuler 邮件列表可能不在 lore 上，需要手动下载 mbox 后用 `b4 am -m local.mbox`
- 如果 Message-ID 找不到，检查是否拼写正确

---

## 四、方法 2：直接下载 mbox（lore.kernel.org）

### 4.1 单个邮件

```bash
# 下载单个邮件的 mbox
curl -o patch.mbox "https://lore.kernel.org/all/<message-id>/"

# 或添加 .mbox 后缀
curl -o patch.mbox "https://lore.kernel.org/all/<message-id>.mbox"
```

### 4.2 整个 thread

```bash
# 下载整个 thread 的 mbox
curl -o thread.mbox "https://lore.kernel.org/all/<message-id>/T.mbox"
```

### 4.3 月度归档

```bash
# 下载某个月的归档
curl -o month.mbox "https://lore.kernel.org/linux-arm-kernel/202609.mbox"
```

---

## 五、方法 3：从 HyperKitty 提取（openEuler）

openEuler 使用 HyperKitty 作为邮件归档系统。

### 5.1 手动提取流程

1. **访问 thread 页面**
   ```
   https://mailweb.openeuler.org/hyperkitty/list/<list-name>/<year>/<month>/
   ```

2. **找到目标 thread**
   - 按日期或标题搜索
   - 点击进入 thread 详情页

3. **提取 Message-ID**
   - 在 "Use email software" 链接中找到 `In-Reply-To=<...>`
   - 或在页面源码中查找 `Message-ID`

4. **构造 mbox URL（如果支持）**
   ```
   # 尝试以下 URL 格式
   https://mailweb.openeuler.org/hyperkitty/list/<list>/<year>/<month>/<message-hash>.mbox
   https://mailweb.openeuler.org/hyperkitty/list/<list>/message/<message-hash>/export
   ```

5. **如果无法直接下载 mbox**
   - 使用浏览器开发者工具查看网络请求
   - 或手动复制邮件内容（见方法 5）

### 5.2 自动化提取脚本

```python
#!/usr/bin/env python3
"""
从 HyperKitty thread 页面提取 patch series
"""
import re
import os
import subprocess
import sys

def extract_patches_from_hyperkitty(thread_url, output_dir):
    """
    从 HyperKitty thread 页面提取所有 patch
    
    Args:
        thread_url: HyperKitty thread 页面 URL
        output_dir: 输出目录
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 下载 thread 页面
    result = subprocess.run(
        ["curl", "-s", thread_url],
        capture_output=True, text=True, timeout=30
    )
    html_content = result.stdout
    
    # 提取所有 message hash
    hash_pattern = re.compile(r'/archives/list/[^/]+/message/([A-Z0-9]+)/')
    hashes = list(set(hash_pattern.findall(html_content)))
    
    print(f"Found {len(hashes)} messages in thread")
    
    # 提取每个 message 的内容
    patches = []
    for i, msg_hash in enumerate(hashes):
        msg_url = f"https://mailweb.openeuler.org/hyperkitty/list/virt@openeuler.org/message/{msg_hash}/"
        
        # 下载单个 message
        result = subprocess.run(
            ["curl", "-s", msg_url],
            capture_output=True, text=True, timeout=30
        )
        msg_html = result.stdout
        
        # 提取 subject
        subject_match = re.search(r'<title>\s*\[PATCH[^]]*\]\s*([^<]+)', msg_html)
        subject = subject_match.group(0) if subject_match else f"patch_{i}"
        
        # 提取邮件正文（在 <pre> 或特定 div 中）
        # HyperKitty 的结构可能变化，需要根据实际情况调整
        
        # 提取 diff 内容
        diff_match = re.search(r'(diff --git.*?-- 2\.\d+\.\d+)', msg_html, re.DOTALL)
        if diff_match:
            diff_content = diff_match.group(1)
            patch_file = f"{output_dir}/{i:04d}.patch"
            with open(patch_file, 'w') as f:
                f.write(diff_content)
            patches.append(patch_file)
            print(f"Extracted: {patch_file}")
    
    return patches

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <thread_url> <output_dir>")
        sys.exit(1)
    
    thread_url = sys.argv[1]
    output_dir = sys.argv[2]
    extract_patches_from_hyperkitty(thread_url, output_dir)
```

---

## 六、方法 4：从 lore.kernel.org 提取

### 6.1 使用 curl 下载

```bash
# 下载单个 patch
curl -o patch.mbox "https://lore.kernel.org/all/<message-id>/"

# 下载整个 series（通过 thread ID）
curl -o series.mbox "https://lore.kernel.org/all/<thread-id>/T.mbox"
```

### 6.2 使用 b4 下载（推荐）

```bash
b4 am -o ./patches/ "<message-id>"
```

---

## 七、方法 5：从邮件原文提取

### 7.1 保存邮件为 .eml

1. 在邮件客户端中导出邮件为 .eml 文件
2. 或使用 "显示原始邮件" → 复制全部内容 → 保存为 .eml

### 7.2 提取 patch

```bash
# 使用 git apply 检查
git apply --check patch.eml

# 使用 git am 应用
git am patch.eml

# 使用 b4 处理
b4 am -m patch.eml
```

### 7.3 手动提取 diff

如果邮件格式不标准，可以手动提取：

1. 找到 `diff --git` 开始的部分
2. 找到 `-- ` 或 `2.x.x` 结束的部分
3. 复制这部分内容保存为 .patch 文件

---

## 八、构造 mbox 文件

如果需要手动构造 mbox 文件：

### 8.1 mbox 格式

```
From sender@example.com Thu Sep  4 13:53:38 2026
From: Sender Name <sender@example.com>
Date: Thu, 04 Sep 2026 13:53:38 +0800
Subject: [PATCH 1/8] Patch title
Message-ID: <message-id@example.com>
To: list@example.org
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8

Patch description here.

Signed-off-by: Author <author@example.com>
---
 file.c | 10 ++++++++++
 1 file changed, 10 insertions(+)

diff --git a/file.c b/file.c
index 1234567..abcdefg 100644
--- a/file.c
+++ b/file.c
@@ -1,0 +1,10 @@
+added line 1
+added line 2
...
-- 
2.33.0

```

### 8.2 使用 git mailsplit 分割 mbox

```bash
# 分割 mbox 为单个 patch
mkdir patches
git mailsplit -o patches/ series.mbox

# 应用单个 patch
git am patches/0001
```

---

## 九、应用 patch

### 9.1 使用 git am

```bash
# 应用单个 patch
git am patch.mbox

# 应用多个 patch
git am patch1.mbox patch2.mbox

# 应用整个 series
git am *.patch

# 三方合并（遇到冲突时）
git am -3 patch.mbox

# 交互式应用
git am -i patch.mbox
```

### 9.2 使用 git apply

```bash
# 检查 patch 是否能应用
git apply --check patch.patch

# 应用 patch（不创建 commit）
git apply patch.patch

# 显示将要应用的变更
git apply --stat patch.patch
```

### 9.3 冲突处理

```bash
# 如果 git am 失败
git am --abort  # 取消
git am --skip   # 跳过当前 patch
git am --resolved  # 解决冲突后继续

# 使用 git apply 手动应用
git apply --reject patch.patch  # 生成 .rej 文件
```

---

## 十、常见问题

### 10.1 b4 找不到 Message-ID

- 检查 Message-ID 是否正确
- 确认邮件列表是否被 b4 支持（默认只支持 lore.kernel.org）
- 尝试手动下载 mbox 后用 `b4 am -m local.mbox`

### 10.2 patch 应用失败

- 检查 base commit 是否匹配
- 使用 `git am -3` 尝试三方合并
- 手动检查冲突并解决

### 10.3 编码问题

- 确保邮件使用 UTF-8 编码
- 使用 `git am --utf8` 强制 UTF-8

### 10.4 行尾符问题

- Windows 行尾符 (CRLF) 可能导致问题
- 使用 `dos2unix` 转换
- 或 `git apply --whitespace=fix`

---

## 十一、实用脚本

### 11.1 批量下载 openEuler patch

```bash
#!/bin/bash
# download_openeuler_patches.sh
# 从 openEuler 邮件列表下载 patch series

THREAD_URL="$1"
OUTPUT_DIR="$2"

if [ -z "$THREAD_URL" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "Usage: $0 <thread_url> <output_dir>"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# 提取 Message-IDs
echo "Fetching thread page..."
HTML=$(curl -s "$THREAD_URL")

# 提取所有 In-Reply-To
MSG_IDS=$(echo "$HTML" | grep -oP 'In-Reply-To=<\K[^>]+' | sort -u)

if [ -z "$MSG_IDS" ]; then
    echo "No Message-IDs found. Trying alternative method..."
    # 尝试从页面提取 message hash
    MSG_HASHES=$(echo "$HTML" | grep -oP '/message/\K[A-Z0-9]+' | sort -u)
    
    for hash in $MSG_HASHES; do
        MSG_URL="https://mailweb.openeuler.org/hyperkitty/list/virt@openeuler.org/message/$hash/"
        echo "Downloading $MSG_URL..."
        curl -s "$MSG_URL" -o "$OUTPUT_DIR/${hash}.html"
    done
else
    for msg_id in $MSG_IDS; do
        echo "Found Message-ID: $msg_id"
        # 尝试从 lore 下载
        curl -s "https://lore.kernel.org/all/$msg_id/" -o "$OUTPUT_DIR/$(echo $msg_id | tr '@' '_').mbox"
    done
fi

echo "Done. Files saved to $OUTPUT_DIR"
```

### 11.2 转换 HTML 为 patch

```bash
#!/bin/bash
# html_to_patch.sh
# 从 HyperKitty HTML 页面提取 patch

HTML_FILE="$1"
OUTPUT_FILE="$2"

if [ -z "$HTML_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "Usage: $0 <html_file> <output_file>"
    exit 1
fi

# 提取 diff 内容
python3 << EOF
import re
import sys

with open('$HTML_FILE', 'r') as f:
    html = f.read()

# 查找 diff 内容
diff_match = re.search(r'(diff --git.*?-- 2\.\d+\.\d+)', html, re.DOTALL)
if diff_match:
    diff_content = diff_match.group(1)
    # 清理 HTML 实体
    diff_content = diff_content.replace('&lt;', '<')
    diff_content = diff_content.replace('&gt;', '>')
    diff_content = diff_content.replace('&amp;', '&')
    diff_content = diff_content.replace('&quot;', '"')
    
    with open('$OUTPUT_FILE', 'w') as f:
        f.write(diff_content)
    print(f"Extracted patch to $OUTPUT_FILE")
else:
    print("No diff found in HTML")
    sys.exit(1)
EOF
```

---

## 十二、参考链接

- [b4 工具文档](https://b4.docs.kernel.org/)
- [Linux 内核提交规范](https://www.kernel.org/doc/html/latest/process/submitting-patches.html)
- [lore.kernel.org](https://lore.kernel.org/)
- [openEuler 邮件列表](https://mailweb.openeuler.org/)
- [HyperKitty 文档](https://hyperkitty.readthedocs.io/)

---

## 十三、快速参考卡片

```
┌─────────────────────────────────────────────────────────────┐
│                    Patch 下载快速参考                        │
├─────────────────────────────────────────────────────────────┤
│ 知道 Message-ID？                                           │
│   → b4 am -o ./patches/ "<message-id>"                     │
│                                                             │
│ 有 lore.kernel.org 链接？                                   │
│   → curl -o patch.mbox "<url>"                             │
│                                                             │
│ 有 openEuler thread 链接？                                  │
│   → 提取 Message-ID → b4 或手动下载                        │
│                                                             │
│ 只有邮件内容？                                              │
│   → 保存为 .eml → git am .eml                              │
│                                                             │
│ 应用 patch：                                                │
│   → git am patch.mbox                                      │
│   → git am -3 patch.mbox  # 三方合并                       │
│                                                             │
│ 冲突处理：                                                  │
│   → git am --abort                                         │
│   → git apply --reject patch.patch                         │
└─────────────────────────────────────────────────────────────┘
```
