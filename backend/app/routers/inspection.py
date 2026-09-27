"""巡检计划接口：维护巡检任务，覆盖登记、单条编辑、批量排期与状态流转。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchPayload, EntryPayload, PageResult
from app.services.inspection import InspectionService

router = APIRouter(prefix="/api/inspection", tags=["巡检计划"])

service = InspectionService()

LIST_FIELDS = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "计划轮次", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
STATUSES = ["待执行", "执行中", "已完成", "已漏检"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡检编号检索"),
    status: str | None = Query(default=None, description="待执行、执行中、已完成、已漏检"),
    site: str | None = Query(default=None, description="按巡检站点过滤"),
    inspect_type: str | None = Query(default=None, description="按巡检类型过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、站点、类型与状态过滤巡检计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, site=site, inspect_type=inspect_type, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """列表统计：状态分布与今日轮次，口径与列表、详情完全一致。"""
    return service.stats()


@router.post("/batch")
def batch_schedule(payload: BatchPayload) -> dict[str, Any]:
    """批量排期：每条计划过与单条登记相同的排期判定；按巡检编号幂等，重复提交不累加。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="批量排期内容为空，请至少提交一条计划")
    return service.batch_schedule(payload.items)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出巡检计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "inspection", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡检任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡检任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡检任务，缺字段或不满足排期规则时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="巡检任务已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """单条编辑巡检任务：与登记、批量排期走同一根排期判定。"""
    entry, problems = service.update_entry(entry_id, payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="巡检任务已更新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检任务执行开始巡检、完成巡检、标记漏检；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
