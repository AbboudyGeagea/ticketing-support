"""Preventive maintenance (PM) logic shared by the PM blueprint, the agent
dashboard and the reminder task."""
import io
import logging
from datetime import date, datetime, time, timedelta
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


# ── Dates ─────────────────────────────────────────────────────────────────────

def _local_tz():
    try:
        return ZoneInfo(current_app.config.get("LOCAL_TZ_NAME", "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def local_today() -> date:
    return datetime.now(_local_tz()).date()


def month_start(d: date) -> date:
    return d.replace(day=1)


def prev_month_start(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


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
    """Per-hospital PM state for the month containing `today`.

    Returns (rows, hospitals_without_checks). A hospital is "done" once a
    checkup dated this month is submitted, "overdue" when it also missed last
    month, and only appears at all if one of its products has active checks.
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

    this_month, last_month = month_start(today), prev_month_start(today)
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
        if last and last >= this_month:
            state = STATE_DONE
        elif h.id in drafts:
            state = STATE_IN_PROGRESS
        elif last and last < last_month:
            state = STATE_OVERDUE
        else:
            state = STATE_DUE
        rows.append(SimpleNamespace(
            hospital=h, products=products, owner=owners.get(h.id),
            last_date=last, draft=drafts.get(h.id), state=state,
        ))
    return rows, skipped


def open_alert_count():
    return (
        PMResult.query.join(PMCheckup)
        .filter(
            PMCheckup.status == CHECKUP_SUBMITTED,
            PMResult.status == PM_ALERT,
            PMResult.resolved_at.is_(None),
        )
        .count()
    )


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
    alerts = [r for r in checkup.results if r.status == PM_ALERT]
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


# ── Reminders ─────────────────────────────────────────────────────────────────

def due_by_owner(today):
    """{owner: [overview rows not yet done this month]} for hospitals with an active owner."""
    rows, _ = overview(today)
    out = {}
    for row in rows:
        owner = row.owner
        if row.state != STATE_DONE and owner and owner.active and owner.email:
            out.setdefault(owner, []).append(row)
    return out


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
