"""数据回滚恢复接口：维护回滚记录，覆盖执行回滚、确认恢复、归档记录等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.rehearsal import rehearsal_service
from app.services.rollback import RollbackService

router = APIRouter(prefix="/api/rollback", tags=["数据回滚恢复"])

service = RollbackService()

LIST_FIELDS = ["记录编号", "表名称", "回滚版本", "回滚原因", "影响范围", "恢复耗时", "回滚时间", "回滚状态"]
STATUSES = ["待回滚", "回滚中", "已回滚", "已恢复"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待回滚、回滚中、已回滚、已恢复"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤数据回滚恢复列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rehearsals", response_model=dict)
def list_rehearsals() -> dict[str, Any]:
    """列出全部回滚预演批次，供跨回滚单核对恢复计划。"""
    items = rehearsal_service.list_rehearsals()
    return {"module": "rollback", "total": len(items), "items": items}


@router.get("/{entry_id}/rehearsal", response_model=dict)
def get_rehearsal(entry_id: int) -> dict[str, Any]:
    """读取某条回滚记录最近一次预演批次；未预演过时给出可读说明。"""
    batch = rehearsal_service.get_rehearsal(entry_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"回滚记录 {entry_id} 尚未生成回滚预演")
    return batch


@router.post("/{entry_id}/rehearsal", response_model=ActionResult)
def create_rehearsal(entry_id: int) -> ActionResult:
    """提交回滚预演：联动回滚记录、表快照、血缘与迁移状态合成恢复计划。

    恢复快照、下游表与未提交迁移来自同一预演批次，影响范围同时写回血缘影响清单。
    """
    batch, message = rehearsal_service.create_rehearsal(entry_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条回滚记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"回滚记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条回滚记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="回滚记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条回滚记录执行执行回滚、确认恢复、归档记录；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据回滚恢复清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "rollback", "total": total, "items": items}
