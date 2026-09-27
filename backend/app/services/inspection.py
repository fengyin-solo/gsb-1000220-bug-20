"""巡检计划业务规则：状态流转、字段校验、排期判定与轮次统计都收在这里。

排期口径（日期范围、站点上限、缺陷数门槛）统一走 services.scheduling，
单条登记/编辑、批量排期、列表统计看到的是同一根判定，不会各拦各的。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services import scheduling
from app.services.scheduling import (
    DATE_FIELD,
    DEFECT_FIELD,
    RECHECK_DEFECT_THRESHOLD,
    SITE_FIELD,
    TYPE_FIELD,
    parse_defect_count,
    parse_plan_date,
    validate_plan,
)
from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检编号", SITE_FIELD, TYPE_FIELD]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已漏检"]
ACTION_RULES = {"开始巡检": "执行中", "完成巡检": "已完成", "标记漏检": "已漏检"}
NEGATIVE_ACTIONS = []


class InspectionService:
    def __init__(self) -> None:
        # 已受理的批次：batch_id -> 首次提交结果，重复提交原样返回，不再累加任务。
        self._batches: dict[str, dict[str, Any]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡检编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _missing_required(self, values: dict[str, Any]) -> list[str]:
        return [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]

    def _build_entry(
        self,
        values: dict[str, Any],
        *,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        rows = store.rows(MODULE)
        site = str(values[SITE_FIELD]).strip()
        plan_date = parse_plan_date(values.get(DATE_FIELD))
        date_text = plan_date.isoformat() if plan_date else ""
        defects = parse_defect_count(values.get(DEFECT_FIELD)) or 0
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["巡检编号"] = str(values["巡检编号"]).strip()
        entry[SITE_FIELD] = site
        entry[TYPE_FIELD] = str(values[TYPE_FIELD]).strip()
        entry[DATE_FIELD] = date_text
        entry["巡检人员"] = str(values.get("巡检人员") or "").strip()
        entry["巡检路线"] = str(values.get("巡检路线") or "").strip()
        entry[DEFECT_FIELD] = defects
        entry["计划轮次"] = scheduling.count_rounds(rows, site, date_text) + 1
        entry["status"] = STATUS_ORDER[0]
        entry["巡检状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = defects >= RECHECK_DEFECT_THRESHOLD
        if batch_id:
            entry["批次号"] = batch_id
        rows.append(entry)
        return entry

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        today: date | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        missing = self._missing_required(values)
        if missing:
            return None, [f"缺少必填字段：{name}" for name in missing]
        reasons = validate_plan(values, store.rows(MODULE), today=today)
        if reasons:
            return None, reasons
        return self._build_entry(values), []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        today: date | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检任务 {entry_id} 不存在或已归档"
        merged = dict(entry)
        merged.update(values)
        missing = self._missing_required(merged)
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        reasons = validate_plan(merged, store.rows(MODULE), exclude_id=entry_id, today=today)
        if reasons:
            return None, "；".join(reasons)
        # 校验通过才落字段，站点/日期变更后轮次重新排号。
        entry["巡检编号"] = str(merged["巡检编号"]).strip()
        entry[SITE_FIELD] = str(merged[SITE_FIELD]).strip()
        entry[TYPE_FIELD] = str(merged[TYPE_FIELD]).strip()
        plan_date = parse_plan_date(merged.get(DATE_FIELD))
        entry[DATE_FIELD] = plan_date.isoformat() if plan_date else ""
        entry["巡检人员"] = str(merged.get("巡检人员") or "").strip()
        entry["巡检路线"] = str(merged.get("巡检路线") or "").strip()
        defects = parse_defect_count(merged.get(DEFECT_FIELD))
        entry[DEFECT_FIELD] = defects if defects is not None else 0
        entry["abnormal"] = entry[DEFECT_FIELD] >= RECHECK_DEFECT_THRESHOLD
        entry["计划轮次"] = scheduling.count_rounds(
            store.rows(MODULE), entry[SITE_FIELD], entry[DATE_FIELD], exclude_id=entry_id
        ) + 1
        return entry, ""

    def create_batch(
        self,
        batch_id: str,
        plans: list[dict[str, Any]],
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        """批量排期：同站点同日的轮次按计划顺序累计判定；批次幂等。"""
        batch_id = str(batch_id or "").strip()
        if not batch_id:
            return {"ok": False, "message": "缺少批次号", "batch_id": "", "duplicated": False,
                    "created": [], "rejected": []}
        if batch_id in self._batches:
            previous = self._batches[batch_id]
            return {**previous, "duplicated": True,
                    "message": f"批次 {batch_id} 已提交过，未重复累加任务"}

        created: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for index, plan in enumerate(plans):
            missing = self._missing_required(plan)
            if missing:
                rejected.append({"index": index, "values": plan,
                                 "reasons": [f"缺少必填字段：{'、'.join(missing)}"]})
                continue
            # 已通过的计划即时入库，同批后续计划判定站点上限时能“看见”它们。
            reasons = validate_plan(plan, store.rows(MODULE), today=today)
            if reasons:
                rejected.append({"index": index, "values": plan, "reasons": reasons})
                continue
            created.append(self._build_entry(plan, batch_id=batch_id))

        if created and not rejected:
            message = f"批次 {batch_id} 排期完成，共排入 {len(created)} 条"
        elif created:
            message = f"批次 {batch_id} 排入 {len(created)} 条，{len(rejected)} 条被排期规则拦截"
        else:
            message = f"批次 {batch_id} 全部 {len(rejected)} 条均未通过排期判定"

        result = {"ok": bool(created), "message": message, "batch_id": batch_id,
                  "duplicated": False, "created": created, "rejected": rejected}
        self._batches[batch_id] = result
        return result

    def stats(self) -> dict[str, Any]:
        """按同一批已入库计划统计轮次：列表数量、详情轮次、统计卡片口径一致。"""
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        status_count = {status: 0 for status in STATUS_ORDER}
        site_day: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            status = str(row.get("status") or STATUS_ORDER[0])
            status_count[status] = status_count.get(status, 0) + 1
            site = str(row.get(SITE_FIELD) or "").strip()
            plan_date = str(row.get(DATE_FIELD) or "").strip()
            bucket = site_day.setdefault(
                (site, plan_date),
                {"巡检站点": site, "计划日期": plan_date, "计划轮次": 0,
                 "最高缺陷数": 0, "任务编号": []},
            )
            bucket["计划轮次"] += 1
            bucket["任务编号"].append(str(row.get("巡检编号", "")))
            bucket["最高缺陷数"] = max(
                bucket["最高缺陷数"], parse_defect_count(row.get(DEFECT_FIELD)) or 0
            )
        site_rounds = sorted(site_day.values(), key=lambda item: (item["计划日期"], item["巡检站点"]))
        return {
            "总任务数": len(rows),
            "状态统计": status_count,
            "需复检任务": sum(1 for row in rows if row.get("abnormal")),
            "站点轮次": site_rounds,
        }

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡检计划可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["巡检状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS or bool(entry.get("abnormal"))
        return entry, f"巡检任务已{action}"
