"""merge_tasks.json 和 analysis_cache.json schema 校验"""

import json
import pytest


# ── merge_tasks.json 校验 ──

REQUIRED_TASK_FIELDS = [
    "seq", "task_id", "status", "patch_file", "subject", "author",
    "files_changed", "功能分类", "introduced_symbols", "referenced_symbols",
    "action", "skip_reason", "pre_revert", "depends_on",
    "risk_level", "review_required", "blame_hits", "duplicate_info",
    "conflicts_predicted", "special_notes", "build_checkpoint",
    "pr_mapping", "execution_log",
]

REQUIRED_TOP_FIELDS = [
    "patchset_info", "global_revert_order", "deps_order", "merge_order",
]

REQUIRED_PR_MAPPING_FIELDS = ["upstream_deps", "bugfix_deps", "revert_candidates"]

REQUIRED_PR_ENTRY_FIELDS = ["pr_id", "commits"]

REQUIRED_REVERT_ORDER_FIELDS = [
    "pr_id", "pr_url", "subject", "commits", "commit_count",
    "revert_strategy", "revert_cmd", "urgency", "related_patches",
]


def _load_sample():
    return json.loads("""
{
  "patchset_info": {
    "source": "HDBSS v3 from lore.kernel.org",
    "download_method": "b4",
    "total_patches": 5,
    "target_kernel": "/root/code/openeuler/kernel",
    "target_branch": "patch-hdbss-v3",
    "build_target": "make ARCH=arm64 Image"
  },
  "global_revert_order": [
    {
      "pr_id": "PR #123",
      "pr_url": "https://github.com/torvalds/linux/pull/123",
      "subject": "HDBSS 功能系列",
      "commits": ["abc123", "def456"],
      "commit_count": 2,
      "revert_strategy": "整体 revert PR #123",
      "revert_cmd": "git revert --ancestry-path abc123^..def456",
      "urgency": "必须",
      "related_patches": ["0001", "0003"]
    }
  ],
  "deps_order": [
    {
      "seq": 1,
      "task_id": "dep-001",
      "source_pr": "PR #456",
      "status": "pending",
      "patch_file": "/tmp/patches/deps/0001-dep.patch",
      "subject": "stage2 页表重构",
      "author": "upstream author",
      "files_changed": ["file1.c"],
      "功能分类": "core",
      "introduced_symbols": ["stage2_set_pte"],
      "referenced_symbols": ["kvm_pte_to_phys"],
      "action": "apply",
      "skip_reason": null,
      "pre_revert": [],
      "depends_on": [],
      "risk_level": "低",
      "review_required": "低",
      "blame_hits": [],
      "duplicate_info": {"level": "无重复", "detail": ""},
      "conflicts_predicted": [],
      "special_notes": "上游依赖",
      "build_checkpoint": false,
      "pr_mapping": {
        "upstream_deps": [],
        "bugfix_deps": [],
        "revert_candidates": []
      },
      "execution_log": []
    }
  ],
  "merge_order": [
    {
      "seq": 1,
      "task_id": "0001",
      "status": "pending",
      "patch_file": "/tmp/patches/0001.patch",
      "subject": "arm64/sysreg: Add HDBSS related register information",
      "author": "eillon <yezhenyu2@huawei.com>",
      "files_changed": ["arch/arm64/include/asm/esr.h", "arch/arm64/tools/sysreg"],
      "功能分类": "infra",
      "introduced_symbols": ["HDBSS_ENABLE_BIT", "ESR_ELx_HDBSS_SHIFT"],
      "referenced_symbols": [],
      "action": "apply",
      "skip_reason": null,
      "pre_revert": [],
      "depends_on": [],
      "risk_level": "低",
      "review_required": "低",
      "blame_hits": [],
      "duplicate_info": {"level": "无重复", "detail": ""},
      "conflicts_predicted": [],
      "special_notes": "",
      "build_checkpoint": true,
      "pr_mapping": {
        "upstream_deps": [
          {
            "pr_id": "PR #456",
            "pr_url": "https://github.com/torvalds/linux/pull/456",
            "commits": ["dep-abc"],
            "cover_letter_msgid": "xxx@lore.kernel.org",
            "download_cmd": "b4 am xxx@lore.kernel.org",
            "reason": "缺失函数 stage2_try_set_pte"
          }
        ],
        "bugfix_deps": [
          {
            "pr_id": "独立 commit",
            "commits": ["fix-ghi789"],
            "reason": "修复空指针"
          }
        ],
        "revert_candidates": [
          {
            "pr_id": "PR #456",
            "commits": ["local-abc", "local-def"],
            "subject": "本地 HDBSS 实现",
            "revert_cmd": "git revert --ancestry-path local-abc^..local-def",
            "urgency": "必须"
          }
        ]
      },
      "execution_log": []
    }
  ]
}
""")


# ── 顶层必填字段 ──

@pytest.mark.parametrize("field", REQUIRED_TOP_FIELDS)
def test_top_level_required_fields_exist(field):
    data = _load_sample()
    assert field in data, f"缺少顶层字段: {field}"


def test_deps_order_is_list():
    data = _load_sample()
    assert isinstance(data["deps_order"], list)


def test_merge_order_is_list():
    data = _load_sample()
    assert isinstance(data["merge_order"], list)


def test_global_revert_order_is_list():
    data = _load_sample()
    assert isinstance(data["global_revert_order"], list)


# ── global_revert_order 条目校验 ──

@pytest.mark.parametrize("field", REQUIRED_REVERT_ORDER_FIELDS)
def test_revert_order_entry_has_required_fields(field):
    data = _load_sample()
    for entry in data["global_revert_order"]:
        assert field in entry, f"global_revert_order 条目缺少字段: {field}"


def test_revert_order_entry_commits_is_list():
    data = _load_sample()
    for entry in data["global_revert_order"]:
        assert isinstance(entry["commits"], list)
        assert len(entry["commits"]) > 0
        assert entry["commit_count"] == len(entry["commits"])


def test_revert_order_entry_has_revert_cmd():
    data = _load_sample()
    for entry in data["global_revert_order"]:
        assert "git revert" in entry["revert_cmd"]


def test_revert_order_entry_urgency_valid():
    data = _load_sample()
    valid = {"必须", "建议", "无须"}
    for entry in data["global_revert_order"]:
        assert entry["urgency"] in valid, f"urgency 非法值: {entry['urgency']}"


# ── deps_order 条目校验 ──

@pytest.mark.parametrize("field", REQUIRED_TASK_FIELDS)
def test_deps_order_task_has_required_fields(field):
    data = _load_sample()
    for task in data["deps_order"]:
        assert field in task, f"deps_order task 缺少字段: {field}"


def test_deps_order_task_id_prefix():
    data = _load_sample()
    for task in data["deps_order"]:
        assert task["task_id"].startswith("dep-"), \
            f"deps_order task_id 应以 dep- 开头, 实际: {task['task_id']}"


def test_deps_order_has_source_pr():
    data = _load_sample()
    for task in data["deps_order"]:
        assert "source_pr" in task, "deps_order task 缺少 source_pr 字段"


# ── merge_order 条目校验 ──

@pytest.mark.parametrize("field", REQUIRED_TASK_FIELDS)
def test_merge_order_task_has_required_fields(field):
    data = _load_sample()
    for task in data["merge_order"]:
        assert field in task, f"merge_order task 缺少字段: {field}"


# ── pr_mapping 校验 ──

@pytest.mark.parametrize("section", REQUIRED_PR_MAPPING_FIELDS)
def test_pr_mapping_has_required_sections(section):
    data = _load_sample()
    for task in data["merge_order"]:
        pm = task["pr_mapping"]
        assert section in pm, f"pr_mapping 缺少 section: {section}"
        assert isinstance(pm[section], list)


@pytest.mark.parametrize("section", REQUIRED_PR_MAPPING_FIELDS)
def test_deps_order_pr_mapping_has_required_sections(section):
    data = _load_sample()
    for task in data["deps_order"]:
        pm = task["pr_mapping"]
        assert section in pm, f"deps_order pr_mapping 缺少 section: {section}"
        assert isinstance(pm[section], list)


@pytest.mark.parametrize("field", REQUIRED_PR_ENTRY_FIELDS)
def test_pr_mapping_entry_has_required_fields(field):
    data = _load_sample()
    for task in data["merge_order"]:
        for section_name, entries in task["pr_mapping"].items():
            for entry in entries:
                assert field in entry, \
                    f"pr_mapping.{section_name} entry 缺少字段: {field}"


def test_pr_mapping_entry_commits_is_list():
    data = _load_sample()
    for task in data["merge_order"]:
        for section_name, entries in task["pr_mapping"].items():
            for entry in entries:
                assert isinstance(entry["commits"], list)
                assert len(entry["commits"]) > 0


def test_pr_mapping_revert_candidates_have_urgency():
    data = _load_sample()
    valid = {"必须", "建议", "无须"}
    for task in data["merge_order"]:
        for entry in task["pr_mapping"]["revert_candidates"]:
            assert entry.get("urgency") in valid, \
                f"revert_candidates urgency 非法值: {entry.get('urgency')}"


def test_pr_mapping_upstream_deps_have_reason():
    data = _load_sample()
    for task in data["merge_order"]:
        for entry in task["pr_mapping"]["upstream_deps"]:
            assert "reason" in entry, "upstream_deps entry 缺少 reason"


def test_pr_mapping_independent_commit_ok():
    """独立 commit 的 pr_id 可以不是 PR 格式"""
    data = _load_sample()
    for task in data["merge_order"]:
        for entry in task["pr_mapping"]["bugfix_deps"]:
            if entry["pr_id"] == "独立 commit":
                assert "pr_url" not in entry or entry.get("pr_url") is None, \
                    "独立 commit 不应有 pr_url"


def test_pr_mapping_pr_has_url():
    """PR 类型条目应有 pr_url"""
    data = _load_sample()
    for task in data["merge_order"]:
        for entry in task["pr_mapping"]["upstream_deps"]:
            if entry["pr_id"].startswith("PR"):
                assert "pr_url" in entry, f"PR 类型 {entry['pr_id']} 缺少 pr_url"


# ── task_id 格式 ──

def test_merge_order_task_id_format():
    data = _load_sample()
    for task in data["merge_order"]:
        assert task["task_id"].isdigit() and len(task["task_id"]) == 4, \
            f"merge_order task_id 格式错误: {task['task_id']}"


def test_status_values():
    data = _load_sample()
    valid = {"pending", "in_progress", "done", "blocked", "skipped", "failed"}
    for task in data["deps_order"] + data["merge_order"]:
        assert task["status"] in valid, f"status 非法值: {task['status']}"


def test_action_values():
    data = _load_sample()
    valid = {"apply", "skip"}
    for task in data["deps_order"] + data["merge_order"]:
        assert task["action"] in valid, f"action 非法值: {task['action']}"


def test_risk_level_values():
    data = _load_sample()
    valid = {"高", "中", "低"}
    for task in data["deps_order"] + data["merge_order"]:
        assert task["risk_level"] in valid


def test_review_required_values():
    data = _load_sample()
    valid = {"高", "中", "低"}
    for task in data["deps_order"] + data["merge_order"]:
        assert task["review_required"] in valid


def test_skip_reason_required_when_action_skip():
    """当 action=skip 时 skip_reason 不能为 null"""
    data = _load_sample()
    task = data["merge_order"][0]
    task["action"] = "skip"
    task["skip_reason"] = "目标仓库已完全实现"
    assert task["skip_reason"] is not None, \
        "action=skip 时 skip_reason 必须非空"


def test_execution_log_initial_empty():
    data = _load_sample()
    for task in data["deps_order"] + data["merge_order"]:
        assert task["execution_log"] == [], \
            "初始 execution_log 应为空列表"
