#!/usr/bin/env python3
"""Tests for calculate_build_checkpoints.py."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from calculate_build_checkpoints import (
    calculate_checkpoints,
    count_references,
    common_path_prefix,
)


class TestCommonPathPrefix(unittest.TestCase):
    def test_driver_path(self):
        self.assertEqual(common_path_prefix(['drivers/gpu/arm/mali_kbase_core.c']),
                         'drivers/gpu/arm')

    def test_shallow_path(self):
        self.assertEqual(common_path_prefix(['kernel/sched.c']),
                         'kernel')

    def test_empty(self):
        self.assertEqual(common_path_prefix([]), 'unknown')

    def test_deep_path(self):
        self.assertEqual(common_path_prefix(['arch/arm64/kernel/cpu_errata.c']),
                         'arch/arm64/kernel')


class TestCountReferences(unittest.TestCase):
    def test_no_introduced(self):
        self.assertEqual(count_references([], [{'referenced_symbols': ['a']}]), 0)

    def test_no_later_patches(self):
        self.assertEqual(count_references(['func_a'], []), 0)

    def test_one_match(self):
        later = [
            {'referenced_symbols': ['func_a']},
            {'referenced_symbols': ['func_b']},
        ]
        self.assertEqual(count_references(['func_a'], later), 1)

    def test_multiple_matches(self):
        later = [
            {'referenced_symbols': ['func_a', 'func_b']},
            {'referenced_symbols': ['func_a', 'func_c']},
            {'referenced_symbols': ['func_a']},
            {'referenced_symbols': ['func_d']},
        ]
        self.assertEqual(count_references(['func_a'], later), 3)

    def test_no_match(self):
        later = [
            {'referenced_symbols': ['func_b']},
        ]
        self.assertEqual(count_references(['func_a'], later), 0)

    def test_overlap(self):
        later = [
            {'referenced_symbols': ['func_a', 'func_c']},
        ]
        self.assertEqual(count_references(['func_a', 'func_b'], later), 1)


class TestCalculateCheckpoints(unittest.TestCase):
    def make_patch(self, seq, task_id, func_class='core',
                   introduced_syms=None, referenced_syms=None,
                   risk_level='低', conflicts=None, action='apply',
                   files_changed=None):
        return {
            'seq': seq,
            'task_id': task_id,
            '功能分类': func_class,
            'introduced_symbols': introduced_syms or [],
            'referenced_symbols': referenced_syms or [],
            'risk_level': risk_level,
            'conflicts_predicted': conflicts or [],
            'action': action,
            'files_changed': files_changed or ['kernel/sched.c'],
        }

    def test_rule1_infra(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', func_class='infra',
                                files_changed=['include/linux/kvm_host.h']),
                self.make_patch(2, '0002', referenced_syms=['func_a']),
                self.make_patch(3, '0003'),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        self.assertTrue(updated['merge_order'][0]['build_checkpoint'])
        self.assertFalse(updated['merge_order'][1]['build_checkpoint'])
        # 0003 is last → forced True, even though it's a normal patch
        self.assertTrue(updated['merge_order'][2]['build_checkpoint'])

    def test_rule2_high_dependency_count(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', introduced_syms=['func_a']),
                self.make_patch(2, '0002', func_class='bugfix',
                                referenced_syms=['func_a']),
                self.make_patch(3, '0003', func_class='driver',
                                referenced_syms=['func_a']),
                self.make_patch(4, '0004', func_class='net',
                                referenced_syms=['func_a', 'func_b']),
                self.make_patch(5, '0005', referenced_syms=['func_c']),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        # Patch 1 is referenced by 3 later patches (0002, 0003, 0004)
        self.assertTrue(updated['merge_order'][0]['build_checkpoint'])
        self.assertIn('≥3', results[0]['reason'])

    def test_rule3_risk_high(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001'),
                self.make_patch(2, '0002', risk_level='高'),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])
        self.assertTrue(updated['merge_order'][1]['build_checkpoint'])

    def test_rule3_conflicts(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', conflicts=['file.c:10:duplicate']),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        self.assertTrue(updated['merge_order'][0]['build_checkpoint'])

    def test_rule4_last_in_group(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', func_class='driver',
                                files_changed=['drivers/gpu/arm/a.c']),
                self.make_patch(2, '0002', func_class='driver',
                                files_changed=['drivers/gpu/arm/b.c']),
                self.make_patch(3, '0003', func_class='driver',
                                files_changed=['drivers/gpu/arm/c.c']),
                self.make_patch(4, '0004', func_class='core',
                                files_changed=['kernel/sched.c']),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)

        # 0003 should be checkpoint (last in driver/gpu/arm group)
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])  # 0001
        self.assertFalse(updated['merge_order'][1]['build_checkpoint'])  # 0002
        self.assertTrue(updated['merge_order'][2]['build_checkpoint'])   # 0003
        self.assertIn('功能模块最后', results[2]['reason'])

        # 0004 should be checkpoint (last patch overall + last in its group)
        self.assertTrue(updated['merge_order'][3]['build_checkpoint'])

    def test_rule5_last_patch_forced(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', func_class='bugfix'),
                self.make_patch(2, '0002', introduced_syms=['a']),
                self.make_patch(3, '0003', referenced_syms=['a']),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        # 0001 bugfix not last → False
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])
        # 0002 has 1 ref (<3) → False
        self.assertFalse(updated['merge_order'][1]['build_checkpoint'])
        # 0003 is last → forced True (even though it's a follow-up)
        self.assertTrue(updated['merge_order'][2]['build_checkpoint'])
        self.assertIn('最后一个 patch', results[2]['reason'])

    def test_rule6_skip_doc(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', func_class='doc'),
                self.make_patch(2, '0002', action='skip'),
                self.make_patch(3, '0003'),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])  # doc, not last
        self.assertFalse(updated['merge_order'][1]['build_checkpoint'])  # skip, not last
        self.assertTrue(updated['merge_order'][2]['build_checkpoint'])   # last (forced)

    def test_rule7_default_false(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001'),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        # 0001 is the only patch, so rule 5 kicks in (last patch)
        self.assertTrue(updated['merge_order'][0]['build_checkpoint'])

    def test_rule7_default_false_multi(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', introduced_syms=['a']),
                self.make_patch(2, '0002', referenced_syms=['a']),
                self.make_patch(3, '0003'),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        # 0001: ref_count=1 (<3), not infra, not high risk, not last in group
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])
        # 0002: 0 refs, not high risk, not last in group
        self.assertFalse(updated['merge_order'][1]['build_checkpoint'])
        # 0003: last patch (forced)
        self.assertTrue(updated['merge_order'][2]['build_checkpoint'])

    def test_deps_order_included(self):
        tasks = {
            'merge_order': [
                self.make_patch(3, '0001'),
                self.make_patch(5, '0002'),  # last overall
            ],
            'deps_order': [
                self.make_patch(1, 'dep-001', func_class='infra',
                                files_changed=['include/linux/kvm.h']),
                self.make_patch(2, 'dep-002', introduced_syms=['func_x']),
                self.make_patch(4, 'dep-003', referenced_syms=['func_x']),
            ],
        }
        updated, results = calculate_checkpoints(tasks)
        # dep-001: infra → true
        self.assertTrue(updated['deps_order'][0]['build_checkpoint'])
        # dep-002: ref from dep-003 (1) → false
        self.assertFalse(updated['deps_order'][1]['build_checkpoint'])
        # 0001: no refs → false
        self.assertFalse(updated['merge_order'][0]['build_checkpoint'])
        # dep-003: refs func_x but no later patch, 0 refs → false
        self.assertFalse(updated['deps_order'][2]['build_checkpoint'])
        # 0002: last overall → true
        self.assertTrue(updated['merge_order'][1]['build_checkpoint'])

    def test_output_format(self):
        tasks = {
            'merge_order': [
                self.make_patch(1, '0001', func_class='infra',
                                files_changed=['include/linux/kvm.h']),
                self.make_patch(2, '0002', introduced_syms=['a', 'b']),
                self.make_patch(3, '0003', referenced_syms=['a']),
                self.make_patch(4, '0004', referenced_syms=['a']),
                self.make_patch(5, '0005', referenced_syms=['a']),
            ],
            'deps_order': [],
        }
        updated, results = calculate_checkpoints(tasks)
        self.assertEqual(len(results), 5)
        for r in results:
            self.assertIn('task_id', r)
            self.assertIn('seq', r)
            self.assertIn('功能分类', r)
            self.assertIn('checkpoint', r)
            self.assertIn('reason', r)


if __name__ == '__main__':
    unittest.main()
