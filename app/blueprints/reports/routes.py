import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import render_template, request, abort, current_app, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from app.blueprints.reports import bp
from app.models.ticket import ALL_PRIORITIES, PRIORITY_LABELS, STATUS_LABELS, TYPE_LABELS
from app.models.task import TimeEntry
from app.models.user import User
from app.models.hospital import Hospital
from app.models.product import Product
from app.extensions import db
from app.services import text_analytics as ta
from app.services.report_service import (
    ReportBuilder, Filters, parse_range, earliest_ticket_date,
    PRESETS, OUTCOMES, OUTCOME_LABELS, OUTCOME_COLORS,
)
from functools import wraps


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── KPI Reports Dashboard ─────────────────────────────────────────────────────

def _local_tz():
    try:
        return ZoneInfo(current_app.config.get("LOCAL_TZ_NAME", "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def _builder():
    tz = _local_tz()
    today = datetime.now(tz).date()
    rng = parse_range(request.args, today, lambda: earliest_ticket_date(tz))
    return ReportBuilder(rng, Filters.from_args(request.args), tz), today


def _query_args(rb):
    """Current range + filters as URL params (shared by exports and preset links)."""
    args = rb.filters.as_args()
    if rb.rng.preset == "custom":
        args.update(start=rb.rng.start.isoformat(), end=rb.rng.end.isoformat())
    else:
        args["range"] = rb.rng.preset
    return args


@bp.route("/")
@login_required
@agent_required
def dashboard():
    rb, today = _builder()
    prev = None
    if rb.rng.preset != "all":
        prev = ReportBuilder(rb.rng.previous(), rb.filters, rb.tz, now=rb.now)

    agent_choices = (
        User.query.filter(User.role.in_(["agent", "admin"]), User.active == True)  # noqa: E712
        .order_by(User.name).all()
    )
    return render_template(
        "agent/reports.html",
        rng=rb.rng,
        prev_rng=prev.rng if prev else None,
        filters=rb.filters,
        query_args=_query_args(rb),
        today=today,
        presets=PRESETS,
        kpis=rb.kpis,
        deltas=rb.deltas(prev) if prev else {},
        ov=rb.overview,
        agents=rb.agents,
        acc=rb.acceptance,
        cust=rb.customers,
        text=rb.text,
        outcomes=OUTCOMES,
        outcome_colors=OUTCOME_COLORS,
        hospital_choices=Hospital.query.filter_by(active=True).order_by(Hospital.name).all(),
        product_choices=Product.query.filter_by(active=True).order_by(Product.name).all(),
        agent_choices=agent_choices,
        priority_choices=[(p, PRIORITY_LABELS[p]) for p in ALL_PRIORITIES],
        hospital_names=rb.hospital_names,
        agent_names=rb.agent_names,
    )


# ── CSV exports ───────────────────────────────────────────────────────────────

def _cell(v):
    """Neutralise spreadsheet formula injection in free-text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _hrs(td):
    return round(td.total_seconds() / 3600, 2) if td is not None else None


@bp.route("/export/<kind>.csv")
@login_required
@agent_required
def export_csv(kind):
    if kind not in ("tickets", "resolutions", "agents"):
        abort(404)
    rb, _ = _builder()
    fmt = lambda dt: rb.local(dt).strftime("%Y-%m-%d %H:%M") if dt else ""  # noqa: E731
    agent = lambda uid: rb.agent_names.get(uid, "") if uid else ""  # noqa: E731
    hosp = lambda hid: rb.hospital_names.get(hid, "")  # noqa: E731

    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "tickets":
        w.writerow(["Ref", "Created", "Hospital", "Product", "Assignee", "Priority", "Type", "Source",
                    "Status", "First response (h)", "Resolution (h)", "Closed", "SLA breached",
                    "Subject", "Subject words", "Description words", "Language", "Urgent language"])
        frt = rb.first_responses
        for t in rb.created:
            msgs = rb.created_messages.get(t.id, [])
            desc = "" if t.phi_flagged or not msgs else ta.strip_quoted(msgs[0].body or "", is_reply=False)
            subject = "" if t.phi_flagged else t.subject
            w.writerow([_cell(x) for x in (
                t.ref, fmt(t.created_at), hosp(t.hospital_id), rb.product_names.get(t.product_id, ""),
                agent(t.assigned_to), PRIORITY_LABELS.get(t.priority, t.priority),
                TYPE_LABELS.get(t.type, t.type), t.source, STATUS_LABELS.get(t.status, t.status),
                round(frt[t.id][0], 2) if t.id in frt else None,
                round(rb.created_resolution[t.id], 2) if t.id in rb.created_resolution else None,
                fmt(t.closed_at), "yes" if t.sla_breached else "no",
                subject, ta.word_count(subject), ta.word_count(desc),
                ta.detect_language(f"{subject}\n{desc}") if not t.phi_flagged else "",
                "yes" if ta.urgency_hits(f"{subject}\n{desc}") else "no",
            )])
    elif kind == "resolutions":
        w.writerow(["Ref", "Hospital", "Resolved by", "Resolved at", "First resolution", "Outcome",
                    "Customer response (h)", "Waiting so far (h)"])
        for e in rb.resolution_events:
            w.writerow([_cell(x) for x in (
                e.t.ref, hosp(e.t.hospital_id), agent(e.resolver), fmt(e.at),
                "yes" if e.is_first else "no", OUTCOME_LABELS[e.outcome],
                round(e.hours, 2) if e.hours is not None else None,
                round(e.waited, 2) if e.waited is not None else None,
            )])
    else:
        w.writerow(["Agent", "Assigned", "Open now", "Resolved", "Median FRT (h)", "Median TAT (h)",
                    "Avg TAT (h)", "P90 TAT (h)", "Accepted", "Rejected", "Auto-closed", "Closed by agent",
                    "Acceptance %", "Median time to accept (h)", "Median time to reject (h)",
                    "Public replies", "Internal notes", "Avg words / reply", "CSAT", "CSAT responses",
                    "SLA breached", "Hours logged"])
        for a in rb.agents:
            o = a["outcomes"]
            w.writerow([_cell(x) for x in (
                a["name"], a["assigned"], a["open_now"], a["resolved"], a["frt"]["median"],
                a["tat"]["median"], a["tat"]["avg"], a["tat"]["p90"], o["accepted"], o["rejected"],
                o["auto_closed"], o["closed_by_agent"], a["acceptance_rate"], a["accept_median"],
                a["reject_median"], a["replies"], a["notes"], a["avg_reply_words"], a["csat"],
                a["csat_n"], a["sla_breached"], a["hours_logged"],
            )])

    name = f"report-{kind}-{rb.rng.start.isoformat()}_{rb.rng.end.isoformat()}.csv"
    return Response(
        "﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 (Arabic/French) correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ── Time Report ───────────────────────────────────────────────────────────────

@bp.route("/time")
@login_required
@agent_required
def time_report():
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).order_by(User.name).all()

    agent_id_filter = request.args.get("agent_id", 0, type=int)
    start_date_str = request.args.get("start_date", "")
    end_date_str = request.args.get("end_date", "")

    query = (
        db.session.query(TimeEntry)
        .join(TimeEntry.user)
        .join(TimeEntry.task)
        .order_by(TimeEntry.logged_at.desc())
    )

    if agent_id_filter:
        query = query.filter(TimeEntry.logged_by == agent_id_filter)

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            query = query.filter(TimeEntry.logged_at >= start_date)
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            # include the whole end day
            query = query.filter(TimeEntry.logged_at < end_date + timedelta(days=1))
        except ValueError:
            pass

    # Total minutes across all filtered entries (SQL SUM, not in-memory)
    total_minutes_q = db.session.query(func.sum(TimeEntry.minutes)).join(TimeEntry.user).join(TimeEntry.task)
    if agent_id_filter:
        total_minutes_q = total_minutes_q.filter(TimeEntry.logged_by == agent_id_filter)
    if start_date:
        total_minutes_q = total_minutes_q.filter(TimeEntry.logged_at >= start_date)
    if end_date:
        total_minutes_q = total_minutes_q.filter(TimeEntry.logged_at < end_date + timedelta(days=1))
    total_minutes = total_minutes_q.scalar() or 0

    # Paginated detail entries
    page = request.args.get("page", 1, type=int)
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    entries = pagination.items

    # Group current page entries by agent name
    from collections import defaultdict
    by_agent = defaultdict(list)
    for e in entries:
        by_agent[e.user.name].append(e)
    grouped = sorted(by_agent.items(), key=lambda x: x[0])

    return render_template(
        "agent/time_report.html",
        entries=entries,
        grouped=grouped,
        total_minutes=total_minutes,
        pagination=pagination,
        agents=agents,
        filters={
            "agent_id": agent_id_filter,
            "start_date": start_date_str,
            "end_date": end_date_str,
        },
    )
