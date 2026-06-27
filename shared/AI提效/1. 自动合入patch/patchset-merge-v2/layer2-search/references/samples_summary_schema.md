# samples_summary.json Schema

Layer 2 步骤 3a 抽样检测产出，Layer 2 内部消费（步骤 3b AI 分析 + 步骤 4 Subagent 搜索）。当前 schema_version: `1.0`。

## 完整 Schema

```json
{
  "schema_version": "1.0",
  "patches": [
    {
      "task_id": "0001",
      "files": ["arch/arm64/kvm/hdbss.c", "include/linux/kvm_host.h"],
      "symbol_samples": ["static int hdbss_init", "#define HDBSS_ENABLE"],
      "keyword_samples": ["HDBSS_BR_EL2 enable", "hdbss->flags"],
      "representative_samples": ["static int hdbss_init...", "#include <linux/..."],
      "total_add_lines": 150,
      "keywords": ["HDBSS", "FEAT_HDBSS", "DBM"]
    }
  ],
  "total_patches": 5,
  "scan_mode": "sampling"
}
```

## 字段说明

| 字段 | 说明 |
|------|------|
| `patches[].task_id` | patch 编号，从文件名提取 |
| `patches[].files` | 涉改文件列表 |
| `patches[].symbol_samples` | 符号样本（函数定义、宏定义、结构体定义） |
| `patches[].keyword_samples` | 关键词样本（大写关键词） |
| `patches[].representative_samples` | 代表性代码样本（前几行新增代码） |
| `patches[].total_add_lines` | 该 patch 新增行数 |
| `patches[].keywords` | 提取的关键词列表，供 step 4 Subagent 扩展搜索 |
| `total_patches` | patch 总数 |
| `scan_mode` | 固定为 `"sampling"` |
