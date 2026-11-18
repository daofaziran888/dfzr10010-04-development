"""湖仓血缘追踪接口：维护血缘记录，覆盖关联血缘、标记过期、清理记录等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.lineage import LineageService
from app.store import store

router = APIRouter(prefix="/api/lineage", tags=["湖仓血缘追踪"])

service = LineageService()

LIST_FIELDS = ["记录编号", "上游表名", "下游表名", "转换类型", "字段映射", "操作时间", "操作批次", "记录状态"]
STATUSES = ["已记录", "已关联", "已过期", "已清理"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="已记录、已关联、已过期、已清理"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤湖仓血缘追踪列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/impacts", response_model=PageResult[dict])
def list_impacts(
    rollback_id: int | None = Query(default=None, description="按回滚记录 id 过滤影响范围"),
    keyword: str | None = Query(default=None, description="按上游/下游表名或回滚记录编号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """血缘影响清单：回滚预演发布的同一份影响范围，保留下游表与迁移批次关系。

    回滚列表入口与本入口读取的是同一份数据，保证两个页面展示的回滚影响范围一致。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    rows = store.lineage_impacts(rollback_id)
    if keyword:
        rows = [
            row for row in rows
            if keyword in str(row.get("上游表名", ""))
            or keyword in str(row.get("下游表名", ""))
            or keyword in str(row.get("回滚记录编号", ""))
        ]
    total = len(rows)
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/impacts/summary", response_model=dict)
def impacts_summary() -> dict[str, Any]:
    """血缘影响清单汇总：按预演批次核对一份完整边界的恢复结果。"""
    batches: dict[str, dict[str, Any]] = {}
    for row in store.lineage_impacts():
        batch_no = str(row.get("预演批次号"))
        batch = batches.setdefault(batch_no, {
            "预演批次号": batch_no,
            "回滚记录编号": row.get("回滚记录编号"),
            "上游表名": row.get("上游表名"),
            "回滚版本": row.get("回滚版本"),
            "影响下游表数": 0,
            "可恢复表数": 0,
            "待处理表数": 0,
            "关联迁移批次": set(),
            "版本结论": row.get("版本结论"),
            "影响范围摘要": row.get("影响范围摘要"),
            "发布时间": row.get("发布时间"),
        })
        batch["影响下游表数"] += 1
        if row.get("恢复结论") == "可恢复":
            batch["可恢复表数"] += 1
        else:
            batch["待处理表数"] += 1
        if row.get("关联迁移批次"):
            for task in str(row["关联迁移批次"]).split("、"):
                if task:
                    batch["关联迁移批次"].add(task)
    items = []
    for batch in batches.values():
        batch["关联迁移批次"] = "、".join(sorted(batch["关联迁移批次"]))
        items.append(batch)
    items.sort(key=lambda item: str(item.get("发布时间") or ""), reverse=True)
    return {"total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条血缘记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"血缘记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条血缘记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="血缘记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条血缘记录执行关联血缘、标记过期、清理记录；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出湖仓血缘追踪清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "lineage", "total": total, "items": items}
