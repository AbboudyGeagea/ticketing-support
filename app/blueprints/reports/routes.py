from datetime import datetime, timedelta
from flask import render_template, request, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.blueprints.reports import bp
from app.models.ticket import Ticket, TicketMessage
from app.models.task import Task, TimeEntry
from app.models.user import User
from app.models.hospital import Hospital
from app.models.csat_feedback import CSATFeedback
from app.extensions import db
from functools import wraps

_SEVERITY_LABELS = {"urgent": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
_SEVERITY_COLORS = {"urgent": "#EF4444", "high": "#F97316", "medium": "#EAB308", "low": "#22C55E"}


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── KPI Reports Dashboard ─────────────────────────────────────────────────────

@bp.route("/")
@login_required
@agent_required
def dashboard():
    days = request.args.get("days", 30, type=int)
    if days not in (7, 30, 90):
        days = 30
    start_date = datetime.utcnow() - timedelta(days=days)

    # Metric 1 — Ticket Volume trend (daily counts over period)
    daily_counts = (
        db.session.query(func.date(Ticket.created_at), func.count(Ticket.id))
        .filter(Ticket.created_at >= start_date)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
        .all()
    )
    chart_dates = [str(r[0]) for r in daily_counts]
    chart_values = [r[1] for r in daily_counts]

    # Total tickets in period
    total_tickets = sum(chart_values)

    # Metric 2 — Average TAT (hours) for tickets closed in period
    avg_tat_raw = (
        db.session.query(
            func.avg(func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600)
        )
        .filter(Ticket.closed_at >= start_date, Ticket.closed_at.isnot(None))
        .scalar()
    )
    avg_tat = round(avg_tat_raw, 1) if avg_tat_raw is not None else None

    # Metric 3 — TAT trend by week (weekly avg TAT in hours)
    weekly_tat = (
        db.session.query(
            func.date_trunc("week", Ticket.closed_at).label("week"),
            func.avg(func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600).label("avg_tat"),
        )
        .filter(Ticket.closed_at >= start_date, Ticket.closed_at.isnot(None))
        .group_by(func.date_trunc("week", Ticket.closed_at))
        .order_by(func.date_trunc("week", Ticket.closed_at))
        .all()
    )
    tat_weeks = [str(r[0])[:10] for r in weekly_tat]
    tat_values = [round(r[1], 1) if r[1] is not None else 0 for r in weekly_tat]

    # Metric 4 — Agent Activity
    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).order_by(User.name).all()

    # One query: resolved tickets per agent
    resolved_rows = (
        db.session.query(Ticket.assigned_to, func.count(Ticket.id))
        .filter(
            Ticket.assigned_to.isnot(None),
            Ticket.status.in_(["resolved", "closed"]),
            Ticket.updated_at >= start_date,
        )
        .group_by(Ticket.assigned_to)
        .all()
    )
    resolved_map = {uid: cnt for uid, cnt in resolved_rows}

    # One query: replies per agent
    replies_rows = (
        db.session.query(TicketMessage.sender_id, func.count(TicketMessage.id))
        .filter(
            TicketMessage.sender_id.isnot(None),
            TicketMessage.is_internal == False,
            TicketMessage.created_at >= start_date,
        )
        .group_by(TicketMessage.sender_id)
        .all()
    )
    replies_map = {uid: cnt for uid, cnt in replies_rows}

    agent_activity = [
        {
            "name": agent.name,
            "resolved": resolved_map.get(agent.id, 0),
            "replies": replies_map.get(agent.id, 0),
        }
        for agent in agents
    ]

    # Metric 5 — By Status (current snapshot)
    status_counts = (
        db.session.query(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
        .all()
    )
    status_data = [{"name": s, "value": c} for s, c in status_counts]

    # KPI: Incident Severity — priority distribution (current snapshot)
    priority_counts = (
        db.session.query(Ticket.priority, func.count(Ticket.id))
        .group_by(Ticket.priority)
        .all()
    )
    incident_severity = [
        {
            "name": _SEVERITY_LABELS.get(p, p.capitalize()),
            "value": c,
            "itemStyle": {"color": _SEVERITY_COLORS.get(p, "#94A3B8")},
        }
        for p, c in priority_counts
    ]

    # KPI: First Response Time — avg hours for tickets with a first response
    avg_frt_raw = (
        db.session.query(
            func.avg(
                func.extract("epoch", Ticket.first_response_at - Ticket.created_at) / 3600
            )
        )
        .filter(
            Ticket.first_response_at.isnot(None),
            Ticket.created_at >= start_date,
        )
        .scalar()
    )
    avg_frt = round(float(avg_frt_raw), 1) if avg_frt_raw is not None else None

    # KPI: Ticket Backlog — open tickets (not resolved/closed)
    ticket_backlog = Ticket.query.filter(
        Ticket.status.notin_(["resolved", "closed"])
    ).count()

    # KPI: Escalation Rate — escalated / all open tickets
    escalated_count = Ticket.query.filter(Ticket.status == "escalated").count()
    escalation_rate = round(escalated_count / ticket_backlog * 100, 1) if ticket_backlog > 0 else 0.0

    # KPI: CSAT — average rating (1–5) from submitted surveys
    csat_raw = (
        db.session.query(func.avg(CSATFeedback.rating))
        .filter(CSATFeedback.rating.isnot(None))
        .scalar()
    )
    csat_score = round(float(csat_raw), 1) if csat_raw is not None else None
    csat_responses = CSATFeedback.query.filter(CSATFeedback.rating.isnot(None)).count()

    # Metric: SLA Breach rate
    _active_statuses = ["new", "assigned", "awaiting_info", "in_progress", "escalated"]
    sla_breached = Ticket.query.filter(
        Ticket.status.in_(_active_statuses),
        Ticket.created_at < datetime.utcnow() - timedelta(hours=24),
    ).count()
    total_open = Ticket.query.filter(
        Ticket.status.in_(_active_statuses)
    ).count()
    breach_rate = round(sla_breached / total_open * 100, 1) if total_open > 0 else 0

    # Metric 8 — Resolution rate (for tickets created in period)
    resolved_count = Ticket.query.filter(
        Ticket.created_at >= start_date,
        Ticket.status.in_(["resolved", "closed"]),
    ).count()
    total_count = Ticket.query.filter(Ticket.created_at >= start_date).count()
    resolution_rate = round(resolved_count / total_count * 100, 1) if total_count > 0 else 0

    # Metric 9 — Tickets by hospital (top 8, in period)
    hosp_counts = (
        db.session.query(Hospital.name, func.count(Ticket.id))
        .join(Ticket, Ticket.hospital_id == Hospital.id)
        .filter(Ticket.created_at >= start_date)
        .group_by(Hospital.name)
        .order_by(func.count(Ticket.id).desc())
        .limit(8)
        .all()
    )
    hosp_names = [r[0] for r in hosp_counts]
    hosp_values = [r[1] for r in hosp_counts]

    # Metric 10 — Tickets by source (in period)
    source_counts = (
        db.session.query(Ticket.source, func.count(Ticket.id))
        .filter(Ticket.created_at >= start_date)
        .group_by(Ticket.source)
        .all()
    )
    source_data = [{"name": s or "unknown", "value": c} for s, c in source_counts]

    return render_template(
        "agent/reports.html",
        days=days,
        total_tickets=total_tickets,
        avg_tat=avg_tat,
        avg_frt=avg_frt,
        ticket_backlog=ticket_backlog,
        escalation_rate=escalation_rate,
        csat_score=csat_score,
        csat_responses=csat_responses,
        breach_rate=breach_rate,
        resolution_rate=resolution_rate,
        chart_dates=chart_dates,
        chart_values=chart_values,
        tat_weeks=tat_weeks,
        tat_values=tat_values,
        agent_activity=agent_activity,
        status_data=status_data,
        incident_severity=incident_severity,
        hosp_names=hosp_names,
        hosp_values=hosp_values,
        source_data=source_data,
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
