"""Tests for download_patches.py - unified patchset download script."""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import download_patches as dp


class TestDetectSourceType(unittest.TestCase):
    def test_parse_message_id(self):
        result = dp.detect_source_type(
            "<20240501000000.12345-1-user@kernel.org>"
        )
        self.assertEqual(result, "message-id")

    def test_parse_url_lore(self):
        result = dp.detect_source_type(
            "https://lore.kernel.org/all/20240501000000.12345-1-user@kernel.org/"
        )
        self.assertEqual(result, "url")

    def test_parse_url_patchwork(self):
        result = dp.detect_source_type(
            "https://patchwork.kernel.org/project/linux-arm-kernel/patch/12345/"
        )
        self.assertEqual(result, "url")

    def test_parse_local_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = dp.detect_source_type(tmpdir)
            self.assertEqual(result, "local")

    def test_parse_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".patch") as tmpfile:
            result = dp.detect_source_type(tmpfile.name)
            self.assertEqual(result, "local")

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            dp.detect_source_type("not_a_valid_source")


class TestB4Download(unittest.TestCase):
    @patch("subprocess.run")
    def test_b4_command_constructed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK")
        result = dp.download_via_b4(
            "<20240501000000.12345-1-user@kernel.org>",
            "/tmp/test_patches",
        )
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("b4", cmd)
        self.assertIn("am", cmd)
        self.assertIn("<20240501000000.12345-1-user@kernel.org>", cmd)
        self.assertIn("/tmp/test_patches", cmd)

    @patch("subprocess.run")
    def test_b4_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("b4 not found")
        with self.assertRaises(RuntimeError) as ctx:
            dp.download_via_b4("<msg-id>", "/tmp/test_patches")
        self.assertIn("b4", str(ctx.exception).lower())


class TestProxyDetection(unittest.TestCase):
    def setUp(self):
        self.saved_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def test_proxy_from_env(self):
        os.environ["http_proxy"] = "http://proxy:8080"
        proxy = dp.detect_proxy()
        self.assertEqual(proxy, "http://proxy:8080")

    def test_https_proxy_preferred(self):
        os.environ["http_proxy"] = "http://proxy:8080"
        os.environ["https_proxy"] = "https://secure-proxy:8443"
        proxy = dp.detect_proxy()
        self.assertEqual(proxy, "https://secure-proxy:8443")

    def test_no_proxy(self):
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)
        proxy = dp.detect_proxy()
        self.assertIsNone(proxy)


class TestOutputNaming(unittest.TestCase):
    def test_pad_number(self):
        self.assertEqual(dp.pad_patch_number(1), "0001")
        self.assertEqual(dp.pad_patch_number(42), "0042")
        self.assertEqual(dp.pad_patch_number(9999), "9999")

    def test_sanitize_filename(self):
        result = dp.sanitize_filename(
            "KVM: arm64: Support 5-level paging in stage-2?"
        )
        self.assertNotIn(":", result)
        self.assertNotIn("?", result)
        self.assertNotIn(" ", result)
        self.assertEqual(result, "KVM-arm64-Support-5-level-paging-in-stage-2")

    def test_generate_output_name(self):
        result = dp.generate_output_name(1, "KVM: arm64: Fix mmu bug")
        self.assertEqual(result, "0001-KVM-arm64-Fix-mmu-bug.patch")


class TestMetadataGeneration(unittest.TestCase):
    def test_generate_metadata(self):
        patches = [{
            "id": "0001",
            "file": "/tmp/patches/0001-test.patch",
            "subject": "Test patch",
            "author": "test@kernel.org",
            "date": "2024-05-01",
            "upstream_commit": "abc123",
        }]
        metadata = dp.generate_metadata(
            source="<test-msg-id>",
            method="b4",
            total=1,
            target_kernel="/home/user/kernel",
            target_branch="main",
            build_target="make ARCH=arm64 Image",
            patches=patches,
        )
        self.assertEqual(metadata["source"], "<test-msg-id>")
        self.assertEqual(metadata["download_method"], "b4")
        self.assertEqual(metadata["total_patches"], 1)
        self.assertEqual(len(metadata["patches"]), 1)
        self.assertEqual(metadata["patches"][0]["id"], "0001")


class TestLocalCopy(unittest.TestCase):
    def test_copy_patch_files(self):
        with tempfile.TemporaryDirectory() as srcdir:
            with tempfile.TemporaryDirectory() as dstdir:
                src = os.path.join(srcdir, "some-patch.patch")
                with open(src, "w") as f:
                    f.write("dummy patch content\n")
                results = dp.copy_from_local(srcdir, dstdir)
                self.assertEqual(len(results), 1)
                dest = os.path.join(dstdir, os.path.basename(src))
                self.assertTrue(os.path.exists(dest))
