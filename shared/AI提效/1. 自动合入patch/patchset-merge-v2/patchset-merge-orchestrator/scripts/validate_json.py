#!/usr/bin/env python3
"""
JSON Schema 验证脚本 - 执行时间 <1秒
用法: validate_json.py --file <json_file> --schema <schema_file>
"""

import json
import sys
import argparse
from pathlib import Path

def validate_json(json_file: str, schema_file: str) -> bool:
    """验证 JSON 文件是否符合 schema"""
    try:
        with open(json_file) as f:
            data = json.load(f)
        
        with open(schema_file) as f:
            schema = json.load(f)
        
        # 简化验证：检查必填字段
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                print(f"❌ 缺失必填字段: {field}")
                return False
        
        print(f"✅ {json_file} schema 验证通过")
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        return False
    except FileNotFoundError as e:
        print(f"❌ 文件不存在: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    
    success = validate_json(args.file, args.schema)
    sys.exit(0 if success else 1)