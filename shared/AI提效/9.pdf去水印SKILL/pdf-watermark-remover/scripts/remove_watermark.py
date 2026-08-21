#!/usr/bin/env python3
"""
PDF 水印去除工具

通过分析 PDF 的 OCG（Optional Content Group，可选内容组）图层结构，
识别并关闭水印图层，实现水印去除。

用法:
    python remove_watermark.py <输入路径> [输出路径]

    输入路径: PDF 文件路径，或包含 PDF 文件的目录
    输出路径: （可选）输出文件或目录路径，默认为输入文件同目录下添加 _无水印 后缀
"""

import sys
import os
import json
import argparse
import re


def check_pymupdf():
    """检查 PyMuPDF 是否已安装，未安装则尝试自动安装"""
    try:
        import fitz
        return True
    except ImportError:
        print("[INFO] PyMuPDF 未安装，正在自动安装...")
        import subprocess
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "PyMuPDF", "-q"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            import fitz  # noqa: F401
            print("[INFO] PyMuPDF 安装成功")
            return True
        except Exception as e:
            print(f"[ERROR] PyMuPDF 安装失败: {e}")
            print("请手动执行: pip install PyMuPDF")
            return False


def find_watermark_keywords():
    """
    返回水印关键词配置。

    分为两类:
    - strict_patterns: 精确匹配模式，关键词必须占文本主体（>=50%）才算命中，
                       避免 "内部" 匹配到 "DDR内部存储结构图" 等正文内容
    - broad_patterns:  模糊匹配模式，关键词作为子串出现即命中，
                       适用于水印特征非常明显的长文本

    返回:
        tuple: (strict_patterns, broad_patterns)
    """
    strict_patterns = [
        "内部", "机密", "仅供", "版权", "微信", "公众号",
        "Confidential", "Internal", "Draft", "DRAFT", "Sample",
    ]
    broad_patterns = [
        "保密文件", "保密资料", "保密级别", "保密",
        "水印",
        "微信公众号", "奔跑吧",
        "Watermark", "WATERMARK",
    ]
    return strict_patterns, broad_patterns


def is_watermark_text(txt, strict_patterns, broad_patterns):
    """
    判断文本是否为水印文本。

    - broad_patterns: 子串命中即判定为水印（长且特征明显的短语）
    - strict_patterns: 使用滑尺阈值检查关键词占比，
      避免 "内部" 匹配到 "DDR内部存储结构图" 等正文内容

    滑尺规则：文本越长，关键词需要占的比例越高
      - <=6 字符:  >=30%  （如 "内部文件" 4字, "内部" 占50%）
      - <=12 字符: >=50%  （如 "内部参考资料" 6字, "内部" 占33% -> 不匹配）
      - >12 字符:  >=70%  （如很长的正文句子, 基本不匹配）

    返回:
        bool: 是否为水印文本
    """
    txt_stripped = txt.strip()
    if not txt_stripped:
        return False

    # 模糊匹配：特征明显的长短语，子串命中即可
    for kw in broad_patterns:
        if kw in txt_stripped:
            return True

    # 精确匹配：短关键词，使用滑尺阈值
    txt_len = len(txt_stripped)
    for kw in strict_patterns:
        if kw in txt_stripped:
            kw_len = len(kw)
            ratio = kw_len / txt_len

            if txt_len <= 6:
                threshold = 0.3
            elif txt_len <= 12:
                threshold = 0.5
            else:
                threshold = 0.7

            if ratio >= threshold:
                return True

    return False


def analyze_pdf_watermarks(doc):
    """
    分析 PDF 文档中的水印信息。

    返回:
        dict: {
            "has_ocg": bool,
            "ocg_layers": list,
            "watermark_ocgs": list,
            "watermark_texts": list,
            "watermark_pages": list,
        }
    """
    import fitz

    result = {
        "has_ocg": False,
        "ocg_layers": [],
        "watermark_ocgs": [],
        "watermark_texts": [],
        "watermark_pages": [],
    }

    ocgs = doc.get_ocgs()
    if ocgs:
        result["has_ocg"] = True
        for xref, info in ocgs.items():
            layer_info = {
                "xref": xref,
                "name": info["name"],
                "on": info["on"],
            }
            result["ocg_layers"].append(layer_info)

    strict_patterns, broad_patterns = find_watermark_keywords()
    watermark_texts_set = set()

    for pg_idx in range(doc.page_count):
        page = doc[pg_idx]
        text_dict = page.get_text("dict")
        page_has_watermark = False

        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if is_watermark_text(txt, strict_patterns, broad_patterns):
                        watermark_texts_set.add(txt)
                        page_has_watermark = True

        if page_has_watermark:
            result["watermark_pages"].append(pg_idx + 1)

    result["watermark_texts"] = sorted(list(watermark_texts_set))

    watermark_name_patterns = [
        r"(?i)watermark",
        r"(?i)水印",
        r"(?i)stamp",
        r"(?i)confidential",
        r"(?i)保密",
    ]

    for layer in result["ocg_layers"]:
        name = layer["name"]
        for pattern in watermark_name_patterns:
            if re.search(pattern, name):
                result["watermark_ocgs"].append(layer["xref"])
                break

    return result


def remove_watermark_from_pdf(doc, watermark_xrefs, catalog_xref):
    """
    从 PDF 中移除水印。
    通过修改 Watermark OCG 对象的 Usage 状态和 Catalog 的 OCProperties 实现。

    返回:
        bool: 是否成功移除
    """
    import fitz

    if not watermark_xrefs:
        return False

    for xref in watermark_xrefs:
        try:
            obj_str = doc.xref_object(xref)
            new_obj = re.sub(
                r'/ViewState\s+/\w+', '/ViewState /OFF', obj_str
            )
            new_obj = re.sub(
                r'/PrintState\s+/\w+', '/PrintState /OFF', new_obj
            )
            new_obj = re.sub(
                r'/ExportState\s+/\w+', '/ExportState /OFF', new_obj
            )
            doc.update_object(xref, new_obj)
        except Exception as e:
            print(f"[WARN] 修改 OCG xref={xref} 失败: {e}")

    try:
        catalog_obj = doc.xref_object(catalog_xref)

        for xref in watermark_xrefs:
            ref_str = f"{xref} 0 R"

            on_pattern = r'(/ON\s*\[)([^\]]*?)(' + re.escape(ref_str) + r'\s*)'
            catalog_obj = re.sub(on_pattern, r'\1\2', catalog_obj)

            if '/OFF' not in catalog_obj:
                catalog_obj = catalog_obj.replace(
                    '/ON [',
                    f'/OFF [ {ref_str} ]\n      /ON ['
                )
            else:
                off_pattern = r'(/OFF\s*\[)'
                catalog_obj = re.sub(off_pattern, f'\\1 {ref_str}', catalog_obj)

        doc.update_object(catalog_xref, catalog_obj)
    except Exception as e:
        print(f"[WARN] 修改 Catalog 失败: {e}")

    return True


def remove_watermark_text_redaction(doc, strict_patterns=None, broad_patterns=None):
    """
    备选方案：通过文本涂黑（redaction）方式移除水印文本。
    适用于水印不是通过 OCG 图层实现的情况。

    返回:
        int: 被移除的水印文本数量
    """
    if strict_patterns is None or broad_patterns is None:
        strict_patterns, broad_patterns = find_watermark_keywords()

    removed_count = 0

    for pg_idx in range(doc.page_count):
        page = doc[pg_idx]
        text_dict = page.get_text("dict")

        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if is_watermark_text(txt, strict_patterns, broad_patterns):
                        bbox = span.get("bbox")
                        if bbox:
                            from fitz import Rect
                            rect = Rect(bbox)
                            rect.x0 -= 2
                            rect.y0 -= 2
                            rect.x1 += 2
                            rect.y1 += 2
                            page.add_redact_annot(rect)
                            removed_count += 1

        if removed_count > 0:
            page.apply_redactions()

    return removed_count


def process_single_pdf(input_path, output_path=None, use_redaction_fallback=False):
    """
    处理单个 PDF 文件的水印去除。

    返回:
        dict: 处理结果
    """
    import fitz

    result = {
        "input_file": input_path,
        "output_file": None,
        "status": "unknown",
        "message": "",
        "page_count": 0,
        "watermark_texts_found": [],
        "watermark_pages": [],
        "ocg_layers": [],
        "watermark_ocgs_removed": [],
        "method": "none",
        "verification": {
            "watermark_remaining": False,
            "remaining_texts": [],
        },
    }

    if not os.path.isfile(input_path):
        result["status"] = "error"
        result["message"] = f"文件不存在: {input_path}"
        return result

    if not input_path.lower().endswith(".pdf"):
        result["status"] = "error"
        result["message"] = f"不是 PDF 文件: {input_path}"
        return result

    try:
        doc = fitz.open(input_path)
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"无法打开 PDF: {e}"
        return result

    result["page_count"] = doc.page_count

    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_无水印{ext}"
    result["output_file"] = output_path

    analysis = analyze_pdf_watermarks(doc)
    result["ocg_layers"] = analysis["ocg_layers"]
    result["watermark_texts_found"] = analysis["watermark_texts"]
    result["watermark_pages"] = analysis["watermark_pages"]

    if not analysis["watermark_texts"]:
        result["status"] = "no_watermark"
        result["message"] = "未检测到水印文本"
        result["verification"]["watermark_remaining"] = False
        doc.close()
        import shutil
        shutil.copy2(input_path, output_path)
        return result

    removed = False
    if analysis["watermark_ocgs"]:
        catalog_xref = doc.pdf_catalog()
        removed = remove_watermark_from_pdf(doc, analysis["watermark_ocgs"], catalog_xref)
        if removed:
            result["method"] = "ocg_layer"
            result["watermark_ocgs_removed"] = analysis["watermark_ocgs"]
            result["message"] = f"通过 OCG 图层关闭移除 {len(analysis['watermark_ocgs'])} 个水印图层"

    if not removed and use_redaction_fallback:
        strict_p, broad_p = find_watermark_keywords()
        redact_count = remove_watermark_text_redaction(doc, strict_p, broad_p)
        if redact_count > 0:
            removed = True
            result["method"] = "text_redaction"
            result["message"] = f"通过文本涂黑移除 {redact_count} 处水印文本"

    if not removed:
        result["status"] = "no_ocg_watermark"
        result["message"] = (
            f"检测到 {len(analysis['watermark_texts'])} 处水印文本，"
            f"但未找到水印 OCG 图层。"
            f"可使用 --redaction 参数尝试文本涂黑方式移除。"
        )
        doc.close()
        import shutil
        shutil.copy2(input_path, output_path)
        return result

    try:
        doc.save(output_path, garbage=4, deflate=True)
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"保存失败: {e}"
        doc.close()
        return result

    # 验证
    try:
        doc2 = fitz.open(output_path)
        strict_p, broad_p = find_watermark_keywords()
        remaining_texts = []

        for pg_idx in range(doc2.page_count):
            page = doc2[pg_idx]
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        txt = span["text"].strip()
                        if is_watermark_text(txt, strict_p, broad_p):
                            remaining_texts.append(txt)

        doc2.close()

        if remaining_texts:
            result["verification"]["watermark_remaining"] = True
            result["verification"]["remaining_texts"] = sorted(list(set(remaining_texts)))
            result["status"] = "partial"
            result["message"] += f"（警告：验证发现 {len(set(remaining_texts))} 处水印文本可能残留）"
        else:
            result["verification"]["watermark_remaining"] = False
            result["status"] = "success"
            result["message"] += "（验证通过：水印已完全移除）"
    except Exception as e:
        result["status"] = "success_unverified"
        result["message"] += f"（验证失败: {e}）"

    doc.close()
    return result


def find_pdf_files(input_path):
    """
    根据输入路径查找 PDF 文件。

    支持:
        - 单个 PDF 文件路径
        - 目录路径（递归查找所有 PDF）
        - 逗号分隔的多个路径

    返回:
        list: PDF 文件路径列表
    """
    pdf_files = []

    paths = [p.strip() for p in input_path.split(",") if p.strip()]

    for path in paths:
        path = os.path.expanduser(path)
        if os.path.isfile(path) and path.lower().endswith(".pdf"):
            pdf_files.append(os.path.abspath(path))
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for f in sorted(files):
                    if f.lower().endswith(".pdf"):
                        pdf_files.append(os.path.abspath(os.path.join(root, f)))
        else:
            print(f"[WARN] 跳过无效路径: {path}")

    return pdf_files


def main():
    parser = argparse.ArgumentParser(
        description="PDF 水印去除工具 - 通过 OCG 图层分析移除 PDF 水印"
    )
    parser.add_argument(
        "input",
        help="输入 PDF 文件路径、目录路径，或多个路径用逗号分隔",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出文件或目录路径（可选，默认在输入文件名后添加 _无水印 后缀）",
    )
    parser.add_argument(
        "--redaction",
        action="store_true",
        help="当 OCG 方式无法移除水印时，启用文本涂黑备选方案",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )

    args = parser.parse_args()

    if not check_pymupdf():
        sys.exit(1)

    pdf_files = find_pdf_files(args.input)

    if not pdf_files:
        print("[ERROR] 未找到任何 PDF 文件")
        sys.exit(1)

    print(f"[INFO] 找到 {len(pdf_files)} 个 PDF 文件待处理")
    print()

    results = []
    for i, pdf_path in enumerate(pdf_files):
        print(f"[{i+1}/{len(pdf_files)}] 处理: {os.path.basename(pdf_path)}")

        output_path = None
        if args.output and len(pdf_files) == 1:
            output_path = args.output
        elif args.output and os.path.isdir(args.output):
            base = os.path.basename(pdf_path)
            name, ext = os.path.splitext(base)
            output_path = os.path.join(args.output, f"{name}_无水印{ext}")

        result = process_single_pdf(
            pdf_path,
            output_path=output_path,
            use_redaction_fallback=args.redaction,
        )
        results.append(result)

        status_icons = {
            "success": "✅",
            "success_unverified": "⚠️",
            "partial": "⚠️",
            "no_watermark": "ℹ️",
            "no_ocg_watermark": "⚠️",
            "error": "❌",
            "unknown": "❓",
        }
        icon = status_icons.get(result["status"], "❓")
        print(f"  状态: {icon} {result['status']}")
        print(f"  方法: {result['method']}")
        print(f"  信息: {result['message']}")
        if result["output_file"]:
            print(f"  输出: {result['output_file']}")
        print()

    if args.json:
        json_output = {
            "total_files": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
            "partial_count": sum(1 for r in results if r["status"] == "partial"),
            "no_watermark_count": sum(1 for r in results if r["status"] == "no_watermark"),
            "error_count": sum(1 for r in results if r["status"] == "error"),
            "results": results,
        }
        print("===JSON_START===")
        print(json.dumps(json_output, ensure_ascii=False, indent=2))
        print("===JSON_END===")

    success_count = sum(1 for r in results if r["status"] in ("success", "no_watermark"))
    print(f"[汇总] 共 {len(results)} 个文件，成功 {success_count} 个")

    has_errors = any(r["status"] == "error" for r in results)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
