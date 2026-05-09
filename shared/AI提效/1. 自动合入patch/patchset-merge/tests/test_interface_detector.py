"""Interface Detector 测试"""
import pytest
from pathlib import Path
from patchset_merge.interface_detector import (
    is_interface_file,
    extract_function_signatures,
    InterfaceChange,
)


class TestIsInterfaceFile:
    def test_c_h_files_are_interface(self):
        assert is_interface_file("foo.h") is True
        assert is_interface_file("foo.c") is True
        assert is_interface_file("bar.cpp") is True

    def test_py_files_are_interface(self):
        assert is_interface_file("foo.py") is True

    def test_txt_files_are_not_interface(self):
        assert is_interface_file("README.txt") is False
        assert is_interface_file("data.json") is False


class TestExtractFunctionSignatures:
    def test_extract_c_function(self):
        content = "int process_data(char* input, int len);"
        sigs = extract_function_signatures(content)
        assert "process_data" in sigs
        assert "int process_data(char* input, int len)" == sigs["process_data"]

    def test_extract_multiple_c_functions(self):
        content = """
        int init(void);
        int process_data(char* input, int len);
        void cleanup(void);
        """
        sigs = extract_function_signatures(content)
        assert "init" in sigs
        assert "process_data" in sigs
        assert "cleanup" in sigs

    def test_extract_python_function(self):
        content = """
def process_data(input_str, length):
    pass
"""
        sigs = extract_function_signatures(content)
        assert "process_data" in sigs
        assert "def process_data(input_str, length):" == sigs["process_data"]
