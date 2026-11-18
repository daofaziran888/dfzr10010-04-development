"""回滚恢复预演业务规则测试：只依赖标准库，直接 python -m unittest 即可运行。"""
from __future__ import annotations

import unittest

from app.services.rehearsal import (
    PLAN_PENDING,
    PLAN_RECOVERABLE,
    UNCOMMITTED_MIGRATE_STATUSES,
    rehearsal_service,
)
from app.store import store


class RehearsalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()

    def test_finance_ledger_rollback_to_reachable_version(self) -> None:
        """finance_ledger 回滚 v20261110：快照可达，影响范围含全部下游表。"""
        batch, message = rehearsal_service.create_rehearsal(4)

        self.assertIsNotNone(batch)
        self.assertTrue(batch["快照可达"])
        self.assertEqual(batch["恢复快照"]["快照版本"], "v20261110")
        self.assertEqual(
            batch["影响范围表清单"],
            ["finance_ledger", "report_finance", "dws_ledger_daily", "ads_finance_monthly"],
        )
        conclusions = {plan["下游表名"]: plan["恢复结论"] for plan in batch["下游表"]}
        # 迁移中的 dws_ledger_daily 不能进入已完成恢复集合。
        self.assertEqual(conclusions["dws_ledger_daily"], PLAN_PENDING)
        self.assertEqual(conclusions["report_finance"], PLAN_RECOVERABLE)
        self.assertEqual(conclusions["ads_finance_monthly"], PLAN_RECOVERABLE)
        # 恢复快照、下游表、未提交迁移来自同一预演批次。
        self.assertEqual(len(batch["未提交迁移"]), 1)
        self.assertEqual(batch["未提交迁移"][0]["任务编号"], "MIGR-20261115-17")
        self.assertEqual(batch["已完成恢复集合"], ["report_finance", "ads_finance_monthly"])
        self.assertEqual(batch["待处理集合"], ["dws_ledger_daily"])
        self.assertIn("REH-", batch["预演批次号"])

    def test_pending_plan_keeps_migration_batch_relation(self) -> None:
        """待处理项必须保留与迁移批次的关系及可读原因。"""
        batch, _ = rehearsal_service.create_rehearsal(4)
        dws = next(plan for plan in batch["下游表"] if plan["下游表名"] == "dws_ledger_daily")

        self.assertIsNone(dws["预演采用版本"])
        self.assertEqual(
            [task["任务编号"] for task in dws["未提交迁移"]],
            ["MIGR-20261115-17"],
        )
        self.assertIn("MIGR-20261115-17", dws["待处理说明"])
        self.assertIn("不能进入已完成恢复集合", dws["待处理说明"])

    def test_committed_migration_uses_post_commit_version(self) -> None:
        """时间窗口冲突的另一面：已提交迁移的表采用提交后版本进入预演。"""
        batch, _ = rehearsal_service.create_rehearsal(4)
        ads = next(plan for plan in batch["下游表"] if plan["下游表名"] == "ads_finance_monthly")

        self.assertEqual(ads["恢复结论"], PLAN_RECOVERABLE)
        self.assertEqual(ads["预演采用版本"], "v20261118-post-migr")
        self.assertEqual(ads["未提交迁移"], [])

    def test_unreachable_snapshot_marks_all_pending(self) -> None:
        """回滚版本指向已过期快照时，全部下游表进入待处理且结论不成立。"""
        batch, _ = rehearsal_service.create_rehearsal(5)

        self.assertFalse(batch["快照可达"])
        self.assertEqual(batch["已完成恢复集合"], [])
        self.assertEqual(
            set(batch["待处理集合"]),
            {"report_finance", "dws_ledger_daily", "ads_finance_monthly"},
        )
        self.assertFalse(batch["快照核对"][0]["通过"])
        self.assertIn("已过期", batch["快照核对"][0]["说明"])
        self.assertIn("未指向可恢复快照", batch["版本结论"])

    def test_publish_single_consistent_impact_scope(self) -> None:
        """血缘影响清单与预演批次同源；重复预演只保留一份完整边界结果。"""
        rehearsal_service.create_rehearsal(4)
        latest, _ = rehearsal_service.create_rehearsal(4)

        impacts = store.lineage_impacts(4)
        self.assertEqual(len(impacts), 3)  # 三张下游表，没有因重复预演翻倍
        # 影响清单整体刷新为最新预演批次，只发布一份完整边界结果。
        self.assertTrue(all(row["预演批次号"] == latest["预演批次号"] for row in impacts))
        self.assertEqual(
            sorted((row["下游表名"], row["恢复结论"]) for row in impacts),
            sorted((plan["下游表名"], plan["恢复结论"]) for plan in latest["下游表"]),
        )
        # 版本结论同步到血缘影响清单。
        self.assertTrue(all(row["版本结论"] == latest["版本结论"] for row in impacts))
        # 回滚记录影响范围被回写，回滚列表入口读到同一份口径。
        self.assertEqual(store.find("rollback", 4)["影响范围"], latest["影响范围摘要"])

    def test_lineage_impacts_keep_downstream_batch_relation(self) -> None:
        """血缘影响清单保留下游表与迁移批次、血缘操作批次的关系。"""
        rehearsal_service.create_rehearsal(4)
        impacts = {row["下游表名"]: row for row in store.lineage_impacts(4)}

        self.assertEqual(impacts["dws_ledger_daily"]["关联迁移批次"], "MIGR-20261115-17")
        self.assertEqual(impacts["dws_ledger_daily"]["操作批次"], "BATCH-20261116-DW")
        self.assertEqual(impacts["report_finance"]["关联迁移批次"], "")
        self.assertEqual(impacts["report_finance"]["操作批次"], "BATCH-20261117-DW")

    def test_unknown_rollback_returns_error(self) -> None:
        batch, message = rehearsal_service.create_rehearsal(999)
        self.assertIsNone(batch)
        self.assertIn("不存在", message)

    def test_uncommitted_status_scope_constant(self) -> None:
        """迁移状态范围口径固定：只有待执行/迁移中视为未提交。"""
        self.assertEqual(UNCOMMITTED_MIGRATE_STATUSES, ("待执行", "迁移中"))


if __name__ == "__main__":
    unittest.main()
