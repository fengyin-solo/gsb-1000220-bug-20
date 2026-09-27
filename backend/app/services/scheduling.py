"""巡检排期规则：日期范围、站点上限、缺陷数门槛。

单条编辑、批量排期、列表统计三个入口都从这里取判定，不再各写一套：

- 日期范围：计划日期必须落在 [今天, 今天 + SCHEDULE_WINDOW_DAYS]；
- 站点上限：同一巡检站点、同一天默认最多 MAX_ROUNDS_PER_SITE_DAY 轮；
- 缺陷数门槛：站点当日已有任务发现缺陷数达到 RECHECK_DEFECT_THRESHOLD
  （或本次计划自身缺陷数已达门槛）时，可加排 1 轮复检，加排轮次巡检类型
  必须带「复检」，其余情况下第三轮一律拦截。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

SCHEDULE_WINDOW_DAYS = 30
MAX_ROUNDS_PER_SITE_DAY = 2
RECHECK_DEFECT_THRESHOLD = 3
RECHECK_TYPE_KEYWORD = "复检"

SITE_FIELD = "巡检站点"
DATE_FIELD = "计划日期"
DEFECT_FIELD = "发现缺陷数"
TYPE_FIELD = "巡检类型"


def parse_plan_date(value: Any) -> date | None:
    """把计划日期解析成 date；空值或非法格式返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_defect_count(value: Any) -> int | None:
    """发现缺陷数必须是非负整数；缺失按 0 处理，非法值返回 None。"""
    if value is None or str(value).strip() == "":
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def is_recheck(values: dict[str, Any]) -> bool:
    return RECHECK_TYPE_KEYWORD in str(values.get(TYPE_FIELD) or "")


def _same_site_day(row: dict[str, Any], site: str, plan_date: str) -> bool:
    return str(row.get(SITE_FIELD) or "").strip() == site and str(row.get(DATE_FIELD) or "").strip() == plan_date


def count_rounds(
    rows: list[dict[str, Any]],
    site: str,
    plan_date: str,
    *,
    exclude_id: int | None = None,
) -> int:
    """统计某站点某天已排入的轮次；编辑场景用 exclude_id 排除自身。"""
    return sum(
        1
        for row in rows
        if _same_site_day(row, site, plan_date) and int(row.get("id", 0)) != (exclude_id or -1)
    )


def max_defect_count(
    rows: list[dict[str, Any]],
    site: str,
    plan_date: str,
    *,
    exclude_id: int | None = None,
) -> int:
    """某站点某天已排任务里的最高缺陷数，用于判断是否触发复检门槛。"""
    defects = [
        parse_defect_count(row.get(DEFECT_FIELD)) or 0
        for row in rows
        if _same_site_day(row, site, plan_date) and int(row.get("id", 0)) != (exclude_id or -1)
    ]
    return max(defects, default=0)


def validate_plan(
    values: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    exclude_id: int | None = None,
    today: date | None = None,
) -> list[str]:
    """对一条排期计划做统一判定，返回拦截原因列表；空列表表示放行。

    批量排期逐条入库后再判下一条，已入库的同批计划自然参与站点上限与
    编号唯一性判定，批内不会互相“看不见”而超排或重号。
    """
    today = today or date.today()
    reasons: list[str] = []

    serial = str(values.get("巡检编号") or "").strip()
    if serial and any(
        str(row.get("巡检编号") or "").strip() == serial and int(row.get("id", 0)) != (exclude_id or -1)
        for row in rows
    ):
        reasons.append(f"巡检编号 {serial} 已存在，不能重复排期")

    site = str(values.get(SITE_FIELD) or "").strip()
    if not site:
        reasons.append("巡检站点不能为空")

    plan_date = parse_plan_date(values.get(DATE_FIELD))
    if plan_date is None:
        reasons.append("计划日期格式应为 YYYY-MM-DD")
    else:
        earliest, latest = today, today + timedelta(days=SCHEDULE_WINDOW_DAYS)
        if plan_date < earliest or plan_date > latest:
            reasons.append(f"计划日期需在 {earliest.isoformat()} 至 {latest.isoformat()} 之间")

    defects = parse_defect_count(values.get(DEFECT_FIELD))
    if defects is None:
        reasons.append("发现缺陷数必须是非负整数")
        defects = 0

    if site and plan_date is not None:
        date_text = plan_date.isoformat()
        existing = count_rounds(rows, site, date_text, exclude_id=exclude_id)

        threshold_hit = (
            defects >= RECHECK_DEFECT_THRESHOLD
            or max_defect_count(rows, site, date_text, exclude_id=exclude_id) >= RECHECK_DEFECT_THRESHOLD
        )
        # 缺陷数达门槛时，允许在常规上限之外加排 1 轮复检。
        cap = MAX_ROUNDS_PER_SITE_DAY + (1 if threshold_hit else 0)
        next_round = existing + 1

        if next_round > cap:
            reasons.append(
                f"同一站点同一天最多排 {MAX_ROUNDS_PER_SITE_DAY} 轮"
                + ("（缺陷数达门槛时可加排 1 轮复检）" if threshold_hit else "")
            )
        elif next_round > MAX_ROUNDS_PER_SITE_DAY and not is_recheck(values):
            reasons.append(
                f"该站点当日缺陷数已达 {RECHECK_DEFECT_THRESHOLD}，第 {next_round} 轮必须以「复检」类型排期"
            )

    return reasons
