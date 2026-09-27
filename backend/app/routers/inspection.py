"""巡检计划接口：维护巡检任务，覆盖单条登记/编辑、批量排期、轮次统计与状态流转。

排期判定统一走 services.scheduling，路由层只负责转发，不另写规则。
注意：/stats、/export 等字面量路径必须声明在 /{entry_id} 之前，否则会被
路径参数抢走（/export 曾被当成 entry_id 解析而 422）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchSchedulePayload, BatchScheduleResult, EntryPayload, PageResult
from app.services.inspection import InspectionService

router = APIRouter(prefix="/api/inspection", tags=["巡检计划"])

service = InspectionService()

LIST_FIELDS = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "计划轮次", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
STATUSES = ["待执行", "执行中", "已完成", "已漏检"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡检编号检索"),
    status: str | None = Query(default=None, description="待执行、执行中、已完成、已漏检"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡检编号与状态过滤巡检计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats", response_model=dict)
def stats() -> dict:
    """轮次统计：状态分布、需复检任务数与站点当日轮次，和列表、详情同源。"""
    return service.stats()


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
    """登记一条巡检任务：先过统一排期判定，被拦下时逐条说明原因。"""
    entry, reasons = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message="；".join(reasons))
    return ActionResult(ok=True, message="巡检任务已登记", entry=entry)


@router.post("/batch", response_model=BatchScheduleResult)
def create_batch(payload: BatchSchedulePayload) -> BatchScheduleResult:
    """批量排期：与单条共用同一套排期判定；同一 batch_id 重复提交不累加。"""
    if not payload.plans:
        return BatchScheduleResult(
            ok=False, message="批次里没有可排期的计划", batch_id=payload.batch_id,
        )
    result = service.create_batch(payload.batch_id, payload.plans)
    return BatchScheduleResult(**result)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑单条巡检任务：与登记走同一套排期判定，校验不过则原样保留。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="巡检任务已更新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检任务执行开始巡检、完成巡检、标记漏检；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
