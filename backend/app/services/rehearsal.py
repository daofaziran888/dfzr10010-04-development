"""回滚恢复预演：读取回滚记录并合成恢复计划。

预演把三类约束联动成同一份回滚影响范围，避免口径失真：

1. 快照可达性判定标准——回滚版本必须能在表快照里找到「可恢复」快照；
2. 迁移状态范围——下游表存在未提交迁移（待执行/迁移中）时不能进入已完成恢复集合；
3. 恢复条件——快照可达、迁移状态允许、且未超出允许状态范围的表才能标记为可恢复，
   其余表一律进入待处理并附原因说明。

预演与下游迁移提交在同一时间窗口冲突时，本服务只发布一份对应完整边界的恢复结果：
要么把该表列入待处理（存在未提交迁移），要么采用迁移提交后的表版本进入预演（迁移已提交，
取该表最新可恢复快照作为恢复基准），两种结论不会同时出现。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

ROLLBACK_MODULE = "rollback"
SNAPSHOT_MODULE = "snapshot"
LINEAGE_MODULE = "lineage"
MIGRATE_MODULE = "migrate"

# 快照可达性判定标准：只有处于可恢复口径内的快照才能作为回滚落点。
RECOVERABLE_SNAPSHOT_STATUSES = ("可恢复", "保留中")
# 迁移状态范围：处于该范围内的迁移任务视为未提交，会阻断下游表进入已完成恢复集合。
UNCOMMITTED_MIGRATE_STATUSES = ("待执行", "迁移中")
# 预演恢复结论。
PLAN_RECOVERABLE = "可恢复"
PLAN_PENDING = "待处理"

# 下游表逐项核对时的恢复条件口径，超出该范围的表进入待处理说明。
RECOVERY_RULES = {
    "snapshot": "回滚版本须存在状态为可恢复/保留中的表快照",
    "migration": "下游表不得存在待执行或迁移中的未提交迁移任务",
    "window": "同一时间窗口内迁移已提交时，采用迁移提交后的表版本进入预演；未提交则列入待处理",
}


class RehearsalService:
    """合成回滚预演批次，并向血缘影响清单发布同一份影响范围。"""

    def _find_target_snapshot(self, table: str, version: str) -> dict[str, Any] | None:
        """按表名称+快照版本定位恢复落点快照。"""
        for snap in store.rows(SNAPSHOT_MODULE):
            if snap.get("表名称") != table:
                continue
            if str(snap.get("快照版本") or "") != version:
                continue
            return snap
        return None

    def _downstream_tables(self, table: str) -> list[str]:
        """从湖仓血缘记录里取该表的全部下游表，按血缘记录顺序去重。"""
        downstream: list[str] = []
        for row in store.rows(LINEAGE_MODULE):
            if row.get("上游表名") != table:
                continue
            target = str(row.get("下游表名") or "")
            if target and target not in downstream:
                downstream.append(target)
        return downstream

    def _lineage_for(self, table: str, downstream: str) -> dict[str, Any] | None:
        for row in store.rows(LINEAGE_MODULE):
            if row.get("上游表名") == table and row.get("下游表名") == downstream:
                return row
        return None

    def _uncommitted_migrations(self, downstream: str) -> list[dict[str, Any]]:
        """收集直接落在该下游表上、且仍处于未提交状态范围的迁移任务。

        只按下游表本身（迁移源或目标）匹配：一条 finance_ledger→dws_ledger_daily 的
        迁移只阻断 dws_ledger_daily，不会波及其它下游表，避免影响范围被放大失真。
        """
        pending: list[dict[str, Any]] = []
        for task in store.rows(MIGRATE_MODULE):
            if task.get("status") not in UNCOMMITTED_MIGRATE_STATUSES:
                continue
            involved = {str(task.get("源表名") or ""), str(task.get("目标表名") or "")}
            if downstream in involved:
                pending.append(task)
        return pending

    def _latest_recoverable_snapshot(self, table: str) -> dict[str, Any] | None:
        """取下游表迁移提交后的最新可恢复快照作为预演基准版本。"""
        candidates = [
            snap for snap in store.rows(SNAPSHOT_MODULE)
            if snap.get("表名称") == table
            and snap.get("快照状态") in RECOVERABLE_SNAPSHOT_STATUSES
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: str(item.get("快照时间") or ""))

    def _build_downstream_plan(
        self,
        upstream_table: str,
        downstream: str,
    ) -> dict[str, Any]:
        """逐张下游表核对快照与迁移，合成单项恢复结论。"""
        lineage = self._lineage_for(upstream_table, downstream) or {}
        pending_migrations = self._uncommitted_migrations(downstream)
        latest_snapshot = self._latest_recoverable_snapshot(downstream)

        reasons: list[str] = []
        if latest_snapshot is None:
            reasons.append("下游表缺少可恢复快照，不满足快照可达性判定标准")
        if pending_migrations:
            task_ids = "、".join(str(task.get("任务编号")) for task in pending_migrations)
            reasons.append(
                f"存在未提交迁移（{task_ids}），迁移状态处于允许恢复范围之外，"
                "不能进入已完成恢复集合"
            )

        if reasons:
            conclusion = PLAN_PENDING
            recovery_snapshot = None
            adopted_version = None
        else:
            conclusion = PLAN_RECOVERABLE
            recovery_snapshot = latest_snapshot
            adopted_version = str(latest_snapshot.get("快照版本") or "") if latest_snapshot else None

        return {
            "下游表名": downstream,
            "血缘记录编号": lineage.get("记录编号"),
            "转换类型": lineage.get("转换类型"),
            "操作批次": lineage.get("操作批次"),
            "恢复结论": conclusion,
            "预演采用版本": adopted_version,
            "恢复快照编号": latest_snapshot.get("快照编号") if latest_snapshot else None,
            "待处理说明": "；".join(reasons),
            "未提交迁移": [
                {
                    "任务编号": task.get("任务编号"),
                    "源表名": task.get("源表名"),
                    "目标表名": task.get("目标表名"),
                    "迁移状态": task.get("status"),
                    "数据范围": task.get("数据范围"),
                }
                for task in pending_migrations
            ],
        }

    def create_rehearsal(self, rollback_id: int) -> tuple[dict[str, Any] | None, str]:
        """读取回滚记录并预演恢复，生成一个带批次号的完整恢复计划。"""
        entry = store.find(ROLLBACK_MODULE, rollback_id)
        if entry is None:
            return None, f"回滚记录 {rollback_id} 不存在或已归档"

        table = str(entry.get("表名称") or "")
        version = str(entry.get("回滚版本") or "")
        target_snapshot = self._find_target_snapshot(table, version)

        snapshot_reachable = (
            target_snapshot is not None
            and target_snapshot.get("快照状态") in RECOVERABLE_SNAPSHOT_STATUSES
        )

        snapshot_checks: list[dict[str, Any]] = []
        if target_snapshot is None:
            snapshot_checks.append({
                "判定项": "快照可达性",
                "通过": False,
                "说明": f"表 {table} 不存在版本 {version} 的快照，回滚版本未指向任何可恢复快照",
            })
        elif not snapshot_reachable:
            snapshot_checks.append({
                "判定项": "快照可达性",
                "通过": False,
                "说明": (
                    f"快照 {target_snapshot.get('快照编号')} 状态为"
                    f"「{target_snapshot.get('快照状态')}」，超出可恢复快照状态范围"
                ),
            })
        else:
            snapshot_checks.append({
                "判定项": "快照可达性",
                "通过": True,
                "说明": (
                    f"回滚版本 {version} 指向可恢复快照 {target_snapshot.get('快照编号')}"
                    f"（{target_snapshot.get('快照时间')}）"
                ),
            })

        downstream_tables = self._downstream_tables(table)
        downstream_plans = [
            self._build_downstream_plan(table, downstream) for downstream in downstream_tables
        ]

        # 主表快照不可达时，整张回滚单都无法形成已完成恢复集合。
        if not snapshot_reachable:
            for plan in downstream_plans:
                if plan["恢复结论"] == PLAN_RECOVERABLE:
                    plan["恢复结论"] = PLAN_PENDING
                    plan["预演采用版本"] = None
                    plan["恢复快照编号"] = None
                    plan["待处理说明"] = (
                        (plan["待处理说明"] + "；" if plan["待处理说明"] else "")
                        + "上游回滚版本未指向可恢复快照，恢复条件不成立"
                    )

        recoverable_tables = [
            plan["下游表名"] for plan in downstream_plans if plan["恢复结论"] == PLAN_RECOVERABLE
        ]
        pending_tables = [
            plan["下游表名"] for plan in downstream_plans if plan["恢复结论"] == PLAN_PENDING
        ]
        uncommitted_migrations: list[dict[str, Any]] = []
        seen_task_ids: set[str] = set()
        for plan in downstream_plans:
            for migration in plan["未提交迁移"]:
                task_id = str(migration.get("任务编号"))
                if task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)
                uncommitted_migrations.append(migration)

        batch = {
            "预演批次号": self._next_batch_no(),
            "回滚记录id": rollback_id,
            "回滚记录编号": entry.get("记录编号"),
            "表名称": table,
            "回滚版本": version,
            "预演时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "快照可达": snapshot_reachable,
            "约束口径": dict(RECOVERY_RULES),
            "恢复快照": self._snapshot_view(target_snapshot),
            "快照核对": snapshot_checks,
            "下游表": downstream_plans,
            "未提交迁移": uncommitted_migrations,
            "已完成恢复集合": recoverable_tables,
            "待处理集合": pending_tables,
            "影响范围表清单": [table, *downstream_tables],
            "影响范围摘要": self._impact_summary(table, version, downstream_plans, snapshot_reachable),
            "版本结论": self._version_conclusion(snapshot_reachable, downstream_plans),
        }

        store.save_rehearsal(rollback_id, batch)
        self._publish_to_lineage(batch)
        # 回写回滚记录，保证回滚列表入口看到的影响范围与血缘影响清单同源。
        entry["影响范围"] = batch["影响范围摘要"]
        entry["预演批次号"] = batch["预演批次号"]
        return batch, "回滚恢复预演已生成，影响范围已同步到血缘影响清单"

    def _snapshot_view(self, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        return {
            "快照编号": snapshot.get("快照编号"),
            "表名称": snapshot.get("表名称"),
            "快照版本": snapshot.get("快照版本"),
            "快照时间": snapshot.get("快照时间"),
            "快照状态": snapshot.get("快照状态"),
            "快照大小": snapshot.get("快照大小"),
            "保留天数": snapshot.get("保留天数"),
            "创建方式": snapshot.get("创建方式"),
        }

    def _impact_summary(
        self,
        table: str,
        version: str,
        plans: list[dict[str, Any]],
        snapshot_reachable: bool,
    ) -> str:
        scope = "、".join([table, *(plan["下游表名"] for plan in plans)])
        head = f"{table}@{version} 影响 {len(plans) + 1} 张表（{scope}）"
        if not snapshot_reachable:
            return head + "；回滚版本快照不可达，全部进入待处理"
        pending = [plan["下游表名"] for plan in plans if plan["恢复结论"] == PLAN_PENDING]
        if pending:
            return head + f"；待处理 {len(pending)} 张：{'、'.join(pending)}"
        return head + "；全部满足恢复条件"

    def _version_conclusion(
        self,
        snapshot_reachable: bool,
        plans: list[dict[str, Any]],
    ) -> str:
        if not snapshot_reachable:
            return "回滚版本未指向可恢复快照，预演不成立，影响范围内表全部列入待处理"
        if any(plan["恢复结论"] == PLAN_PENDING for plan in plans):
            return "回滚版本快照可达；存在未提交迁移或恢复条件不满足的下游表，按完整边界发布一份恢复结果"
        return "回滚版本快照可达，下游表均可采用迁移提交后的表版本进入预演"

    def _publish_to_lineage(self, batch: dict[str, Any]) -> None:
        """把同一份影响范围写回血缘影响清单，并保留下游表与迁移批次的关系。"""
        impacts: list[dict[str, Any]] = []
        for plan in batch["下游表"]:
            migration_batches = [
                str(task.get("任务编号")) for task in plan["未提交迁移"]
            ]
            impacts.append({
                "预演批次号": batch["预演批次号"],
                "回滚记录编号": batch["回滚记录编号"],
                "上游表名": batch["表名称"],
                "回滚版本": batch["回滚版本"],
                "下游表名": plan["下游表名"],
                "血缘记录编号": plan["血缘记录编号"],
                "操作批次": plan["操作批次"],
                "恢复结论": plan["恢复结论"],
                "预演采用版本": plan["预演采用版本"],
                "关联迁移批次": "、".join(migration_batches),
                "待处理说明": plan["待处理说明"],
                "版本结论": batch["版本结论"],
                "影响范围摘要": batch["影响范围摘要"],
                "发布时间": batch["预演时间"],
            })
        store.replace_lineage_impacts(batch["回滚记录id"], impacts)

    def _next_batch_no(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        seq = store.next_rehearsal_seq()
        return f"REH-{today}-{seq:03d}"

    def list_rehearsals(self) -> list[dict[str, Any]]:
        return store.list_rehearsals()

    def get_rehearsal(self, rollback_id: int) -> dict[str, Any] | None:
        return store.get_rehearsal(rollback_id)


rehearsal_service = RehearsalService()
