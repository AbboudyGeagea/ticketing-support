"""Preventive maintenance (PM) logic shared by the PM blueprint, the nav-bar
alert badge and the daily alert task."""
import io
import logging
from datetime import date, datetime, time, timedelta
from time import monotonic
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import contains_eager, joinedload

from app.extensions import db
from app.models.hospital import Hospital
from app.models.pm import (
    PMCheck, PMCheckup, PMResult, PMReading, PMHospitalSettings,
    PM_STATUSES, PM_FLAGGED, PM_ALERT, PM_STATUS_LABELS,
    CHECKUP_DRAFT, CHECKUP_SUBMITTED, FIELD_NUMBER, FIELD_PERCENT,
)

logger = logging.getLogger(__name__)

STATE_DONE = "done"
STATE_IN_PROGRESS = "in_progress"
STATE_DUE = "due"
STATE_OVERDUE = "overdue"

ALERT_OVERDUE = "overdue"
ALERT_DUE_TODAY = "due_today"
ALERT_HEADS_UP = "heads_up"


def interval_days() -> int:
    """A hospital's PM is due this many days after its last submitted checkup."""
    return current_app.config.get("PM_INTERVAL_DAYS", 40)


def warn_days() -> int:
    """How many days before the due date the heads-up goes out."""
    return current_app.config.get("PM_WARN_DAYS", 7)


# ── Dates ─────────────────────────────────────────────────────────────────────

def _local_tz():
    try:
        return ZoneInfo(current_app.config.get("LOCAL_TZ_NAME", "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def local_today() -> date:
    return datetime.now(_local_tz()).date()


def local_end_of_day_utc(d: date) -> datetime:
    """17:00 local time on `d`, as the naive-UTC datetime the app stores."""
    local = datetime.combine(d, time(17, 0), tzinfo=_local_tz())
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


# ── Catalog / plan ────────────────────────────────────────────────────────────

def _active_catalog():
    return (
        PMCheck.query.filter_by(active=True)
        .options(joinedload(PMCheck.products), joinedload(PMCheck.fields))
        .order_by(PMCheck.sort_order, PMCheck.name)
        .all()
    )


def hospital_plan(hospital, catalog=None):
    """[(product, [PMCheck, ...]), ...] for the hospital's active products that have active checks."""
    catalog = _active_catalog() if catalog is None else catalog
    plan = []
    for product in sorted((p for p in hospital.products if p.active), key=lambda p: p.name.lower()):
        checks = [c for c in catalog if any(cp.id == product.id for cp in c.products)]
        if checks:
            plan.append((product, checks))
    return plan


def create_checkup(hospital, check_date, user):
    """Create a draft checkup with one result per (product, check) and one reading per field."""
    checkup = PMCheckup(
        hospital_id=hospital.id, check_date=check_date,
        performed_by=user.id, status=CHECKUP_DRAFT,
    )
    db.session.add(checkup)
    for product, checks in hospital_plan(hospital):
        for c in checks:
            result = PMResult(
                check_id=c.id, product_id=product.id, check_name=c.name,
                check_description=c.description, sort_order=c.sort_order,
            )
            for f in c.fields:
                result.readings.append(PMReading(
                    field_id=f.id, label=f.label, field_type=f.field_type,
                    unit=f.unit, sort_order=f.sort_order,
                ))
            checkup.results.append(result)
    db.session.commit()
    return checkup


def grouped_results(checkup):
    """[(product, [results...]), ...] ordered by product name, then check order."""
    groups = {}
    for r in checkup.results:
        groups.setdefault(r.product_id, []).append(r)
    out = []
    for rs in groups.values():
        rs.sort(key=lambda r: (r.sort_order, r.check_name.lower()))
        out.append((rs[0].product, rs))
    out.sort(key=lambda g: g[0].name.lower())
    return out


# ── History ───────────────────────────────────────────────────────────────────

def previous_results(checkup):
    """{(check_id, product_id): (previous_result, flagged_streak)} from earlier
    submitted checkups of the same hospital. flagged_streak counts how many of
    the most recent previous results in a row were Needs attention / Alert."""
    rows = (
        PMResult.query.join(PMCheckup)
        .filter(
            PMCheckup.hospital_id == checkup.hospital_id,
            PMCheckup.status == CHECKUP_SUBMITTED,
            PMCheckup.id != checkup.id,
            PMCheckup.check_date <= checkup.check_date,
        )
        .options(contains_eager(PMResult.checkup), joinedload(PMResult.readings))
        .order_by(PMCheckup.check_date.desc(), PMCheckup.id.desc())
        .all()
    )
    out = {}
    for r in rows:
        key = (r.check_id, r.product_id)
        entry = out.setdefault(key, {"prev": r, "streak": 0, "open": True})
        if entry["open"]:
            if r.status in PM_FLAGGED:
                entry["streak"] += 1
            else:
                entry["open"] = False
    return {k: (v["prev"], v["streak"]) for k, v in out.items()}


def flagged_streaks(results):
    """{result.id: consecutive flagged results ending at (and including) that result}."""
    results = [r for r in results if r.checkup.status == CHECKUP_SUBMITTED]
    if not results:
        return {}
    keys = {(r.checkup.hospital_id, r.check_id, r.product_id) for r in results}
    rows = (
        db.session.query(PMResult.id, PMCheckup.hospital_id, PMResult.check_id,
                         PMResult.product_id, PMResult.status)
        .join(PMCheckup)
        .filter(
            PMCheckup.status == CHECKUP_SUBMITTED,
            PMCheckup.hospital_id.in_({k[0] for k in keys}),
            PMResult.check_id.in_({k[1] for k in keys}),
        )
        .order_by(PMCheckup.check_date, PMCheckup.id)
        .all()
    )
    streak, out = {}, {}
    for rid, hid, cid, pid, status in rows:
        key = (hid, cid, pid)
        if key not in keys:
            continue
        streak[key] = streak.get(key, 0) + 1 if status in PM_FLAGGED else 0
        out[rid] = streak[key]
    return out


# ── Overview ──────────────────────────────────────────────────────────────────

def overview(today):
    """Per-hospital PM state as of `today`, ordered by hospital name.

    Returns (rows, hospitals_without_checks). A hospital's PM is due
    interval_days() after its last submitted checkup. It is "done" until the
    last warn_days() before that, then "due" ("in_progress" with a draft), and
    "overdue" once the due date has passed — or straight away if it has never
    had a submitted checkup. Only hospitals with a product that has active
    checks appear at all.
    """
    catalog = _active_catalog()
    pm_product_ids = {p.id for c in catalog for p in c.products}
    hospitals = (
        Hospital.query.filter_by(active=True)
        .options(joinedload(Hospital.products))
        .order_by(Hospital.name)
        .all()
    )
    owners = {
        s.hospital_id: s.owner
        for s in PMHospitalSettings.query.options(joinedload(PMHospitalSettings.owner)).all()
    }
    last_submitted = dict(
        db.session.query(PMCheckup.hospital_id, func.max(PMCheckup.check_date))
        .filter(PMCheckup.status == CHECKUP_SUBMITTED, PMCheckup.check_date <= today)
        .group_by(PMCheckup.hospital_id)
        .all()
    )
    drafts = {}
    for d in PMCheckup.query.filter_by(status=CHECKUP_DRAFT).order_by(PMCheckup.updated_at.desc()).all():
        drafts.setdefault(d.hospital_id, d)

    interval, warn = interval_days(), warn_days()
    rows, skipped = [], 0
    for h in hospitals:
        products = sorted(
            (p for p in h.products if p.active and p.id in pm_product_ids),
            key=lambda p: p.name.lower(),
        )
        if not products:
            skipped += 1
            continue
        last = last_submitted.get(h.id)
        due_date = last + timedelta(days=interval) if last else None
        days_left = (due_date - today).days if due_date else None
        if days_left is None or days_left < 0:
            state = STATE_OVERDUE
        elif days_left > warn:
            state = STATE_DONE
        elif h.id in drafts:
            state = STATE_IN_PROGRESS
        else:
            state = STATE_DUE
        rows.append(SimpleNamespace(
            hospital=h, products=products, owner=owners.get(h.id),
            last_date=last, due_date=due_date, days_left=days_left,
            draft=drafts.get(h.id), state=state,
        ))
    return rows, skipped


def by_urgency(rows):
    """Never-done hospitals first, then the most overdue, then the next due."""
    return sorted(rows, key=lambda r: (r.days_left is not None, r.days_left or 0, r.hospital.name.lower()))


def set_owner(hospital_id, owner_id):
    row = db.session.get(PMHospitalSettings, hospital_id)
    if row is None:
        row = PMHospitalSettings(hospital_id=hospital_id)
        db.session.add(row)
    row.owner_id = owner_id or None
    db.session.commit()


# ── Draft editing / submit ────────────────────────────────────────────────────

def apply_form(checkup, form):
    """Copy posted values onto a draft. Returns problems (strings) for readings
    that should be numbers but aren't — the raw text is still kept so nothing
    the engineer typed is lost."""
    problems = []
    raw_date = (form.get("check_date") or "").strip()
    if raw_date:
        try:
            checkup.check_date = date.fromisoformat(raw_date)
        except ValueError:
            problems.append("Checkup date is not a valid date.")
    checkup.notes = (form.get("notes") or "").strip() or None
    for r in checkup.results:
        status = form.get(f"status_{r.id}")
        r.status = status if status in PM_STATUSES else None
        r.comment = (form.get(f"comment_{r.id}") or "").strip() or None
        for rd in r.readings:
            raw = (form.get(f"reading_{rd.id}") or "").strip()
            if raw and rd.field_type in (FIELD_NUMBER, FIELD_PERCENT):
                normalized = raw.replace(",", ".").rstrip("%").strip()
                try:
                    float(normalized)
                    raw = normalized
                except ValueError:
                    problems.append(f"{r.product.name} — {r.check_name}: “{rd.label}” must be a number.")
            rd.value = raw[:500] or None
    return problems


def missing_statuses(checkup):
    return [r for r in checkup.results if r.status not in PM_STATUSES]


def submit_checkup(checkup):
    """Lock a complete draft and email agents if anything is on Alert.
    The caller must have checked missing_statuses() first."""
    checkup.status = CHECKUP_SUBMITTED
    checkup.submitted_at = datetime.utcnow()
    db.session.commit()
    clear_alert_cache()
    alerts =[r for r in checkup.results if r.status == PM_ALERT]
    if alerts:
        try:
            from app.services.email_outbound import notify_agents_pm_alert
            notify_agents_pm_alert(checkup, alerts)
        except Exception:
            logger.exception("PM alert email failed for checkup %s", checkup.id)
    return alerts


# ── Findings ──────────────────────────────────────────────────────────────────

def resolve_result(result, user, note):
    result.resolved_at = datetime.utcnow()
    result.resolved_by = user.id
    result.resolution_note = note or None
    db.session.commit()


def create_followup_task(result, creator, assignee_id, deadline_date, title):
    from app.models.task import Task, TASK_TODO
    from app.services.email_outbound import _base_url

    checkup = result.checkup
    lines = [
        f"PM finding from the {checkup.hospital.name} checkup on {checkup.check_date:%d %b %Y}.",
        f"Product: {result.product.name}",
        f"Check: {result.check_name}",
        f"Status: {result.status_label}",
    ]
    readings = ", ".join(f"{rd.label}: {rd.display}" for rd in result.readings if rd.value)
    if readings:
        lines.append(f"Readings: {readings}")
    if result.comment:
        lines.append(f"Comment: {result.comment}")
    lines.append("")
    lines.append("Completing this task marks the PM finding as resolved.")
    lines.append(f"{_base_url()}/pm/{checkup.id}")

    task = Task(
        title=title[:500],
        description="\n".join(lines),
        hospital_id=checkup.hospital_id,
        product_id=result.product_id,
        created_by=creator.id,
        assigned_to=assignee_id,
        priority="high" if result.status == PM_ALERT else "medium",
        status=TASK_TODO,
        deadline=local_end_of_day_utc(deadline_date) if deadline_date else None,
    )
    db.session.add(task)
    db.session.flush()
    result.task_id = task.id
    db.session.commit()
    return task


def resolve_findings_for_task(task, user):
    """Called when a task is marked done: resolve PM findings it was created for."""
    rows = PMResult.query.filter(PMResult.task_id == task.id, PMResult.resolved_at.is_(None)).all()
    for r in rows:
        r.resolved_at = datetime.utcnow()
        r.resolved_by = user.id
        r.resolution_note = f"Follow-up task completed: {task.title}"
    if rows:
        db.session.commit()
    return len(rows)


# ── Alerts ────────────────────────────────────────────────────────────────────

def alert_kind(row):
    """The alert `row` triggers today, if any: a heads-up exactly warn_days()
    before the due date, one on the due date, then one every day while overdue."""
    if row.days_left is None or row.days_left < 0:
        return ALERT_OVERDUE
    if row.days_left == 0:
        return ALERT_DUE_TODAY
    if row.days_left == warn_days():
        return ALERT_HEADS_UP
    return None


def alert_rows(today):
    """Overview rows that alert today, most urgent first, each with `.alert` set."""
    rows, _ = overview(today)
    out = []
    for row in by_urgency(rows):
        row.alert = alert_kind(row)
        if row.alert:
            out.append(row)
    return out


_alert_cache = {"data": None, "ts": 0.0}


def alert_summary():
    """{"now": hospitals overdue or due today, "soon": due within warn_days()}.
    The nav bar shows this on every agent page, so it is cached for a minute."""
    ts = monotonic()
    if _alert_cache["data"] is not None and ts - _alert_cache["ts"] < 60.0:
        return _alert_cache["data"]
    rows, _ = overview(local_today())
    warn = warn_days()
    data = {
        "now": sum(1 for r in rows if r.days_left is None or r.days_left <= 0),
        "soon": sum(1 for r in rows if r.days_left is not None and 0 < r.days_left <= warn),
    }
    _alert_cache.update(data=data, ts=ts)
    return data


def clear_alert_cache():
    _alert_cache["data"] = None


# ── Excel ─────────────────────────────────────────────────────────────────────

_STATUS_FILLS = {
    "normal": "DCFCE7",
    "attention": "FEF3C7",
    "alert": "FEE2E2",
    "na": "F1F5F9",
}


def _sheet_header(ws, row, headers):
    from openpyxl.styles import Font, PatternFill
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="334155")


def _status_cell(ws, row, col, status):
    from openpyxl.styles import PatternFill
    cell = ws.cell(row=row, column=col, value=PM_STATUS_LABELS.get(status, "Not set"))
    if status in _STATUS_FILLS:
        cell.fill = PatternFill("solid", fgColor=_STATUS_FILLS[status])


def _readings_text(result):
    return "; ".join(f"{rd.label}: {rd.display}" for rd in result.readings if rd.value)


def _resolution_text(result):
    if not result.resolved_at:
        return ""
    who = result.resolver.name if result.resolver else "?"
    text = f"Resolved by {who} on {result.resolved_at:%Y-%m-%d}"
    return f"{text} — {result.resolution_note}" if result.resolution_note else text


def _finish(wb, ws, widths):
    from openpyxl.styles import Alignment
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def checkup_workbook(checkup):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "PM checkup"
    ws["A1"] = f"Preventive maintenance — {checkup.hospital.name}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (
        f"Date: {checkup.check_date:%Y-%m-%d}   ·   Performed by: {checkup.performer.name}   ·   "
        f"Status: {'Submitted' if checkup.status == CHECKUP_SUBMITTED else 'Draft'}"
    )
    if checkup.notes:
        ws["A3"] = f"Notes: {checkup.notes}"
    headers = ["Product", "Check", "Status", "Readings", "Comment", "Resolution"]
    _sheet_header(ws, 5, headers)
    row = 6
    for product, results in grouped_results(checkup):
        for r in results:
            ws.cell(row=row, column=1, value=product.name)
            ws.cell(row=row, column=2, value=r.check_name)
            _status_cell(ws, row, 3, r.status)
            ws.cell(row=row, column=4, value=_readings_text(r))
            ws.cell(row=row, column=5, value=r.comment or "")
            ws.cell(row=row, column=6, value=_resolution_text(r))
            row += 1
    ws.freeze_panes = "A6"
    return _finish(wb, ws, [18, 26, 16, 40, 45, 40])


def findings_workbook(results, streaks):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "PM findings"
    headers = ["Date", "Hospital", "Product", "Check", "Status", "Repeated",
               "Readings", "Comment", "Resolution", "Follow-up task"]
    _sheet_header(ws, 1, headers)
    for i, r in enumerate(results, start=2):
        ws.cell(row=i, column=1, value=r.checkup.check_date.strftime("%Y-%m-%d"))
        ws.cell(row=i, column=2, value=r.checkup.hospital.name)
        ws.cell(row=i, column=3, value=r.product.name)
        ws.cell(row=i, column=4, value=r.check_name)
        _status_cell(ws, i, 5, r.status)
        streak = streaks.get(r.id, 0)
        ws.cell(row=i, column=6, value=f"{streak}x in a row" if streak >= 2 else "")
        ws.cell(row=i, column=7, value=_readings_text(r))
        ws.cell(row=i, column=8, value=r.comment or "")
        ws.cell(row=i, column=9, value=_resolution_text(r))
        ws.cell(row=i, column=10, value=r.task.title if r.task else "")
    ws.freeze_panes = "A2"
    return _finish(wb, ws, [12, 22, 16, 24, 16, 12, 34, 40, 40, 30])
