# SMMUv3 accel=on 热迁移 RFC 测试工作区

> 测试对象:[RFC PATCH 0/7] hw/arm/smmuv3: Live migration for accel=on
> (Shameer Kolothum <skolothumtho@nvidia.com>,2026-09-04,qemu-devel)
> 测试设备:海思加速器 VF(hisi_acc_vfio_pci,支持 VFIO live migration,无自跟踪脏页)
> 目标:真机验证后向社区回复 Tested-by

## 快速回答三个问题

**Q1:需要哪些 patch?**
- QEMU:upstream master `99e54ab5e7`(2026-09-03)+ 7 个 RFC patch + 1 个额外的 pci fix
  (作者分支上有、邮件系列里没有)—— 共 8 个,见 `patches/qemu/0001~0008`
- 内核:**不需要自己打任何 patch**,直接用作者的 `iommu_pt_arm64_s2_dbm` 分支
  (已含 vEVENTQ / vIOMMU / iommupt 栈 / s2-DBM / hisi_acc 驱动全套)

**Q2:kernel 要不要改?**
- 代码:**不用改**(作者分支全齐,hisi_acc 驱动与 openEuler 6.6 版本无功能差异,已核对)
- 要做的只有:①config ②**验证它能在测试服务器上启动**(mainline 基础,平台私货可能要移植)
- ⚠️ 不要试图在 openEuler 6.6 上改:那是旧一代 iommufd(无 vEVENTQ/viommu 新语义),代差太大

**Q3:怎么开始?**
按 `test-plan.md` §3 Pre-flight 清单先过三个硬门槛(内核可启动 / SMMU 有 DBM / QM V4+),
再按 TC1→TC8 顺序执行。QEMU 测试分支已就绪:`/home/akira/code/qemu/qemu` 的
`smmuv3-accel-live-migrn-rfcv1` 分支。

## 目录结构

```
smmuv3_live_migration_test/
├── README.md                # 本文件:索引与快速上手
├── test-plan.md             # 完整测试计划(命令行/12 用例总表 §5.0/压力基准/性能数据表/Tested-by 模板)
└── patches/
    ├── qemu/
    │   ├── 0001~0007-*.patch   # 7 个 RFC patch(git format-patch 导出)
    │   ├── 0008-pci-pcie-*.patch  # 额外的 Link Status 2 修复(邮件系列外,必打)
    │   └── 20260904_skolothumtho_*.mbx/.cover  # b4 下载的原始邮件(git am 可直接用)
    └── kernel/
        └── iommu-arm-smmu-v3-Enable-stage-2-dirty-tracking-*.patch
                                 # s2-DBM 关键内核提交(参考;完整内核用作者分支)
```

## QEMU 测试分支(已就绪)

位置:`/home/akira/code/qemu/qemu`,分支 `smmuv3-accel-live-migrn-rfcv1`

复现方式:

```bash
git switch -c smmuv3-accel-live-migrn-rfcv1 99e54ab5e7
git am patches/qemu/20260904_skolothumtho_hw_arm_smmuv3_live_migration_for_accel_on.mbx
git fetch https://github.com/shamiali2008/qemu-master.git smmuv3-accel-live-migrn-rfcv1
git cherry-pick FETCH_HEAD   # 第 8 个 pci fix
```

已验证:与作者分支 tip `git diff` 为空(逐字节一致)。

## 相关链接

| 资源 | 链接 |
|---|---|
| RFC 邮件(回复 Tested-by 的对象) | https://lore.kernel.org/qemu-devel/20260904180513.248396-1-skolothumtho@nvidia.com/ |
| 作者 QEMU 分支 | https://github.com/shamiali2008/qemu-master/tree/smmuv3-accel-live-migrn-rfcv1 |
| 作者内核分支(必须用) | https://github.com/shamiali2008/linux/commits/iommu_pt_arm64_s2_dbm/ |
| 上游 accel SMMUv3 主系列(v9, 37p) | patchwork.kernel.org 系列 "user-creatable accelerated SMMUv3" |
| 上游 vEVENTQ 系列(v3, 4p) | patchwork.kernel.org 系列 "vEVENTQ support for accelerated SMMUv3" |
