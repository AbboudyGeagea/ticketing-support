import logging
import os
import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, flash, request, abort, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.blueprints.portal import bp
from app.blueprints.portal.forms import NewTicketForm, ReplyForm
from app.models.ticket import Ticket, TicketMessage, TicketHistory
from app.models.product import Product
from app.extensions import db
from app.services.email_outbound import notify_agents_new_ticket
from functools import wraps

logger = logging.getLogger(__name__)


def customer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_customer:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _visible_tickets(user):
    """Return a base Query of tickets the portal user is allowed to see.

    Rules:
    - User sees only tickets for products they are assigned to.
    - If a SharedInstallation links the user's hospital to other hospitals
      for a given product, tickets from all those hospitals are included.
    - Hospitals with no shared installation: only the user's own hospital.
    """
    from app.models.shared_installation import SharedInstallation

    user_product_ids = [p.id for p in user.products]
    if not user_product_ids:
        return Ticket.query.filter(db.false())

    # Single query for all relevant SharedInstallations instead of one per product
    installations = (
        SharedInstallation.query
        .filter(SharedInstallation.product_id.in_(user_product_ids))
        .filter(SharedInstallation.hospitals.any(id=user.hospital_id))
        .all()
    )
    install_map = {inst.product_id: [h.id for h in inst.hospitals] for inst in installations}

    conditions = []
    for pid in user_product_ids:
        hosp_ids = install_map.get(pid, [user.hospital_id])
        conditions.append(
            db.and_(Ticket.product_id == pid, Ticket.hospital_id.in_(hosp_ids))
        )

    return Ticket.query.filter(db.or_(*conditions))


def _make_ref(ticket_id):
    now = datetime.utcnow()
    return f"TKT-{now.year}{now.month:02d}-{ticket_id:05d}"


@bp.route("/")
@login_required
@customer_required
def dashboard():
    base = _visible_tickets(current_user)
    open_count = base.filter(Ticket.status.notin_(["closed"])).count()
    closed_count = base.filter_by(status="closed").count()
    recent = base.order_by(Ticket.updated_at.desc()).limit(5).all()
    return render_template("portal/dashboard.html", open_count=open_count,
                           closed_count=closed_count, recent=recent)


@bp.route("/tickets")
@login_required
@customer_required
def tickets():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    query = _visible_tickets(current_user)
    if status_filter:
        query = query.filter(Ticket.status == status_filter)
    tickets_page = (
        query
        .options(joinedload(Ticket.product))
        .order_by(Ticket.updated_at.desc())
        .paginate(page=page, per_page=20)
    )
    return render_template("portal/tickets.html", tickets=tickets_page,
                           status_filter=status_filter)


@bp.route("/tickets/new", methods=["GET", "POST"])
@login_required
@customer_required
def ticket_new():
    from app.models.ticket_template import TicketTemplate
    form = NewTicketForm()
    # Only show products assigned to this user (not all hospital products)
    products = sorted([p for p in current_user.products if p.active], key=lambda p: p.name)
    form.product_id.choices = [(0, "— Select product —")] + [(p.id, p.name) for p in products]
    ticket_templates = TicketTemplate.query.filter_by(is_active=True).order_by(
        TicketTemplate.category, TicketTemplate.name
    ).all()

    # Pre-fill from template if ?template_id= provided
    tmpl_id = request.args.get("template_id", type=int)
    if tmpl_id and request.method == "GET":
        tmpl = TicketTemplate.query.get(tmpl_id)
        if tmpl and tmpl.is_active:
            form.subject.data = tmpl.subject
            form.body.data = tmpl.body
            form.priority.data = tmpl.default_priority
            if tmpl.product_id:
                form.product_id.data = tmpl.product_id

    if form.validate_on_submit():
        valid_product_ids = {p.id for p in current_user.products}
        if form.product_id.data not in valid_product_ids:
            form.product_id.errors = ["Please select a valid product."]
            return render_template("portal/ticket_new.html", form=form, ticket_templates=ticket_templates)
        ticket = Ticket(
            ref=uuid.uuid4().hex,  # temp unique value, replaced after flush
            hospital_id=current_user.hospital_id,
            product_id=form.product_id.data,
            created_by=current_user.id,
            subject=form.subject.data,
            priority=form.priority.data,
            status="open",
            source="portal",
        )
        db.session.add(ticket)
        db.session.flush()  # get ID before commit
        ticket.ref = _make_ref(ticket.id)
        ticket.rustdesk_peer_id = form.rustdesk_peer_id.data.strip() if form.rustdesk_peer_id.data else None

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_name=current_user.name,
            sender_email=current_user.email,
            body=form.body.data,
        )
        db.session.add(msg)

        file = request.files.get("attachment")
        if file and file.filename:
            from app.services.file_service import save_attachment
            from app.models.attachment import TicketAttachment
            try:
                stored_name, original_name, mimetype, size = save_attachment(file, ticket.id)
                att = TicketAttachment(
                    ticket_id=ticket.id,
                    message_id=None,
                    uploaded_by=current_user.id,
                    filename=stored_name,
                    original_name=original_name,
                    mimetype=mimetype,
                    size=size,
                )
                db.session.add(att)
            except ValueError as e:
                flash(str(e), "warning")

        try:
            from app.services.auto_assign import apply_auto_assignment
            apply_auto_assignment(ticket)
        except Exception:
            logger.exception("auto_assign failed for portal ticket %s", ticket.ref)

        try:
            from app.services.sla_service import apply_sla
            apply_sla(ticket)
        except Exception:
            logger.exception("sla_apply failed for portal ticket %s", ticket.ref)

        db.session.commit()

        try:
            notify_agents_new_ticket(ticket)
        except Exception:
            logger.exception("notify failed for portal ticket %s", ticket.ref)

        flash(f"Ticket {ticket.ref} submitted successfully.", "success")
        return redirect(url_for("portal.ticket_detail", ref=ticket.ref))

    return render_template("portal/ticket_new.html", form=form, ticket_templates=ticket_templates)


@bp.route("/tickets/<ref>")
@login_required
@customer_required
def ticket_detail(ref):
    ticket = _visible_tickets(current_user).filter(Ticket.ref == ref).first_or_404()
    messages = ticket.messages.filter_by(is_internal=False).all()

    # Batch-load attachments to avoid N+1
    from app.models.attachment import TicketAttachment
    msg_ids = [m.id for m in messages]
    msg_attachments: dict[int, list] = {}
    if msg_ids:
        for att in TicketAttachment.query.filter(TicketAttachment.message_id.in_(msg_ids)).all():
            msg_attachments.setdefault(att.message_id, []).append(att)

    reply_form = ReplyForm()
    return render_template(
        "portal/ticket_detail.html",
        ticket=ticket,
        messages=messages,
        msg_attachments=msg_attachments,
        reply_form=reply_form,
    )


@bp.route("/tickets/<ref>/reply", methods=["POST"])
@login_required
@customer_required
def ticket_reply(ref):
    ticket = _visible_tickets(current_user).filter(Ticket.ref == ref).first_or_404()
    form = ReplyForm()
    if form.validate_on_submit():
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_name=current_user.name,
            sender_email=current_user.email,
            body=form.body.data,
            is_internal=False,
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
            except ValueError as e:
                flash(str(e), "warning")

        if ticket.status in ("resolved", "pending"):
            old_status = ticket.status   # capture first
            ticket.status = "open"
            entry = TicketHistory(
                ticket_id=ticket.id,
                changed_by=current_user.id,
                action="status_change",
                old_value=old_status,
                new_value="open",
            )
            db.session.add(entry)
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Reply sent.", "success")
    return redirect(url_for("portal.ticket_detail", ref=ref))


@bp.route("/tickets/<ref>/confirm")
def ticket_confirm(ref):
    """Handle resolved confirmation link from email. No login required."""
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    from datetime import datetime as dt
    token = request.args.get("token", "")
    action = request.args.get("action", "")  # "close" or "reopen"

    try:
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        ticket_ref = s.loads(token, salt="ticket-confirm", max_age=7 * 24 * 3600)
    except (SignatureExpired, BadSignature):
        flash("This confirmation link has expired or is invalid.", "danger")
        return redirect(url_for("auth.login"))

    ticket = Ticket.query.filter_by(ref=ticket_ref).first_or_404()

    if action == "close" and ticket.status == "resolved":
        old = ticket.status
        ticket.status = "closed"
        ticket.closed_at = dt.utcnow()
        ticket.updated_at = dt.utcnow()
        db.session.add(TicketHistory(ticket_id=ticket.id, changed_by=None,
                                     action="status_change", old_value=old, new_value="closed"))
        db.session.commit()
        flash("Thank you — your ticket has been closed.", "success")
    elif action == "reopen" and ticket.status in ("resolved", "closed"):
        old = ticket.status
        ticket.status = "open"
        ticket.closed_at = None
        ticket.updated_at = dt.utcnow()
        db.session.add(TicketHistory(ticket_id=ticket.id, changed_by=None,
                                     action="status_change", old_value=old, new_value="open"))
        db.session.commit()
        flash("Your ticket has been reopened. Our team will follow up shortly.", "info")
    else:
        flash("Nothing to do — ticket is already in this state.", "info")

    # Redirect to login (customer may not be logged in)
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
@customer_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        new_password_confirm = request.form.get("new_password_confirm", "")
        if name:
            current_user.name = name
        if current_password and new_password:
            if new_password != new_password_confirm:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("portal.profile"))
            if not current_user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("portal.profile"))
            if len(new_password) < 8:
                flash("New password must be at least 8 characters.", "danger")
                return redirect(url_for("portal.profile"))
            current_user.set_password(new_password)
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("portal.profile"))
    return render_template("portal/profile.html")


# ── Knowledge Base ────────────────────────────────────────────────────────────

@bp.route("/kb")
@login_required
@customer_required
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
    return render_template("portal/kb.html", articles=articles, q=q,
                           category=category, categories=categories)


@bp.route("/kb/<int:article_id>")
@login_required
@customer_required
def kb_article(article_id):
    from app.models.kb_article import KBArticle
    article = KBArticle.query.get_or_404(article_id)
    if not article.is_published:
        abort(404)
    article.views += 1
    db.session.commit()
    return render_template("portal/kb_article.html", article=article)


@bp.route("/attachments/<int:att_id>/download")
@login_required
@customer_required
def download_attachment(att_id):
    from app.models.attachment import TicketAttachment
    att = TicketAttachment.query.get_or_404(att_id)
    _visible_tickets(current_user).filter(Ticket.id == att.ticket_id).first_or_404()
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(att.ticket_id))
    return send_from_directory(upload_dir, att.filename, as_attachment=True, download_name=att.original_name)
