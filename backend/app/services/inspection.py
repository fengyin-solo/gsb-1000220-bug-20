"""巡检计划业务规则：排期判定、状态流转与统计口径都收在这里。

排期规则只有一份（evaluate_schedule）：单条登记/编辑、批量排期、列表统计
都走同一根判定，避免各入口口径不一。规则包含三块：
- 日期范围：计划日期必须落在今天起 SCHEDULE_WINDOW_DAYS 天的排期窗口内；
- 站点上限：同一巡检站点同一天最多排 MAX_ROUNDS_PER_SITE_DAY 轮；
- 缺陷数门槛：发现缺陷数达到 DEFECT_THRESHOLD 的任务先转故障处置，不再直接排期。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检编号", "巡检站点", "巡检类型"]
SCHEDULE_FIELDS = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "巡检人员", "巡检路线", "发现缺陷数"]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已漏检"]
ACTION_RULES = {"开始巡检": "执行中", "完成巡检": "已完成", "标记漏检": "已漏检"}
NEGATIVE_ACTIONS = []

SCHEDULE_WINDOW_DAYS = 30
MAX_ROUNDS_PER_SITE_DAY = 2
DEFECT_THRESHOLD = 5


def _parse_plan_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_defect_count(value: Any) -> int | None:
    """发现缺陷数：留空按 0 处理；填了就必须是非负整数，否则返回 None 由调用方报错。"""
    text = str(value if value is not None else "").strip()
    if not text:
        return 0
    try:
        count = int(text)
    except ValueError:
        return None
    return count if count >= 0 else None


def _same_day_rows(rows: list[dict[str, Any]], site: str, plan_date: date, exclude_id: int | None) -> list[dict[str, Any]]:
    """同一站点同一天已排的轮次，按 id 排序保证口径稳定。"""
    key = plan_date.isoformat()
    matched = [
        row for row in rows
        if str(row.get("巡检站点") or "").strip() == site
        and str(row.get("计划日期") or "").strip() == key
        and int(row.get("id", 0)) != (exclude_id or 0)
    ]
    return sorted(matched, key=lambda row: int(row.get("id", 0)))


def evaluate_schedule(
    values: dict[str, Any],
    rows: list[dict[str, Any]],
    exclude_id: int | None = None,
) -> tuple[list[str], int | None]:
    """统一排期判定：日期范围、站点上限、缺陷数门槛。

    返回 (问题列表, 计划轮次)；问题列表为空即允许排期，计划轮次为排入后的轮次号。
    exclude_id 用于单条编辑时把自身从轮次统计里剔除。
    """
    problems: list[str] = []
    site = str(values.get("巡检站点") or "").strip()

    plan_date = _parse_plan_date(values.get("计划日期"))
    if plan_date is None:
        problems.append("计划日期缺失或格式应为 YYYY-MM-DD")
    else:
        today = date.today()
        if plan_date < today:
            problems.append("计划日期早于今天，不在排期窗口内")
        elif (plan_date - today).days > SCHEDULE_WINDOW_DAYS:
            problems.append(f"计划日期超出 {SCHEDULE_WINDOW_DAYS} 天排期窗口")

    defect_count = _parse_defect_count(values.get("发现缺陷数"))
    if defect_count is None:
        problems.append("发现缺陷数需为非负整数")
    elif defect_count >= DEFECT_THRESHOLD:
        problems.append(f"发现缺陷数 {defect_count} 已达到 {DEFECT_THRESHOLD} 的门槛，请先转故障处置再排期")

    round_no: int | None = None
    if site and plan_date is not None:
        existing = _same_day_rows(rows, site, plan_date, exclude_id)
        round_no = len(existing) + 1
        if round_no > MAX_ROUNDS_PER_SITE_DAY:
            problems.append(
                f"{site} 在 {plan_date.isoformat()} 已排 {len(existing)} 轮，"
                f"同一站点同一天最多 {MAX_ROUNDS_PER_SITE_DAY} 轮"
            )
    return problems, round_no


def attach_rounds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给每行补上计划轮次：同站点同日内按 id 排序编号，列表、详情、统计共用这一份。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("巡检站点") or "").strip(), str(row.get("计划日期") or "").strip())
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        group.sort(key=lambda row: int(row.get("id", 0)))
        for index, row in enumerate(group, start=1):
            row["计划轮次"] = index
    return rows


class InspectionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        site: str | None = None,
        inspect_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = attach_rounds(store.rows(MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡检编号", ""))]
        if site:
            rows = [row for row in rows if site in str(row.get("巡检站点", ""))]
        if inspect_type:
            rows = [row for row in rows if inspect_type in str(row.get("巡检类型", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 按 id 稳定排序，避免重新查询时分页重复或错位
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        rows = attach_rounds(store.rows(MODULE))
        for row in rows:
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def stats(self) -> dict[str, Any]:
        """列表统计：状态分布与轮次口径都和列表/详情保持一致。"""
        rows = attach_rounds(store.rows(MODULE))
        today = date.today().isoformat()
        return {
            "cards": [
                {"label": "待巡检任务", "value": sum(1 for row in rows if row.get("status") == "待执行")},
                {"label": "已完成巡检", "value": sum(1 for row in rows if row.get("status") == "已完成")},
                {"label": "漏检任务", "value": sum(1 for row in rows if row.get("status") == "已漏检")},
            ],
            "total": len(rows),
            "today_rounds": sum(1 for row in rows if str(row.get("计划日期") or "").strip() == today),
        }

    def _next_id(self, rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def _build_entry(self, rows: list[dict[str, Any]], values: dict[str, Any], round_no: int) -> dict[str, Any]:
        entry = {"id": self._next_id(rows)}
        for field in SCHEDULE_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry["计划日期"] = str(values.get("计划日期") or "").strip()
        entry["计划轮次"] = round_no
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{field}" for field in missing]
        rows = store.rows(MODULE)
        problems, round_no = evaluate_schedule(values, rows)
        if problems:
            return None, problems
        entry = self._build_entry(rows, values, round_no or 1)
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """单条编辑：与登记走同一根排期判定，轮次统计时剔除自身。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"巡检任务 {entry_id} 不存在或已归档"]
        merged = {**entry, **values}
        missing = [field for field in REQUIRED_FIELDS if not str(merged.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{field}" for field in missing]
        rows = store.rows(MODULE)
        problems, round_no = evaluate_schedule(merged, rows, exclude_id=entry_id)
        if problems:
            return None, problems
        for field in SCHEDULE_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry["计划日期"] = str(merged.get("计划日期") or "").strip()
        entry["计划轮次"] = round_no or 1
        return entry, []

    def batch_schedule(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """批量排期：每条都过同一根排期判定；按巡检编号幂等，重复提交不累加。"""
        rows = store.rows(MODULE)
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen_codes = {str(row.get("巡检编号") or "").strip() for row in rows}
        for values in items:
            code = str(values.get("巡检编号") or "").strip()
            if not code:
                rejected.append({"values": values, "reasons": ["缺少必填字段：巡检编号"]})
                continue
            if code in seen_codes:
                skipped.append({"巡检编号": code, "reason": "相同巡检编号已排期，跳过不重复累加"})
                continue
            entry, problems = self.create_entry(values)
            if entry is None:
                rejected.append({"values": values, "reasons": problems})
                continue
            seen_codes.add(code)
            created.append(entry)
        return {
            "created": created,
            "skipped": skipped,
            "rejected": rejected,
            "summary": {"created": len(created), "skipped": len(skipped), "rejected": len(rejected)},
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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡检任务已{action}"
