# 用户态页表属性分析演示

## 概述

本演示展示如何获取和解析用户态进程的页表属性，包括：

1. **软件层页表属性**：使用 `page-types` 工具解析 `/proc/<pid>/pagemap`
2. **硬件层 ARM PTE 属性**：通过 PFN 在内核页表中反查
3. **工具链**：
   - 编译 `page-types` (内核工具)
   - 编译 `show_addr.c` (测试程序)
   - 脚本脚本解析地址和页表

## 文件说明

- `show_addr.c`: 简单的 C 测试程序，输出变量地址
- `demo.sh`: 完整的测试脚本，演示页表属性获取流程
- `SUMMARY.md`: 输出结果和解释说明

## 快速开始

```bash
cd /mnt/kernel/user_space_page_table_demo
sh demo.sh
```

## 内核模块编译

如果遇到 `No such file or directory` 错误，请参考 `PTE_QUERY_README.md` 中的「常见问题」章节。

基本步骤：

1. 安装内核开发包：
```bash
sudo yum install kernel-devel
```

2. 编译模块：
```bash
make
```
