# PDF 水印去除技能

本 skill 用于从 PDF 文件中移除水印。通过分析 PDF 的 OCG（Optional Content Group，可选内容组）图层结构，识别水印图层并将其关闭，实现无损水印去除。

## 适用场景

- 用户要求去除 PDF 文件中的水印
- 用户要求批量去除多个 PDF 文件中的水印
- 用户要求去除目录中所有 PDF 文件的水印

**触发词**：去水印、去除水印、移除水印、PDF水印、去掉水印、watermark、remove watermark

## 工作原理

1. **OCG 图层分析**：扫描 PDF 的 Optional Content Group 图层，识别名称中包含水印关键词的图层
2. **图层状态修改**：将水印图层的 `ViewState`、`PrintState`、`ExportState` 全部设为 `OFF`
3. **Catalog 属性更新**：修改 PDF Catalog 的 OCProperties，将水印图层从 `/ON` 移至 `/OFF`
4. **文本涂黑备选**（可选）：当水印不是通过 OCG 图层实现时，使用文本 redaction 方式直接覆盖水印文本
5. **结果验证**：重新打开输出文件，确认水印文本已不可见

## 输入

用户输入支持以下形式：

1. **单个 PDF 文件路径**：`/pdf-watermark-remover /path/to/file.pdf`
2. **多个 PDF 文件路径**（逗号分隔）：`/pdf-watermark-remover /path/to/a.pdf,/path/to/b.pdf`
3. **目录路径**（递归处理目录下所有 PDF）：`/pdf-watermark-remover /path/to/pdf_directory/`

### 可选参数

- `-o` / `--output`：指定输出路径
    - 单文件模式：指定输出文件的完整路径
    - 多文件/目录模式：指定输出目录路径
    - 不指定：默认在输入文件同目录下，文件名添加 `_无水印` 后缀
- `--redaction`：当 OCG 图层方式无法移除水印时，启用文本涂黑（redaction）备选方案
- `--json`：以 JSON 格式输出处理结果

## 输出

### 文件输出

- 默认：在输入文件同目录下生成 `<原文件名>_无水印.pdf`
- 指定 `-o`：输出到指定路径

### 处理报告

处理完成后输出汇总报告，包含：

| 字段 | 说明 |
|------|------|
| 输入文件 | 原始 PDF 文件路径 |
| 输出文件 | 处理后 PDF 文件路径 |
| 状态 | success / partial / no_watermark / error |
| 方法 | ocg_layer（OCG图层） / text_redaction（文本涂黑） |
| 页数 | PDF 总页数 |
| 水印文本 | 检测到的水印文本内容 |
| 水印页码 | 出现水印的页码列表 |
| 验证结果 | 水印是否已完全移除 |

## 执行流程

### 核心原则

- 每个 PDF 文件独立处理，逐个扫描分析
- 处理完成后必须验证输出文件的水印是否已成功移除
- 如果验证发现残留水印，状态标记为 `partial` 并给出警告

### 第 1 步：解析输入与环境检查

[CHECKPOINT: 开始]

1. 解析用户输入，获取 PDF 文件路径或目录路径
2. 解析可选参数（`-o`、`--redaction`、`--json`）
3. 确定输出路径策略（使用 `-o` 指定路径 或 默认 `_无水印` 后缀）
4. 检查 Python3 和 PyMuPDF 是否可用：
    - 执行 `python3 -c "import fitz; print(fitz.__version__)"` 检查
    - 如果 PyMuPDF 未安装，执行 `pip3 install PyMuPDF` 安装
    - 脚本内置了自动安装逻辑，通常无需手动处理

完成后输出 [CHECKPOINT: 环境检查完成]

### 第 2 步：执行水印去除

[CHECKPOINT: 执行水印去除]

使用脚本执行处理：

```bash
python3 scripts/remove_watermark.py "<输入路径>" [可选参数]
```

**参数说明**：

| 场景 | 命令示例 |
|------|----------|
| 单文件，默认输出 | `python3 scripts/remove_watermark.py "/path/to/file.pdf"` |
| 单文件，指定输出 | `python3 scripts/remove_watermark.py "/path/to/file.pdf" -o "/path/to/output.pdf"` |
| 多文件 | `python3 scripts/remove_watermark.py "/path/a.pdf,/path/b.pdf"` |
| 目录 | `python3 scripts/remove_watermark.py "/path/to/dir/"` |
| 启用涂黑备选 | `python3 scripts/remove_watermark.py "/path/to/file.pdf" --redaction` |
| JSON 输出 | `python3 scripts/remove_watermark.py "/path/to/file.pdf" --json` |

**注意**：
- 脚本路径为当前技能目录下的 `scripts/remove_watermark.py`，执行时需使用绝对路径
- 输入路径中的空格和中文不需要额外转义，但建议用双引号包裹

完成后输出 [CHECKPOINT: 水印去除完成]

### 第 3 步：结果汇总与报告

[CHECKPOINT: 结果汇总]

1. 解析脚本输出结果
2. 对每个文件输出处理状态：
    - ✅ `success`：水印已完全移除并通过验证
    - ⚠️ `partial`：部分水印移除，验证发现残留
    - ⚠️ `no_ocg_watermark`：检测到水印文本但未找到 OCG 水印图层
    - ℹ️ `no_watermark`：未检测到水印，无需处理
    - ❌ `error`：处理出错
3. 输出汇总表格

如果有 `partial` 或 `no_ocg_watermark` 状态的文件，建议用户：
- 使用 `--redaction` 参数重试（启用文本涂黑备选方案）
- 或手动检查残留水印

完成后输出 [CHECKPOINT: 结果汇总完成]

## 支持的 OCG 水印名称模式

脚本通过以下正则表达式匹配水印图层名称（不区分大小写）：

| 模式 | 匹配示例 |
|------|----------|
| `watermark` | Watermark, WATERMARK, watermark |
| `水印` | 水印, 公司水印 |
| `stamp` | Stamp, rubber_stamp |
| `confidential` | Confidential, CONFIDENTIAL |
| `保密` | 保密, 保密文件 |

## 支持的水印文本关键词

脚本通过**双层关键词匹配策略**识别水印文本，避免误匹配正文内容：

### 模糊匹配关键词（子串命中即判定为水印）

特征明显的长文本或短语，出现即视为水印：

- 中文：保密、保密文件、保密资料、保密级别、水印、微信公众号、奔跑吧
- 英文：Watermark, WATERMARK

### 精确匹配关键词（滑尺阈值匹配）

短关键词，需要占文本一定比例才算水印（避免误匹配正文）：

- 中文：内部、机密、仅供、版权、微信、公众号
- 英文：Confidential, Internal, Draft, DRAFT, Sample

**滑尺规则**（关键词长度 / 文本长度）：

| 文本长度 | 占比阈值 | 示例 |
|----------|----------|------|
| <= 6 字符 | >= 30% | "内部文件"（"内部"占 50%）-> 命中 |
| <= 12 字符 | >= 50% | "内部参考资料"（"内部"占 33%）-> 不命中 |
| > 12 字符 | >= 70% | 长正文句子 -> 基本不命中 |

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| PyMuPDF 未安装 | 自动安装或提示用户手动安装 |
| 文件不存在 | 标记为 error，跳过该文件 |
| 非 PDF 文件 | 标记为 error，跳过该文件 |
| PDF 加密且无法解密 | 标记为 error，提示用户先解密 |
| 检测到水印但无 OCG 图层 | 标记为 no_ocg_watermark，建议使用 `--redaction` |
| 保存失败 | 标记为 error，保留原文件不变 |
| 验证发现水印残留 | 标记为 partial，输出警告 |

## 文件结构

```
pdf-watermark-remover/
├── SKILL.md (本文件)
└── scripts/
    └── remove_watermark.py (水印去除核心脚本)
```

## 禁止行为

- 禁止修改原始 PDF 文件（始终输出到新文件）
- 禁止在未验证的情况下声称水印已成功移除
- 禁止凭猜测判断水印位置，必须基于 OCG 图层分析或文本关键词匹配
- 禁止跳过验证步骤
- 禁止在用户未指定 `--redaction` 时自动使用文本涂黑方式（这可能影响原始内容）

## 注意事项

1. 本技能依赖 PyMuPDF 库（`pip install PyMuPDF`），脚本内置自动安装逻辑
2. OCG 图层方式是首选方案，因为它是无损的，不影响原始内容
3. 文本涂黑（redaction）方式是备选方案，会用白色矩形覆盖水印文本区域，可能影响水印下方的内容
4. 对于非 OCG 实现的水印（如直接嵌入页面内容流的水印），OCG 方式无效，需要 `--redaction` 参数
5. 输出文件默认添加 `_无水印` 后缀，不会覆盖原文件
6. 加密的 PDF 需要先解密才能处理
