import os
import json
import uuid
from datetime import datetime, timedelta, time as dt_time
from urllib.parse import urlparse
from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func, nulls_last
from sqlalchemy.orm import joinedload
from app.blueprints.agent import bp
from app.blueprints.agent.forms import ReplyForm, StatusForm, AssignForm, PriorityForm, TaskForm, NewTicketForm, SprintForm
from app.models.ticket import Ticket, TicketMessage, TicketHistory, ALL_STATUSES, ALL_PRIORITIES
from app.models.task import Task, TaskChecklist, TaskDependency, TimeEntry, Sprint, TASK_TODO, TASK_IN_PROGRESS, TASK_DONE, ALL_TASK_STATUSES
from app.models.product import Product
from app.models.user import User
from app.models.hospital import Hospital
from app.extensions import db
from app.services.email_outbound import notify_customer_reply
from functools import wraps


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _is_safe_url(url: str) -> bool:
    """Return True only for http/https URLs (blocks javascript: and data: schemes)."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https", "")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
@agent_required
def dashboard():
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    # Stat cards
    open_count = Ticket.query.filter(Ticket.status.notin_(["closed", "resolved"])).count()
    my_count = Ticket.query.filter_by(assigned_to=current_user.id).filter(
        Ticket.status.notin_(["closed"])
    ).count()
    overdue_tasks = Task.query.filter_by(assigned_to=current_user.id).filter(
        Task.status != TASK_DONE,
        Task.deadline < now,
    ).count()
    sla_window = now + timedelta(hours=1)
    sla_at_risk = Ticket.query.filter(
        Ticket.status.notin_(["closed", "resolved"]),
        or_(
            and_(
                Ticket.sla_response_due.isnot(None),
                Ticket.sla_response_due > now,
                Ticket.sla_response_due <= sla_window,
                Ticket.first_response_at.is_(None),
            ),
            and_(
                Ticket.sla_resolve_due.isnot(None),
                Ticket.sla_resolve_due > now,
                Ticket.sla_resolve_due <= sla_window,
            ),
        ),
    ).count()
    resolved_today = Ticket.query.filter(
        Ticket.status == "resolved",
        Ticket.updated_at >= now.replace(hour=0, minute=0, second=0),
    ).count()

    # ECharts: ticket volume last 30 days
    daily_counts = (
        db.session.query(func.date(Ticket.created_at), func.count(Ticket.id))
        .filter(Ticket.created_at >= thirty_days_ago)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
        .all()
    )
    chart_dates = [str(r[0]) for r in daily_counts]
    chart_values = [r[1] for r in daily_counts]

    # ECharts: by status
    status_counts = (
        db.session.query(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
        .all()
    )
    status_data = [{"name": s, "value": c} for s, c in status_counts]

    # ECharts: by hospital
    hosp_counts = (
        db.session.query(Hospital.name, func.count(Ticket.id))
        .join(Ticket, Ticket.hospital_id == Hospital.id)
        .filter(Ticket.status.notin_(["closed"]))
        .group_by(Hospital.name)
        .order_by(func.count(Ticket.id).desc())
        .limit(8)
        .all()
    )
    hosp_names = [r[0] for r in hosp_counts]
    hosp_values = [r[1] for r in hosp_counts]

    # Recent tickets
    recent_tickets = (
        Ticket.query
        .filter(Ticket.status.notin_(["closed"]))
        .options(joinedload(Ticket.hospital))
        .order_by(Ticket.updated_at.desc())
        .limit(10)
        .all()
    )

    # Last public message per recent ticket
    dash_last_msg_map = {}
    _rt_ids = [t.id for t in recent_tickets]
    if _rt_ids:
        _subq = (
            db.session.query(TicketMessage.ticket_id, func.max(TicketMessage.id).label("max_id"))
            .filter(TicketMessage.ticket_id.in_(_rt_ids), TicketMessage.is_internal == False)
            .group_by(TicketMessage.ticket_id)
            .subquery()
        )
        for _m in db.session.query(TicketMessage).join(_subq, TicketMessage.id == _subq.c.max_id).all():
            dash_last_msg_map[_m.ticket_id] = _m

    # My tasks
    my_tasks = (
        Task.query.filter_by(assigned_to=current_user.id)
        .filter(Task.status != TASK_DONE)
        .order_by(nulls_last(Task.deadline.asc()), Task.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "agent/dashboard.html",
        open_count=open_count,
        my_count=my_count,
        overdue_tasks=overdue_tasks,
        sla_at_risk=sla_at_risk,
        resolved_today=resolved_today,
        chart_dates=chart_dates,
        chart_values=chart_values,
        status_data=status_data,
        hosp_names=hosp_names,
        hosp_values=hosp_values,
        recent_tickets=recent_tickets,
        dash_last_msg_map=dash_last_msg_map,
        my_tasks=my_tasks,
    )


# ── Ticket List ───────────────────────────────────────────────────────────────

@bp.route("/tickets")
@login_required
@agent_required
def tickets():
    page = request.args.get("page", 1, type=int)
    status_filters = request.args.getlist("status")
    priority_filter = request.args.get("priority", "")
    hospital_filter = request.args.get("hospital_id", 0, type=int)
    assigned_filter = request.args.get("assigned", "")
    search = request.args.get("q", "").strip()

    query = Ticket.query

    if status_filters:
        query = query.filter(Ticket.status.in_(status_filters))
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if hospital_filter:
        query = query.filter_by(hospital_id=hospital_filter)
    if assigned_filter == "me":
        query = query.filter_by(assigned_to=current_user.id)
    elif assigned_filter == "unassigned":
        query = query.filter(Ticket.assigned_to.is_(None))
    if search:
        query = query.filter(
            or_(Ticket.subject.ilike(f"%{search}%"), Ticket.ref.ilike(f"%{search}%"))
        )

    tickets_page = (
        query
        .options(
            joinedload(Ticket.hospital),
            joinedload(Ticket.product),
            joinedload(Ticket.creator),
            joinedload(Ticket.assignee),
        )
        .order_by(Ticket.updated_at.desc())
        .paginate(page=page, per_page=25)
    )

    # Last public message per ticket on this page (one subquery, not N)
    last_msg_map = {}
    _ids = [t.id for t in tickets_page.items]
    if _ids:
        _subq = (
            db.session.query(TicketMessage.ticket_id, func.max(TicketMessage.id).label("max_id"))
            .filter(TicketMessage.ticket_id.in_(_ids), TicketMessage.is_internal == False)
            .group_by(TicketMessage.ticket_id)
            .subquery()
        )
        for _m in db.session.query(TicketMessage).join(_subq, TicketMessage.id == _subq.c.max_id).all():
            last_msg_map[_m.ticket_id] = _m

    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).all()

    from app.models.saved_filter import SavedFilter
    import json as _json
    saved_filters = SavedFilter.query.filter_by(user_id=current_user.id).order_by(SavedFilter.name).all()
    for sf in saved_filters:
        sf.params = _json.loads(sf.filter_params)

    return render_template(
        "agent/tickets.html",
        tickets=tickets_page,
        hospitals=hospitals,
        statuses=ALL_STATUSES,
        priorities=ALL_PRIORITIES,
        filters={
            "status": status_filters,
            "priority": priority_filter,
            "hospital_id": hospital_filter,
            "assigned": assigned_filter,
            "q": search,
        },
        saved_filters=saved_filters,
        last_msg_map=last_msg_map,
    )


# ── Agent creates ticket ──────────────────────────────────────────────────────

@bp.route("/tickets/new", methods=["GET", "POST"])
@login_required
@agent_required
def ticket_new():
    form = NewTicketForm()
    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).all()
    form.hospital_id.choices = [(h.id, h.name) for h in hospitals]

    # Choices populated dynamically; set defaults for validation
    form.customer_id.choices = [(0, "— No reporter —")]
    form.product_id.choices = [(0, "— Select product —")]

    if form.validate_on_submit():
        hospital = Hospital.query.get_or_404(form.hospital_id.data)
        # Re-validate dynamic choices
        valid_customer_ids = {u.id for u in hospital.users.filter_by(role="customer").all()}
        valid_product_ids = {p.id for p in hospital.products}

        customer_id = form.customer_id.data if form.customer_id.data in valid_customer_ids else None
        product_id = form.product_id.data if form.product_id.data in valid_product_ids else None

        if product_id is None:
            form.product_id.errors = ["Please select a product."]
            return render_template("agent/ticket_new.html", form=form, hospitals=hospitals)

        from app.models.ticket import Ticket, TicketMessage
        ticket = Ticket(
            ref=uuid.uuid4().hex[:20],  # temp unique value; sliced to fit VARCHAR(20)
            hospital_id=hospital.id,
            product_id=product_id,
            created_by=customer_id,
            assigned_to=current_user.id,
            subject=form.subject.data,
            priority=form.priority.data,
            status="assigned",
            source="agent",
        )
        db.session.add(ticket)
        db.session.flush()
        ticket.ref = f"{ticket.id:04d}"

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_name=current_user.name,
            sender_email=current_user.email,
            body=form.body.data,
            is_internal=False,
        )
        db.session.add(msg)

        try:
            from app.services.auto_assign import apply_auto_assignment
            apply_auto_assignment(ticket)
        except Exception:
            pass

        try:
            from app.services.sla_service import apply_sla
            apply_sla(ticket)
        except Exception:
            pass

        db.session.commit()

        try:
            from app.services.email_outbound import notify_agents_new_ticket
            notify_agents_new_ticket(ticket)
        except Exception:
            pass

        flash(f"Ticket {ticket.ref} created.", "success")
        return redirect(url_for("agent.ticket_detail", ref=ticket.ref))

    return render_template("agent/ticket_new.html", form=form, hospitals=hospitals)


@bp.route("/api/hospitals/<int:hospital_id>/customers")
@login_required
@agent_required
def api_hospital_customers(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    customers = hospital.users.filter_by(role="customer", active=True).order_by(User.name).all()
    return jsonify([{"id": u.id, "name": u.name, "email": u.email} for u in customers])


@bp.route("/api/hospitals/<int:hospital_id>/products")
@login_required
@agent_required
def api_hospital_products(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    products = [p for p in hospital.products if p.active]
    products.sort(key=lambda p: p.name)
    return jsonify([{"id": p.id, "name": p.name} for p in products])


# ── Ticket Detail ─────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>")
@login_required
@agent_required
def ticket_detail(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    messages = ticket.messages.all()
    history = ticket.history.all()
    tasks = ticket.tasks.order_by(Task.created_at.desc()).all()
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()

    # Batch-load attachments for all messages in a single query to avoid N+1.
    from app.models.attachment import TicketAttachment
    msg_ids = [m.id for m in messages]
    msg_attachments: dict[int, list] = {}
    if msg_ids:
        for att in TicketAttachment.query.filter(TicketAttachment.message_id.in_(msg_ids)).all():
            msg_attachments.setdefault(att.message_id, []).append(att)

    reply_form = ReplyForm()
    status_form = StatusForm(status=ticket.status)
    priority_form = PriorityForm(priority=ticket.priority)
    assign_form = AssignForm()
    assign_form.agent_id.choices = [(0, "— Unassign —")] + [(a.id, a.name) for a in agents]
    assign_form.agent_id.data = ticket.assigned_to or 0

    from app.models.rustdesk_log import RustDeskLog
    rustdesk_logs = ticket.rustdesk_logs.limit(20).all()

    from app.models.ticket import TicketCollaborator
    collaborators = TicketCollaborator.query.filter_by(ticket_id=ticket.id).all()

    return render_template(
        "agent/ticket_detail.html",
        ticket=ticket,
        messages=messages,
        msg_attachments=msg_attachments,
        history=history,
        tasks=tasks,
        agents=agents,
        reply_form=reply_form,
        status_form=status_form,
        priority_form=priority_form,
        assign_form=assign_form,
        rustdesk_logs=rustdesk_logs,
        collaborators=collaborators,
    )


@bp.route("/tickets/<ref>/reply", methods=["POST"])
@login_required
@agent_required
def ticket_reply(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    form = ReplyForm()
    if form.validate_on_submit():
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_name=current_user.name,
            sender_email=current_user.email,
            body=form.body.data,
            is_internal=form.is_internal.data,
        )
        db.session.add(msg)
        db.session.flush()  # get msg.id

        file = request.files.get("attachment")
        if file and file.filename:
            from app.services.file_service import save_attachment
            from app.models.attachment import TicketAttachment
            try:
                stored_name, original_name, mimetype, size = save_attachment(file, ticket.id)
                att = TicketAttachment(
                    ticket_id=ticket.id,
                    message_id=msg.id,
                    uploaded_by=current_user.id,
                    filename=stored_name,
                    original_name=original_name,
                    mimetype=mimetype,
                    size=size,
                )
                db.session.add(att)
            except (ValueError, OSError) as e:
                logger.exception("Attachment save failed for ticket %s", ticket.ref)
                flash("Attachment could not be saved — reply submitted without it.", "warning")

        _log_history(ticket, current_user.id, "reply", None,
                     "internal note" if form.is_internal.data else "public reply")

        ticket.updated_at = datetime.utcnow()
        if ticket.status == "resolved" and not form.is_internal.data:
            ticket.status = "in_progress"

        # Record first agent response for SLA tracking
        if not form.is_internal.data and ticket.first_response_at is None:
            ticket.first_response_at = datetime.utcnow()

        db.session.commit()

        if not form.is_internal.data:
            try:
                notify_customer_reply(ticket, msg)
            except Exception:
                pass
            try:
                from app.services.email_outbound import notify_collaborators_new_message
                notify_collaborators_new_message(ticket, msg)
            except Exception:
                pass

        flash("Reply sent.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/status", methods=["POST"])
@login_required
@agent_required
def ticket_status(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    new_status = request.form.get("status")

    if new_status == "escalated":
        esc_number = request.form.get("escalation_number", "").strip()
        if esc_number:
            ticket.escalation_number = esc_number
        elif not ticket.escalation_number:
            flash("An escalation number is required when setting status to Escalated.", "danger")
            return redirect(url_for("agent.ticket_detail", ref=ref))

    if new_status in ALL_STATUSES and new_status != ticket.status:
        old = ticket.status
        ticket.status = new_status
        ticket.updated_at = datetime.utcnow()
        if new_status == "closed":
            ticket.closed_at = datetime.utcnow()
            ticket.close_requested = False
        elif old == "closed":
            ticket.closed_at = None
        _log_history(ticket, current_user.id, "status_change", old, new_status)
        db.session.commit()
        if ticket.creator:
            try:
                from app.services.email_outbound import notify_customer_status_change, notify_customer_resolved_confirmation
                notify_customer_status_change(ticket)
                if new_status == "resolved":
                    notify_customer_resolved_confirmation(ticket)
            except Exception:
                pass
        flash(f"Status changed to {new_status.replace('_', ' ').title()}.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/priority", methods=["POST"])
@login_required
@agent_required
def ticket_priority(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    new_priority = request.form.get("priority")
    if new_priority in ALL_PRIORITIES and new_priority != ticket.priority:
        old = ticket.priority
        ticket.priority = new_priority
        ticket.updated_at = datetime.utcnow()
        _log_history(ticket, current_user.id, "priority_change", old, new_priority)
        db.session.commit()
        flash(f"Priority changed to {new_priority}.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/assign", methods=["POST"])
@login_required
@agent_required
def ticket_assign(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    agent_id = request.form.get("agent_id", 0, type=int)
    old_assignee = ticket.assigned_to
    ticket.assigned_to = agent_id if agent_id else None
    ticket.updated_at = datetime.utcnow()
    _log_history(ticket, current_user.id, "assigned",
                 str(old_assignee) if old_assignee else "none",
                 str(agent_id) if agent_id else "none")
    # Auto-advance from New → Assigned when an agent is assigned
    if agent_id and ticket.status == "new":
        _log_history(ticket, current_user.id, "status_change", "new", "assigned")
        ticket.status = "assigned"
    db.session.commit()
    if agent_id:
        try:
            from app.services.email_outbound import notify_agent_ticket_assigned
            notify_agent_ticket_assigned(ticket, current_user.id)
        except Exception:
            pass
    flash("Ticket assigned.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/pull", methods=["POST"])
@login_required
@agent_required
def ticket_pull(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    old_assignee = ticket.assigned_to
    ticket.assigned_to = current_user.id
    ticket.updated_at = datetime.utcnow()
    _log_history(ticket, current_user.id, "assigned",
                 str(old_assignee) if old_assignee else "none",
                 str(current_user.id))
    if ticket.status == "new":
        _log_history(ticket, current_user.id, "status_change", "new", "assigned")
        ticket.status = "assigned"
    db.session.commit()
    try:
        from app.services.email_outbound import notify_agent_ticket_assigned
        notify_agent_ticket_assigned(ticket, current_user.id)
    except Exception:
        pass
    flash("Ticket pulled to your queue.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/reopen", methods=["POST"])
@login_required
@agent_required
def ticket_reopen(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    old = ticket.status
    ticket.status = "in_progress"
    ticket.closed_at = None
    ticket.close_requested = False
    ticket.updated_at = datetime.utcnow()
    _log_history(ticket, current_user.id, "status_change", old, "in_progress")
    db.session.commit()
    if ticket.creator:
        try:
            from app.services.email_outbound import notify_customer_status_change
            notify_customer_status_change(ticket)
        except Exception:
            pass
    flash("Ticket reopened.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


# ── Ticket → Task conversion ──────────────────────────────────────────────────

@bp.route("/tickets/<ref>/create-task", methods=["POST"])
@login_required
@agent_required
def ticket_create_task(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    agent_id = request.form.get("agent_id", type=int) or current_user.id
    title = request.form.get("title", ticket.subject).strip() or ticket.subject
    task = Task(
        ticket_id=ticket.id,
        created_by=current_user.id,
        assigned_to=agent_id,
        title=title,
        description=f"Created from ticket {ticket.ref}",
        priority=ticket.priority,
        status=TASK_TODO,
    )
    db.session.add(task)
    db.session.commit()
    flash(f'Task "{task.title}" created and linked to {ticket.ref}.', "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


# ── Tasks ─────────────────────────────────────────────────────────────────────

@bp.route("/tasks")
@login_required
@agent_required
def tasks():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    assigned_filter = request.args.get("assigned", "me")

    query = Task.query
    if assigned_filter == "me":
        query = query.filter_by(assigned_to=current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)

    tasks_page = (
        query
        .options(
            joinedload(Task.assignee),
            joinedload(Task.ticket),
        )
        .order_by(nulls_last(Task.deadline.asc()), Task.created_at.desc())
        .paginate(page=page, per_page=25)
    )
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()

    return render_template("agent/tasks.html", tasks=tasks_page, agents=agents,
                           filters={"status": status_filter, "assigned": assigned_filter})


@bp.route("/tasks/new", methods=["GET", "POST"])
@login_required
@agent_required
def task_new():
    form = TaskForm()
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()
    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).options(joinedload(Hospital.products)).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    hospital_products_map = {h.id: [p.id for p in h.products] for h in hospitals}
    form.assigned_to.choices = [(a.id, a.name) for a in agents]
    form.hospital_id.choices = [(0, "— None —")] + [(h.id, h.name) for h in hospitals]
    form.product_id.choices = [(0, "— None —")] + [(p.id, p.name) for p in products]
    ticket_ref = request.args.get("ticket_ref")
    linked_ticket = Ticket.query.filter_by(ref=ticket_ref).first() if ticket_ref else None

    if request.method == "GET":
        form.assigned_to.data = current_user.id

    if form.validate_on_submit():
        task = Task(
            ticket_id=linked_ticket.id if linked_ticket else None,
            created_by=current_user.id,
            assigned_to=form.assigned_to.data,
            hospital_id=form.hospital_id.data or None,
            product_id=form.product_id.data or None,
            title=form.title.data,
            description=form.description.data,
            priority=form.priority.data,
            status=form.status.data,
            deadline=form.deadline.data,
            reminder_at=form.reminder_at.data,
        )
        db.session.add(task)
        db.session.commit()
        flash("Task created.", "success")
        if linked_ticket:
            return redirect(url_for("agent.ticket_detail", ref=linked_ticket.ref))
        return redirect(url_for("agent.tasks"))

    return render_template("agent/task_form.html", form=form, task=None, linked_ticket=linked_ticket,
                           hospital_products_map=hospital_products_map)


@bp.route("/tasks/<int:task_id>", methods=["GET", "POST"])
@login_required
@agent_required
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()
    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).options(joinedload(Hospital.products)).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    hospital_products_map = {h.id: [p.id for p in h.products] for h in hospitals}
    form = TaskForm(obj=task)
    form.assigned_to.choices = [(a.id, a.name) for a in agents]
    form.hospital_id.choices = [(0, "— None —")] + [(h.id, h.name) for h in hospitals]
    form.product_id.choices = [(0, "— None —")] + [(p.id, p.name) for p in products]

    if form.validate_on_submit():
        task.title = form.title.data
        task.description = form.description.data
        task.assigned_to = form.assigned_to.data
        task.hospital_id = form.hospital_id.data or None
        task.product_id = form.product_id.data or None
        task.priority = form.priority.data
        task.status = form.status.data
        task.deadline = form.deadline.data
        task.reminder_at = form.reminder_at.data
        if form.reminder_at.data:
            task.reminder_sent = False
        try:
            p = int(request.form.get("progress", task.progress or 0))
            task.progress = max(0, min(100, p))
        except (TypeError, ValueError):
            pass
        db.session.commit()
        flash("Task updated.", "success")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    subtasks = task.subtasks.all()
    checklist_items = task.checklists.all()
    time_entries = task.time_entries.order_by(TimeEntry.logged_at.desc()).all()

    # Eager-load depends_on/task to avoid N+1 in the dependencies partial.
    dep_list = (
        TaskDependency.query
        .filter_by(task_id=task_id)
        .options(joinedload(TaskDependency.depends_on))
        .all()
    )
    dependent_list = (
        TaskDependency.query
        .filter_by(depends_on_id=task_id)
        .options(joinedload(TaskDependency.task))
        .all()
    )

    return render_template("agent/task_detail.html", form=form, task=task,
                           linked_ticket=task.ticket, subtasks=subtasks,
                           checklist_items=checklist_items, agents=agents,
                           time_entries=time_entries,
                           dep_list=dep_list, dependent_list=dependent_list,
                           hospital_products_map=hospital_products_map)


@bp.route("/tasks/<int:task_id>/subtasks", methods=["POST"])
@login_required
@agent_required
def task_add_subtask(task_id):
    task = Task.query.get_or_404(task_id)
    title = request.form.get("title", "").strip()
    assigned_to_raw = request.form.get("assigned_to", "")
    if not title:
        flash("Subtask title is required.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))
    try:
        assigned_to = int(assigned_to_raw)
    except (TypeError, ValueError):
        assigned_to = task.assigned_to
    subtask = Task(
        parent_id=task.id,
        ticket_id=task.ticket_id,
        created_by=current_user.id,
        assigned_to=assigned_to,
        title=title,
        status=TASK_TODO,
        priority=task.priority,
    )
    db.session.add(subtask)
    db.session.commit()
    flash("Subtask added.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/subtasks/<int:sub_id>/delete", methods=["POST"])
@login_required
@agent_required
def task_delete_subtask(task_id, sub_id):
    subtask = Task.query.get_or_404(sub_id)
    if subtask.parent_id != task_id:
        abort(404)
    db.session.delete(subtask)
    db.session.commit()
    flash("Subtask deleted.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/checklist", methods=["POST"])
@login_required
@agent_required
def task_add_checklist(task_id):
    task = Task.query.get_or_404(task_id)
    text = request.form.get("text", "").strip()
    if not text:
        flash("Checklist item text is required.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))
    item = TaskChecklist(task_id=task.id, text=text)
    db.session.add(item)
    db.session.commit()
    flash("Checklist item added.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
@agent_required
def task_toggle_checklist(task_id, item_id):
    item = TaskChecklist.query.get_or_404(item_id)
    if item.task_id != task_id:
        abort(404)
    item.is_done = not item.is_done
    db.session.commit()
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/checklist/<int:item_id>/delete", methods=["POST"])
@login_required
@agent_required
def task_delete_checklist(task_id, item_id):
    item = TaskChecklist.query.get_or_404(item_id)
    if item.task_id != task_id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash("Checklist item deleted.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/progress", methods=["POST"])
@login_required
@agent_required
def task_update_progress(task_id):
    task = Task.query.get_or_404(task_id)
    try:
        p = int(request.form.get("progress", 0))
        task.progress = max(0, min(100, p))
    except (TypeError, ValueError):
        flash("Invalid progress value.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))
    db.session.commit()
    flash("Progress updated.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


# ── Time Entries ──────────────────────────────────────────────────────────────

@bp.route("/tasks/<int:task_id>/time", methods=["POST"])
@login_required
@agent_required
def task_log_time(task_id):
    task = Task.query.get_or_404(task_id)
    hours = request.form.get("hours", 0, type=int)
    minutes = request.form.get("minutes", 0, type=int)
    note = request.form.get("note", "").strip() or None
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        flash("Please enter a time greater than 0.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))
    entry = TimeEntry(
        task_id=task.id,
        logged_by=current_user.id,
        minutes=total_minutes,
        note=note,
    )
    db.session.add(entry)
    db.session.commit()
    flash(f"Logged {hours}h {minutes}m on this task.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/time/<int:entry_id>/delete", methods=["POST"])
@login_required
@agent_required
def task_delete_time(task_id, entry_id):
    task = Task.query.get_or_404(task_id)
    entry = TimeEntry.query.get_or_404(entry_id)
    if entry.task_id != task.id:
        abort(404)
    db.session.delete(entry)
    db.session.commit()
    flash("Time entry deleted.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


# ── Attachments ───────────────────────────────────────────────────────────────

@bp.route("/attachments/<int:att_id>/download")
@login_required
@agent_required
def download_attachment(att_id):
    from app.models.attachment import TicketAttachment
    att = TicketAttachment.query.get_or_404(att_id)
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(att.ticket_id))
    return send_from_directory(upload_dir, att.filename, as_attachment=True, download_name=att.original_name)


# ── Bulk Actions ──────────────────────────────────────────────────────────────

@bp.route("/tickets/bulk", methods=["POST"])
@login_required
@agent_required
def ticket_bulk():
    """Bulk action on selected tickets: assign_me, close, resolve, set_status."""
    ticket_ids = request.form.getlist("ticket_ids", type=int)
    action = request.form.get("action", "")
    if not ticket_ids:
        flash("No tickets selected.", "warning")
        return redirect(url_for("agent.tickets"))

    tickets = Ticket.query.filter(Ticket.id.in_(ticket_ids)).all()
    count = len(tickets)

    for ticket in tickets:
        if action == "assign_me":
            ticket.assigned_to = current_user.id
            _log_history(ticket, current_user.id, "assigned", str(ticket.assigned_to or "none"), str(current_user.id))
            if ticket.status == "new":
                _log_history(ticket, current_user.id, "status_change", "new", "assigned")
                ticket.status = "assigned"
        elif action in ("close", "resolve", "new", "assigned", "awaiting_info", "in_progress", "escalated"):
            status_map = {
                "close": "closed", "resolve": "resolved",
                "new": "new", "assigned": "assigned",
                "awaiting_info": "awaiting_info", "in_progress": "in_progress",
                "escalated": "escalated",
            }
            new_status = status_map.get(action, action)
            if new_status != ticket.status:
                old = ticket.status
                ticket.status = new_status
                if new_status == "closed":
                    from datetime import datetime as _dt
                    ticket.closed_at = _dt.utcnow()
                    ticket.close_requested = False
                _log_history(ticket, current_user.id, "status_change", old, new_status)
        ticket.updated_at = datetime.utcnow()

    db.session.commit()
    flash(f"Updated {count} ticket(s).", "success")
    return redirect(url_for("agent.tickets"))


# ── Merge ─────────────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/merge", methods=["POST"])
@login_required
@agent_required
def ticket_merge(ref):
    """Merge this ticket into another. Moves all messages to target, closes source."""
    from app.models.ticket import TicketMessage
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    target_ref = request.form.get("merge_into_ref", "").strip().upper()
    if not target_ref or target_ref == ref:
        flash("Invalid target ticket reference.", "danger")
        return redirect(url_for("agent.ticket_detail", ref=ref))

    target = Ticket.query.filter_by(ref=target_ref).first()
    if not target:
        flash(f"Ticket {target_ref} not found.", "danger")
        return redirect(url_for("agent.ticket_detail", ref=ref))

    # Move messages and attachments
    TicketMessage.query.filter_by(ticket_id=ticket.id).update({"ticket_id": target.id})
    from app.models.attachment import TicketAttachment
    TicketAttachment.query.filter_by(ticket_id=ticket.id).update({"ticket_id": target.id})

    # Move physical files from source upload directory to target
    import shutil
    upload_root = current_app.config["UPLOAD_FOLDER"]
    src_dir = os.path.join(upload_root, str(ticket.id))
    tgt_dir = os.path.join(upload_root, str(target.id))
    if os.path.isdir(src_dir):
        os.makedirs(tgt_dir, exist_ok=True)
        for fname in os.listdir(src_dir):
            src_file = os.path.join(src_dir, fname)
            tgt_file = os.path.join(tgt_dir, fname)
            if not os.path.exists(tgt_file):
                shutil.move(src_file, tgt_file)

    # Close source with merge note
    old = ticket.status
    ticket.status = "closed"
    ticket.closed_at = datetime.utcnow()
    _log_history(ticket, current_user.id, "merged", old, f"→ {target_ref}")
    _log_history(target, current_user.id, "merged_from", None, ref)

    db.session.commit()
    flash(f"Ticket {ref} merged into {target_ref}.", "success")
    return redirect(url_for("agent.ticket_detail", ref=target_ref))


# ── Print ─────────────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/print")
@login_required
@agent_required
def ticket_print(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    messages = ticket.messages.all()
    return render_template("agent/ticket_print.html", ticket=ticket, messages=messages, now=datetime.utcnow())


# ── RustDesk ──────────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/rustdesk", methods=["POST"])
@login_required
@agent_required
def ticket_rustdesk(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    peer_id = request.form.get("rustdesk_peer_id", "").strip()
    ticket.rustdesk_peer_id = peer_id or None
    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    flash("RustDesk Device ID updated.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/rustdesk/log", methods=["POST"])
@login_required
@agent_required
def ticket_rustdesk_log(ref):
    from app.models.rustdesk_log import RustDeskLog
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    log = RustDeskLog(
        ticket_id=ticket.id,
        agent_id=current_user.id,
        peer_id=ticket.rustdesk_peer_id,
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True})


# ── Escalation ────────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/escalation", methods=["POST"])
@login_required
@agent_required
def ticket_escalation(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    url = request.form.get("escalation_url", "").strip() or None
    if url and not _is_safe_url(url):
        flash("Invalid escalation URL — only http:// and https:// URLs are allowed.", "danger")
        return redirect(url_for("agent.ticket_detail", ref=ref))
    ticket.escalation_url = url
    ticket.escalation_number = request.form.get("escalation_number", "").strip() or None
    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Escalation details updated.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


# ── Close Request ─────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/close-request/approve", methods=["POST"])
@login_required
@agent_required
def ticket_approve_close(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    if ticket.close_requested:
        old = ticket.status
        ticket.status = "closed"
        ticket.closed_at = datetime.utcnow()
        ticket.close_requested = False
        ticket.updated_at = datetime.utcnow()
        _log_history(ticket, current_user.id, "status_change", old, "closed")
        db.session.commit()
        if ticket.creator:
            try:
                from app.services.email_outbound import notify_customer_status_change
                notify_customer_status_change(ticket)
            except Exception:
                pass
        flash("Customer close request approved — ticket closed.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/close-request/deny", methods=["POST"])
@login_required
@agent_required
def ticket_deny_close(ref):
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    ticket.close_requested = False
    ticket.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Close request dismissed.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


# ── Collaborators ─────────────────────────────────────────────────────────────

@bp.route("/tickets/<ref>/collaborators/add", methods=["POST"])
@login_required
@agent_required
def ticket_add_collaborator(ref):
    from app.models.ticket import TicketCollaborator
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    email = request.form.get("email", "").strip().lower()
    name = request.form.get("name", "").strip()
    if not email:
        flash("Email is required.", "danger")
        return redirect(url_for("agent.ticket_detail", ref=ref))
    if TicketCollaborator.query.filter_by(ticket_id=ticket.id, email=email).first():
        flash(f"{email} is already a collaborator.", "warning")
        return redirect(url_for("agent.ticket_detail", ref=ref))
    collab_type = request.form.get("collab_type", "customer")
    if collab_type not in ("customer", "vendor"):
        collab_type = "customer"
    collab = TicketCollaborator(
        ticket_id=ticket.id,
        email=email,
        name=name or None,
        added_by=current_user.id,
        collab_type=collab_type,
    )
    db.session.add(collab)
    db.session.commit()
    try:
        from app.services.email_outbound import notify_collaborator_added
        notify_collaborator_added(ticket, collab)
    except Exception:
        logger.exception("Failed to notify collaborator %s on ticket %s", email, ref)
    flash(f"{email} added as a {collab_type} collaborator.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/collaborators/<int:collab_id>/remove", methods=["POST"])
@login_required
@agent_required
def ticket_remove_collaborator(ref, collab_id):
    from app.models.ticket import TicketCollaborator
    ticket = Ticket.query.filter_by(ref=ref).first_or_404()
    collab = TicketCollaborator.query.filter_by(id=collab_id, ticket_id=ticket.id).first_or_404()
    db.session.delete(collab)
    db.session.commit()
    flash("Collaborator removed.", "success")
    return redirect(url_for("agent.ticket_detail", ref=ref))


# ── Availability ──────────────────────────────────────────────────────────────

@bp.route("/availability", methods=["POST"])
@login_required
@agent_required
def toggle_availability():
    current_user.is_available = not current_user.is_available
    db.session.commit()
    status = "available" if current_user.is_available else "away"
    flash(f"You are now marked as {status}.", "info")
    return redirect(request.referrer or url_for("agent.dashboard"))


# ── Knowledge Base ────────────────────────────────────────────────────────────

@bp.route("/kb")
@login_required
@agent_required
def kb_list():
    from app.models.kb_article import KBArticle
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    query = KBArticle.query.filter_by(is_published=True)
    if q:
        query = query.filter(
            db.or_(KBArticle.title.ilike(f"%{q}%"), KBArticle.body.ilike(f"%{q}%"))
        )
    if category:
        query = query.filter_by(category=category)
    articles = query.order_by(KBArticle.category, KBArticle.title).all()
    categories = db.session.query(KBArticle.category).filter(
        KBArticle.is_published == True, KBArticle.category.isnot(None)
    ).distinct().order_by(KBArticle.category).all()
    categories = [c[0] for c in categories]
    return render_template("agent/kb.html", articles=articles, q=q,
                           category=category, categories=categories)


@bp.route("/kb/<int:article_id>")
@login_required
@agent_required
def kb_article(article_id):
    from app.models.kb_article import KBArticle
    article = KBArticle.query.get_or_404(article_id)
    if not article.is_published and not current_user.is_admin:
        abort(404)
    article.views += 1
    from app.extensions import db as _db
    _db.session.commit()
    return render_template("agent/kb_article.html", article=article)


@bp.route("/kb/search")
@login_required
@agent_required
def kb_search_json():
    """JSON endpoint for inserting KB articles into ticket replies."""
    from app.models.kb_article import KBArticle
    q = request.args.get("q", "").strip()
    results = KBArticle.query.filter_by(is_published=True).filter(
        db.or_(KBArticle.title.ilike(f"%{q}%"), KBArticle.body.ilike(f"%{q}%"))
    ).order_by(KBArticle.title).limit(10).all()
    return jsonify([{"id": a.id, "title": a.title, "url": url_for("agent.kb_article", article_id=a.id)} for a in results])


# ── CSV Export ────────────────────────────────────────────────────────────────

@bp.route("/tickets/export")
@login_required
@agent_required
def tickets_export():
    import csv
    import io
    from flask import Response, stream_with_context

    status_filters = request.args.getlist("status")
    priority_filter = request.args.get("priority", "")
    hospital_filter = request.args.get("hospital_id", 0, type=int)
    assigned_filter = request.args.get("assigned", "")
    search = request.args.get("q", "").strip()

    query = Ticket.query
    if status_filters:
        query = query.filter(Ticket.status.in_(status_filters))
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if hospital_filter:
        query = query.filter_by(hospital_id=hospital_filter)
    if assigned_filter == "me":
        query = query.filter_by(assigned_to=current_user.id)
    elif assigned_filter == "unassigned":
        query = query.filter(Ticket.assigned_to.is_(None))
    if search:
        query = query.filter(
            db.or_(Ticket.subject.ilike(f"%{search}%"), Ticket.ref.ilike(f"%{search}%"))
        )
    query = query.order_by(Ticket.updated_at.desc())

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Ref", "Subject", "Hospital", "Product", "Status", "Priority",
                         "Assigned To", "Created", "Updated", "SLA Breached"])
        yield buf.getvalue()
        for t in query.yield_per(200):
            buf.seek(0)
            buf.truncate()
            writer.writerow([
                t.ref, t.subject,
                t.hospital.name if t.hospital else "",
                t.product.name if t.product else "",
                t.status, t.priority,
                t.assignee.name if t.assignee else "",
                t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
                t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "",
                "Yes" if t.sla_breached else "No",
            ])
            yield buf.getvalue()

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets.csv"},
    )


# ── Canned Responses ──────────────────────────────────────────────────────────

@bp.route("/canned-responses")
@login_required
@agent_required
def canned_responses_list():
    """Return canned responses as JSON for the reply form dropdown."""
    from app.models.canned_response import CannedResponse
    items = CannedResponse.query.filter(
        db.or_(CannedResponse.is_shared == True, CannedResponse.created_by == current_user.id)
    ).order_by(CannedResponse.title).all()
    return jsonify([{"id": r.id, "title": r.title, "body": r.body} for r in items])


# ── Saved Filters ─────────────────────────────────────────────────────────────

@bp.route("/saved-filters", methods=["POST"])
@login_required
@agent_required
def save_filter():
    """Save current filter params as a named view."""
    from app.models.saved_filter import SavedFilter
    name = request.form.get("filter_name", "").strip()
    params = {}
    statuses = request.form.getlist("status")
    if statuses:
        params["status"] = statuses
    for k in ("priority", "hospital_id", "assigned", "q"):
        v = request.form.get(k, "")
        if v:
            params[k] = v
    if not name:
        flash("Please enter a name for this filter.", "warning")
        return redirect(url_for("agent.tickets", **params))
    sf = SavedFilter(user_id=current_user.id, name=name, filter_params=json.dumps(params))
    db.session.add(sf)
    db.session.commit()
    flash(f'Filter "{name}" saved.', "success")
    return redirect(url_for("agent.tickets", **params))


@bp.route("/saved-filters/<int:filter_id>/delete", methods=["POST"])
@login_required
@agent_required
def delete_saved_filter(filter_id):
    from app.models.saved_filter import SavedFilter
    sf = SavedFilter.query.get_or_404(filter_id)
    if sf.user_id != current_user.id:
        abort(403)
    db.session.delete(sf)
    db.session.commit()
    flash("Filter deleted.", "success")
    return redirect(url_for("agent.tickets"))


# ── Sprints ───────────────────────────────────────────────────────────────────

@bp.route("/sprints")
@login_required
@agent_required
def sprints():
    all_sprints = Sprint.query.order_by(Sprint.start_date.desc()).all()
    sprint_ids = [s.id for s in all_sprints]
    if sprint_ids:
        task_rows = (
            db.session.query(
                Task.sprint_id,
                func.count(Task.id).label("total"),
                func.sum(db.case((Task.status == TASK_DONE, 1), else_=0)).label("done"),
            )
            .filter(Task.sprint_id.in_(sprint_ids))
            .group_by(Task.sprint_id)
            .all()
        )
        sprint_task_stats = {r.sprint_id: (r.total, r.done or 0) for r in task_rows}
    else:
        sprint_task_stats = {}
    return render_template("agent/sprints.html", sprints=all_sprints, sprint_task_stats=sprint_task_stats)


@bp.route("/sprints/new", methods=["GET", "POST"])
@login_required
@agent_required
def sprint_new():
    form = SprintForm()
    if form.validate_on_submit():
        sprint = Sprint(
            name=form.name.data,
            goal=form.goal.data or None,
            start_date=datetime.combine(form.start_date.data, dt_time.min),
            end_date=datetime.combine(form.end_date.data, dt_time.min),
            status=form.status.data,
            created_by=current_user.id,
        )
        db.session.add(sprint)
        db.session.commit()
        flash(f'Sprint "{sprint.name}" created.', "success")
        return redirect(url_for("agent.sprint_detail", sprint_id=sprint.id))
    return render_template("agent/sprint_form.html", form=form, sprint=None)


@bp.route("/sprints/<int:sprint_id>/edit", methods=["GET", "POST"])
@login_required
@agent_required
def sprint_edit(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    form = SprintForm(obj=sprint)
    # DateField expects date objects; convert datetime -> date for pre-population
    if request.method == "GET":
        form.start_date.data = sprint.start_date.date() if sprint.start_date else None
        form.end_date.data = sprint.end_date.date() if sprint.end_date else None
    if form.validate_on_submit():
        sprint.name = form.name.data
        sprint.goal = form.goal.data or None
        sprint.start_date = datetime.combine(form.start_date.data, dt_time.min)
        sprint.end_date = datetime.combine(form.end_date.data, dt_time.min)
        sprint.status = form.status.data
        db.session.commit()
        flash(f'Sprint "{sprint.name}" updated.', "success")
        return redirect(url_for("agent.sprint_detail", sprint_id=sprint.id))
    return render_template("agent/sprint_form.html", form=form, sprint=sprint)


@bp.route("/sprints/<int:sprint_id>/delete", methods=["POST"])
@login_required
@agent_required
def sprint_delete(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    # Detach tasks before deleting
    Task.query.filter_by(sprint_id=sprint.id).update({"sprint_id": None})
    name = sprint.name
    db.session.delete(sprint)
    db.session.commit()
    flash(f'Sprint "{name}" deleted.', "success")
    return redirect(url_for("agent.sprints"))


@bp.route("/sprints/<int:sprint_id>")
@login_required
@agent_required
def sprint_detail(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    tasks = sprint.tasks.order_by(Task.created_at.desc()).all()
    total = len(tasks)
    done_count = sum(1 for t in tasks if t.status == TASK_DONE)
    progress_pct = int((done_count / total) * 100) if total else 0
    # Tasks not yet in this sprint (for adding)
    available_tasks = Task.query.filter(
        Task.sprint_id.is_(None),
        Task.status != TASK_DONE,
    ).order_by(Task.created_at.desc()).limit(100).all()
    return render_template(
        "agent/sprint_detail.html",
        sprint=sprint,
        tasks=tasks,
        total=total,
        done_count=done_count,
        progress_pct=progress_pct,
        available_tasks=available_tasks,
    )


@bp.route("/sprints/<int:sprint_id>/add-task/<int:task_id>", methods=["POST"])
@login_required
@agent_required
def sprint_add_task(sprint_id, task_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    task = Task.query.get_or_404(task_id)
    if task.sprint_id and task.sprint_id != sprint.id:
        other = Sprint.query.get(task.sprint_id)
        flash(f'Task "{task.title}" is already in sprint "{other.name if other else task.sprint_id}". Remove it first.', "warning")
        return redirect(url_for("agent.sprint_detail", sprint_id=sprint_id))
    task.sprint_id = sprint.id
    db.session.commit()
    flash(f'Task "{task.title}" added to sprint.', "success")
    return redirect(url_for("agent.sprint_detail", sprint_id=sprint_id))


@bp.route("/sprints/<int:sprint_id>/remove-task/<int:task_id>", methods=["POST"])
@login_required
@agent_required
def sprint_remove_task(sprint_id, task_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    task = Task.query.get_or_404(task_id)
    if task.sprint_id == sprint.id:
        task.sprint_id = None
        db.session.commit()
        flash(f'Task "{task.title}" removed from sprint.', "success")
    return redirect(url_for("agent.sprint_detail", sprint_id=sprint_id))


# ── Task Dependencies ─────────────────────────────────────────────────────────

def _has_circular_dependency(task_id, depends_on_id):
    """Return True if adding task_id -> depends_on_id would create a cycle."""
    visited = set()
    stack = [depends_on_id]
    while stack:
        current = stack.pop()
        if current == task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        # Find all tasks that `current` depends on
        deps = TaskDependency.query.filter_by(task_id=current).all()
        for d in deps:
            stack.append(d.depends_on_id)
    return False


@bp.route("/tasks/<int:task_id>/dependencies", methods=["POST"])
@login_required
@agent_required
def task_add_dependency(task_id):
    task = Task.query.get_or_404(task_id)
    depends_on_id = request.form.get("depends_on_id", type=int)

    if not depends_on_id:
        flash("Please enter a valid task ID.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    if depends_on_id == task_id:
        flash("A task cannot depend on itself.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    depends_on_task = Task.query.get(depends_on_id)
    if not depends_on_task:
        flash(f"Task #{depends_on_id} not found.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    # Check duplicate
    existing = TaskDependency.query.filter_by(task_id=task_id, depends_on_id=depends_on_id).first()
    if existing:
        flash("This dependency already exists.", "warning")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    # Check for circular dependency
    if _has_circular_dependency(task_id, depends_on_id):
        flash("Cannot add this dependency — it would create a circular chain.", "danger")
        return redirect(url_for("agent.task_detail", task_id=task_id))

    dep = TaskDependency(task_id=task_id, depends_on_id=depends_on_id)
    db.session.add(dep)
    db.session.commit()
    flash(f'Dependency on task #{depends_on_id} "{depends_on_task.title}" added.', "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


@bp.route("/tasks/<int:task_id>/dependencies/<int:dep_id>/delete", methods=["POST"])
@login_required
@agent_required
def task_delete_dependency(task_id, dep_id):
    Task.query.get_or_404(task_id)
    dep = TaskDependency.query.get_or_404(dep_id)
    if dep.task_id != task_id:
        abort(404)
    db.session.delete(dep)
    db.session.commit()
    flash("Dependency removed.", "success")
    return redirect(url_for("agent.task_detail", task_id=task_id))


# ── Workload ──────────────────────────────────────────────────────────────────

@bp.route("/workload")
@login_required
@agent_required
def workload():
    from app.models.project import ProjectTask

    week_offset = request.args.get("week", 0, type=int)
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    week_start_dt = datetime.combine(week_start, dt_time.min)
    week_end_dt = datetime.combine(week_end, dt_time.max)

    agents = User.query.filter(
        User.role.in_(["agent", "admin"]),
        User.active == True,
    ).order_by(User.name).all()

    agent_ids = [a.id for a in agents]

    # Tasks with deadline in the selected week, not done
    week_tasks = Task.query.filter(
        Task.status != TASK_DONE,
        Task.deadline >= week_start_dt,
        Task.deadline <= week_end_dt,
    ).all()

    tasks_by_agent = {a.id: [] for a in agents}
    for task in week_tasks:
        if task.assigned_to in tasks_by_agent:
            tasks_by_agent[task.assigned_to].append(task)

    # Open tickets per agent (not closed / resolved)
    ticket_counts = dict(
        db.session.query(Ticket.assigned_to, func.count(Ticket.id))
        .filter(Ticket.assigned_to.in_(agent_ids), Ticket.status.notin_(["closed", "resolved"]))
        .group_by(Ticket.assigned_to)
        .all()
    )

    # Open ticket-tasks per agent (not done)
    open_task_counts = dict(
        db.session.query(Task.assigned_to, func.count(Task.id))
        .filter(Task.assigned_to.in_(agent_ids), Task.status != TASK_DONE)
        .group_by(Task.assigned_to)
        .all()
    )

    # Active projects per agent (distinct projects with a non-done ProjectTask assigned to them)
    project_counts = dict(
        db.session.query(ProjectTask.assigned_to, func.count(func.distinct(ProjectTask.project_id)))
        .filter(ProjectTask.assigned_to.in_(agent_ids), ProjectTask.status != "done")
        .group_by(ProjectTask.assigned_to)
        .all()
    )

    return render_template(
        "agent/workload.html",
        agents=agents,
        tasks_by_agent=tasks_by_agent,
        week_start=week_start,
        week_end=week_end,
        week_offset=week_offset,
        ticket_counts=ticket_counts,
        open_task_counts=open_task_counts,
        project_counts=project_counts,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_history(ticket, changed_by_id, action, old_value, new_value):
    entry = TicketHistory(
        ticket_id=ticket.id,
        changed_by=changed_by_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
    )
    db.session.add(entry)
