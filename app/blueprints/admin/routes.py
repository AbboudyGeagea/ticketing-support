from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from app.blueprints.admin import bp
from app.blueprints.admin.forms import (
    HospitalForm, ProductForm, CustomerUserForm, AgentForm, EditUserForm, ResetPasswordForm,
    CannedResponseForm, AssignmentRuleForm, WebhookConfigForm, ProjectTemplateForm,
    KBArticleForm, TicketTemplateForm, SLAPolicyForm, SharedInstallationForm, TicketStatusForm, NewTicketStatusForm,
    CredentialForm,
)
from app.models.hospital import Hospital, HospitalCredential
from app.utils.crypto import encrypt, decrypt
from app.models.product import Product
from app.models.user import User
from app.models.ticket import Ticket
from app.models.task import Task
from app.models.canned_response import CannedResponse
from app.models.assignment_rule import AssignmentRule
from app.models.webhook_config import WebhookConfig, WEBHOOK_EVENTS
from app.models.project import ProjectTemplate, ProjectTemplateTask
from app.models.kb_article import KBArticle
from app.models.ticket_template import TicketTemplate
from app.models.sla_policy import SLAPolicy
from app.models.shared_installation import SharedInstallation
from app.models.ticket_status import TicketStatus
from app.extensions import db, csrf
from functools import wraps


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
@admin_required
def dashboard():
    stats = {
        "hospitals": Hospital.query.filter_by(active=True).count(),
        "agents": User.query.filter(User.role.in_(["agent", "admin"])).count(),
        "customers": User.query.filter_by(role="customer").count(),
        "open_tickets": Ticket.query.filter(Ticket.status.notin_(["closed"])).count(),
    }
    return render_template("admin/dashboard.html", stats=stats)


# ── Hospitals ────────────────────────────────────────────────────────────────

@bp.route("/hospitals")
@login_required
@admin_required
def hospitals():
    from app.models.product import hospital_products
    all_hospitals = Hospital.query.order_by(Hospital.name).all()
    hospital_ids = [h.id for h in all_hospitals]

    user_rows = (
        db.session.query(User.hospital_id, func.count(User.id))
        .filter(User.hospital_id.in_(hospital_ids))
        .group_by(User.hospital_id)
        .all()
    ) if hospital_ids else []
    user_counts = {uid: cnt for uid, cnt in user_rows}

    prod_rows = (
        db.session.query(hospital_products.c.hospital_id, func.count(hospital_products.c.product_id))
        .filter(hospital_products.c.hospital_id.in_(hospital_ids))
        .group_by(hospital_products.c.hospital_id)
        .all()
    ) if hospital_ids else []
    product_counts = {hid: cnt for hid, cnt in prod_rows}

    return render_template("admin/hospitals.html", hospitals=all_hospitals,
                           user_counts=user_counts, product_counts=product_counts)


@bp.route("/hospitals/new", methods=["GET", "POST"])
@login_required
@admin_required
def hospital_new():
    form = HospitalForm()
    if form.validate_on_submit():
        h = Hospital(
            name=form.name.data,
            email_domain=form.email_domain.data.lower().strip() if form.email_domain.data else None,
            address=form.address.data,
            phone=form.phone.data,
            rustdesk_server_url=form.rustdesk_server_url.data.strip() if form.rustdesk_server_url.data else None,
            rustdesk_server_key=form.rustdesk_server_key.data.strip() if form.rustdesk_server_key.data else None,
            rustdesk_id=form.rustdesk_id.data.strip() if form.rustdesk_id.data else None,
            active=form.active.data,
        )
        db.session.add(h)
        db.session.commit()
        flash(f'Hospital "{h.name}" created.', "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=h.id))
    return render_template("admin/hospital_form.html", form=form, hospital=None)


@bp.route("/hospitals/<int:hospital_id>", methods=["GET", "POST"])
@login_required
@admin_required
def hospital_detail(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    users = User.query.filter_by(hospital_id=hospital_id, role="customer").order_by(User.name).all()
    subscribed_ids = {p.id for p in hospital.products}
    available_products = Product.query.filter_by(active=True).order_by(Product.name).all()
    hospital_product_list = [p for p in hospital.products if p.active]

    # Inline user creation
    add_error = None
    if request.method == "POST" and request.form.get("_action") == "add_user":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        product_ids = request.form.getlist("product_ids", type=int)

        if not name or not email or len(password) < 8:
            add_error = "Name, email and password (min 8 chars) are required."
        elif User.query.filter_by(email=email).first():
            add_error = f"{email} is already registered."
        else:
            u = User(hospital_id=hospital_id, email=email, name=name, role="customer", active=True)
            u.set_password(password)
            valid_ids = {p.id for p in hospital.products}
            u.products = Product.query.filter(Product.id.in_(set(product_ids) & valid_ids)).all()
            db.session.add(u)
            db.session.commit()
            flash(f'User "{u.name}" created.', "success")
            return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id, tab="users"))

    credentials = HospitalCredential.query.filter_by(hospital_id=hospital_id).order_by(
        HospitalCredential.category, HospitalCredential.label
    ).all()
    from app.models.project import Project, ProjectTemplate
    projects = hospital.projects.order_by(Project.created_at.desc()).all()
    templates = ProjectTemplate.query.order_by(ProjectTemplate.name).all()
    active_tab = request.args.get("tab", "users")
    return render_template("admin/hospital_detail.html", hospital=hospital, users=users,
                           subscribed_ids=subscribed_ids, available_products=available_products,
                           hospital_product_list=hospital_product_list,
                           credentials=credentials,
                           projects=projects, templates=templates,
                           add_error=add_error, active_tab=active_tab)


@bp.route("/hospitals/<int:hospital_id>/products/add", methods=["POST"])
@login_required
@admin_required
def hospital_product_add(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    product_id = request.form.get("product_id", type=int)
    product = Product.query.get_or_404(product_id)
    if product not in hospital.products:
        hospital.products.append(product)
        db.session.commit()
        flash(f'"{product.name}" subscribed to {hospital.name}.', "success")
    return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id))


@bp.route("/hospitals/<int:hospital_id>/products/<int:product_id>/remove", methods=["POST"])
@login_required
@admin_required
def hospital_product_remove(hospital_id, product_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    product = Product.query.get_or_404(product_id)
    if product in hospital.products:
        hospital.products.remove(product)
        db.session.commit()
        flash(f'"{product.name}" removed from {hospital.name}.', "warning")
    return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id))


@bp.route("/hospitals/<int:hospital_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def hospital_edit(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    form = HospitalForm(obj=hospital)
    if form.validate_on_submit():
        hospital.name = form.name.data
        hospital.email_domain = form.email_domain.data.lower().strip() if form.email_domain.data else None
        hospital.address = form.address.data
        hospital.phone = form.phone.data
        hospital.rustdesk_server_url = form.rustdesk_server_url.data.strip() if form.rustdesk_server_url.data else None
        hospital.rustdesk_server_key = form.rustdesk_server_key.data.strip() if form.rustdesk_server_key.data else None
        hospital.rustdesk_id = form.rustdesk_id.data.strip() if form.rustdesk_id.data else None
        hospital.active = form.active.data
        db.session.commit()
        flash("Hospital updated.", "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital.id))
    return render_template("admin/hospital_form.html", form=form, hospital=hospital)


@bp.route("/hospitals/bulk-delete", methods=["POST"])
@login_required
@admin_required
def hospital_bulk_delete():
    ids = request.form.getlist("hospital_ids", type=int)
    if not ids:
        flash("No hospitals selected.", "warning")
        return redirect(url_for("admin.hospitals"))
    deleted, skipped = 0, []
    for hospital_id in ids:
        hospital = Hospital.query.get(hospital_id)
        if not hospital:
            continue
        user_count = User.query.filter_by(hospital_id=hospital_id).count()
        ticket_count = hospital.tickets.count()
        if user_count or ticket_count:
            skipped.append(f"{hospital.name} ({user_count} users, {ticket_count} tickets)")
            continue
        db.session.delete(hospital)
        deleted += 1
    db.session.commit()
    if deleted:
        flash(f"{deleted} hospital(s) deleted.", "success")
    if skipped:
        flash("Skipped — still have data: " + "; ".join(skipped), "warning")
    return redirect(url_for("admin.hospitals"))


@bp.route("/hospitals/<int:hospital_id>/delete", methods=["POST"])
@login_required
@admin_required
def hospital_delete(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    user_count = User.query.filter_by(hospital_id=hospital_id).count()
    ticket_count = hospital.tickets.count()
    if user_count or ticket_count:
        flash(
            f'Cannot delete "{hospital.name}" — it still has '
            f'{user_count} user(s) and {ticket_count} ticket(s). Remove them first.',
            "error",
        )
        return redirect(url_for("admin.hospitals"))
    db.session.delete(hospital)
    db.session.commit()
    flash(f'"{hospital.name}" deleted.', "success")
    return redirect(url_for("admin.hospitals"))


# ── Products (global panel) ───────────────────────────────────────────────────

@bp.route("/products")
@login_required
@admin_required
def products_list():
    products = Product.query.order_by(Product.name).all()
    return render_template("admin/products.html", products=products)


@bp.route("/products/new", methods=["GET", "POST"])
@login_required
@admin_required
def product_new():
    form = ProductForm()
    if form.validate_on_submit():
        p = Product(
            name=form.name.data,
            description=form.description.data,
            active=form.active.data,
        )
        db.session.add(p)
        db.session.commit()
        flash(f'Product "{p.name}" added.', "success")
        return redirect(url_for("admin.products_list"))
    return render_template("admin/product_form.html", form=form, product=None)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        product.name = form.name.data
        product.description = form.description.data
        product.active = form.active.data
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("admin.products_list"))
    return render_template("admin/product_form.html", form=form, product=product)


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash(f'Product "{product.name}" deleted.', "success")
    return redirect(url_for("admin.products_list"))


# ── Customer Users ────────────────────────────────────────────────────────────

@bp.route("/hospitals/<int:hospital_id>/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def user_new(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    form = CustomerUserForm()
    if form.validate_on_submit():
        u = User(
            hospital_id=hospital_id,
            email=form.email.data.lower().strip(),
            name=form.name.data,
            role="customer",
            active=True,
        )
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()
        flash(f'User "{u.name}" created.', "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id))
    return render_template("admin/user_form.html", form=form, hospital=hospital, edit_user=None)


@bp.route("/hospitals/<int:hospital_id>/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(hospital_id, user_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    edit_user = User.query.get_or_404(user_id)
    hospital_products = sorted([p for p in hospital.products if p.active], key=lambda p: p.name)
    form = EditUserForm(obj=edit_user)
    form.product_ids.choices = [(p.id, p.name) for p in hospital_products]
    if request.method == "GET":
        form.product_ids.data = [p.id for p in edit_user.products]
    if form.validate_on_submit():
        edit_user.name = form.name.data
        edit_user.active = form.active.data
        valid_ids = {p.id for p in hospital.products}
        selected_ids = set(form.product_ids.data or []) & valid_ids
        edit_user.products = Product.query.filter(Product.id.in_(selected_ids)).all()
        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id))
    return render_template("admin/user_form.html", form=form, hospital=hospital,
                           edit_user=edit_user, hospital_products=hospital_products)


@bp.route("/hospitals/<int:hospital_id>/users/<int:user_id>/remove", methods=["POST"])
@login_required
@admin_required
def user_remove(hospital_id, user_id):
    user = User.query.get_or_404(user_id)
    user.active = False
    db.session.commit()
    flash(f'User "{user.name}" deactivated.', "warning")
    return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id))


# ── Agents ────────────────────────────────────────────────────────────────────

@bp.route("/agents")
@login_required
@admin_required
def agents():
    all_agents = User.query.filter(User.role.in_(["agent", "admin"])).order_by(User.name).all()
    return render_template("admin/agents.html", agents=all_agents)


@bp.route("/agents/new", methods=["GET", "POST"])
@login_required
@admin_required
def agent_new():
    form = AgentForm()
    if form.validate_on_submit():
        u = User(
            hospital_id=None,
            email=form.email.data.lower().strip(),
            name=form.name.data,
            role=form.role.data,
            active=True,
        )
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()
        flash(f'Agent "{u.name}" created.', "success")
        return redirect(url_for("admin.agents"))
    return render_template("admin/agent_form.html", form=form, edit_agent=None)


@bp.route("/agents/<int:agent_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def agent_edit(agent_id):
    edit_agent = User.query.get_or_404(agent_id)
    form = EditUserForm(obj=edit_agent)
    if form.validate_on_submit():
        edit_agent.name = form.name.data
        edit_agent.active = form.active.data
        db.session.commit()
        flash("Agent updated.", "success")
        return redirect(url_for("admin.agents"))
    return render_template("admin/agent_form.html", form=form, edit_agent=edit_agent)


@bp.route("/agents/<int:agent_id>/reset-password", methods=["GET", "POST"])
@login_required
@admin_required
def agent_reset_password(agent_id):
    edit_agent = User.query.get_or_404(agent_id)
    form = ResetPasswordForm()
    if form.validate_on_submit():
        edit_agent.set_password(form.new_password.data)
        db.session.commit()
        flash(f'Password reset for "{edit_agent.name}".', "success")
        return redirect(url_for("admin.agents"))
    return render_template("admin/reset_password.html", form=form, edit_agent=edit_agent)


# ── Canned Responses ──────────────────────────────────────────────────────────

@bp.route("/canned-responses")
@login_required
@admin_required
def canned_responses():
    items = CannedResponse.query.order_by(CannedResponse.title).all()
    return render_template("admin/canned_responses.html", items=items)


@bp.route("/canned-responses/new", methods=["GET", "POST"])
@login_required
@admin_required
def canned_response_new():
    form = CannedResponseForm()
    if form.validate_on_submit():
        cr = CannedResponse(
            title=form.title.data,
            body=form.body.data,
            is_shared=form.is_shared.data,
            created_by=current_user.id,
        )
        db.session.add(cr)
        db.session.commit()
        flash("Canned response created.", "success")
        return redirect(url_for("admin.canned_responses"))
    return render_template("admin/canned_response_form.html", form=form, item=None)


@bp.route("/canned-responses/<int:cr_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def canned_response_edit(cr_id):
    cr = CannedResponse.query.get_or_404(cr_id)
    form = CannedResponseForm(obj=cr)
    if form.validate_on_submit():
        cr.title = form.title.data
        cr.body = form.body.data
        cr.is_shared = form.is_shared.data
        db.session.commit()
        flash("Canned response updated.", "success")
        return redirect(url_for("admin.canned_responses"))
    return render_template("admin/canned_response_form.html", form=form, item=cr)


@bp.route("/canned-responses/<int:cr_id>/delete", methods=["POST"])
@login_required
@admin_required
def canned_response_delete(cr_id):
    cr = CannedResponse.query.get_or_404(cr_id)
    db.session.delete(cr)
    db.session.commit()
    flash("Canned response deleted.", "success")
    return redirect(url_for("admin.canned_responses"))


# ── Assignment Rules ──────────────────────────────────────────────────────────

def _rule_form_choices(form):
    hospitals = Hospital.query.order_by(Hospital.name).all()
    products = Product.query.order_by(Product.name).all()
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()
    form.hospital_id.choices = [(0, "Any hospital")] + [(h.id, h.name) for h in hospitals]
    form.product_id.choices = [(0, "Any product")] + [(p.id, p.name) for p in products]
    form.assigned_to.choices = [(a.id, a.name) for a in agents]


@bp.route("/assignment-rules")
@login_required
@admin_required
def assignment_rules():
    rules = AssignmentRule.query.order_by(AssignmentRule.rule_order).all()
    return render_template("admin/assignment_rules.html", rules=rules)


@bp.route("/assignment-rules/new", methods=["GET", "POST"])
@login_required
@admin_required
def assignment_rule_new():
    form = AssignmentRuleForm()
    _rule_form_choices(form)
    if form.validate_on_submit():
        rule = AssignmentRule(
            hospital_id=form.hospital_id.data or None,
            product_id=form.product_id.data or None,
            priority=form.priority.data or None,
            assigned_to=form.assigned_to.data,
            rule_order=form.rule_order.data,
            is_active=form.is_active.data,
            created_by=current_user.id,
        )
        db.session.add(rule)
        db.session.commit()
        flash("Assignment rule created.", "success")
        return redirect(url_for("admin.assignment_rules"))
    return render_template("admin/assignment_rule_form.html", form=form, rule=None)


@bp.route("/assignment-rules/<int:rule_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def assignment_rule_edit(rule_id):
    rule = AssignmentRule.query.get_or_404(rule_id)
    form = AssignmentRuleForm(obj=rule)
    _rule_form_choices(form)
    if request.method == "GET":
        form.hospital_id.data = rule.hospital_id or 0
        form.product_id.data = rule.product_id or 0
        form.priority.data = rule.priority or ""
    if form.validate_on_submit():
        rule.hospital_id = form.hospital_id.data or None
        rule.product_id = form.product_id.data or None
        rule.priority = form.priority.data or None
        rule.assigned_to = form.assigned_to.data
        rule.rule_order = form.rule_order.data
        rule.is_active = form.is_active.data
        db.session.commit()
        flash("Assignment rule updated.", "success")
        return redirect(url_for("admin.assignment_rules"))
    return render_template("admin/assignment_rule_form.html", form=form, rule=rule)


@bp.route("/assignment-rules/<int:rule_id>/delete", methods=["POST"])
@login_required
@admin_required
def assignment_rule_delete(rule_id):
    rule = AssignmentRule.query.get_or_404(rule_id)
    db.session.delete(rule)
    db.session.commit()
    flash("Assignment rule deleted.", "success")
    return redirect(url_for("admin.assignment_rules"))


# ── Webhook Configs ───────────────────────────────────────────────────────────

@bp.route("/webhooks")
@login_required
@admin_required
def webhooks():
    hooks = WebhookConfig.query.order_by(WebhookConfig.id).all()
    return render_template("admin/webhooks.html", hooks=hooks)


@bp.route("/webhooks/new", methods=["GET", "POST"])
@login_required
@admin_required
def webhook_new():
    form = WebhookConfigForm()
    form.events.choices = [(e, e.replace("_", " ").title()) for e in WEBHOOK_EVENTS]
    if form.validate_on_submit():
        hook = WebhookConfig(
            url=form.url.data,
            secret=form.secret.data or None,
            events=form.events.data,
            is_active=form.is_active.data,
            created_by=current_user.id,
        )
        db.session.add(hook)
        db.session.commit()
        flash("Webhook created.", "success")
        return redirect(url_for("admin.webhooks"))
    return render_template("admin/webhook_form.html", form=form, hook=None)


@bp.route("/webhooks/<int:hook_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def webhook_edit(hook_id):
    hook = WebhookConfig.query.get_or_404(hook_id)
    form = WebhookConfigForm(obj=hook)
    form.events.choices = [(e, e.replace("_", " ").title()) for e in WEBHOOK_EVENTS]
    if form.validate_on_submit():
        hook.url = form.url.data
        hook.secret = form.secret.data or None
        hook.events = form.events.data
        hook.is_active = form.is_active.data
        db.session.commit()
        flash("Webhook updated.", "success")
        return redirect(url_for("admin.webhooks"))
    return render_template("admin/webhook_form.html", form=form, hook=hook)


@bp.route("/webhooks/<int:hook_id>/delete", methods=["POST"])
@login_required
@admin_required
def webhook_delete(hook_id):
    hook = WebhookConfig.query.get_or_404(hook_id)
    db.session.delete(hook)
    db.session.commit()
    flash("Webhook deleted.", "success")
    return redirect(url_for("admin.webhooks"))


# ── Project Task Templates ────────────────────────────────────────────────────

@bp.route("/project-templates")
@login_required
@admin_required
def project_templates():
    templates = ProjectTemplate.query.order_by(ProjectTemplate.name).all()
    return render_template("admin/project_templates.html", templates=templates)


@bp.route("/project-templates/new", methods=["GET", "POST"])
@login_required
@admin_required
def project_template_new():
    form = ProjectTemplateForm()
    if form.validate_on_submit():
        tmpl = ProjectTemplate(
            name=form.name.data,
            description=form.description.data,
            created_by=current_user.id,
        )
        db.session.add(tmpl)
        db.session.flush()
        _save_template_tasks(tmpl)
        db.session.commit()
        flash(f'Template "{tmpl.name}" created.', "success")
        return redirect(url_for("admin.project_template_edit", tmpl_id=tmpl.id))
    return render_template("admin/project_template_form.html", form=form, tmpl=None)


@bp.route("/project-templates/<int:tmpl_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def project_template_edit(tmpl_id):
    tmpl = ProjectTemplate.query.get_or_404(tmpl_id)
    form = ProjectTemplateForm(obj=tmpl)
    if form.validate_on_submit():
        tmpl.name = form.name.data
        tmpl.description = form.description.data
        # Replace tasks
        for t in list(tmpl.tasks):
            db.session.delete(t)
        db.session.flush()
        _save_template_tasks(tmpl)
        db.session.commit()
        flash("Template updated.", "success")
        return redirect(url_for("admin.project_template_edit", tmpl_id=tmpl.id))
    return render_template("admin/project_template_form.html", form=form, tmpl=tmpl)


@bp.route("/project-templates/<int:tmpl_id>/delete", methods=["POST"])
@login_required
@admin_required
def project_template_delete(tmpl_id):
    tmpl = ProjectTemplate.query.get_or_404(tmpl_id)
    db.session.delete(tmpl)
    db.session.commit()
    flash("Template deleted.", "success")
    return redirect(url_for("admin.project_templates"))


def _save_template_tasks(tmpl):
    titles = request.form.getlist("task_title[]")
    descs = request.form.getlist("task_desc[]")
    priorities = request.form.getlist("task_priority[]")
    for i, title in enumerate(titles):
        title = title.strip()
        if not title:
            continue
        t = ProjectTemplateTask(
            template_id=tmpl.id,
            title=title,
            description=descs[i] if i < len(descs) else None,
            default_priority=priorities[i] if i < len(priorities) else "medium",
            order=i,
        )
        db.session.add(t)


# ── Knowledge Base ────────────────────────────────────────────────────────────

@bp.route("/kb")
@login_required
@admin_required
def kb_articles():
    articles = KBArticle.query.order_by(KBArticle.category, KBArticle.title).all()
    return render_template("admin/kb_articles.html", articles=articles)


@bp.route("/kb/new", methods=["GET", "POST"])
@login_required
@admin_required
def kb_article_new():
    form = KBArticleForm()
    if form.validate_on_submit():
        slug = _make_slug(form.title.data)
        article = KBArticle(
            title=form.title.data,
            slug=slug,
            body=form.body.data,
            category=form.category.data.strip() if form.category.data else None,
            is_published=form.is_published.data,
            created_by=current_user.id,
        )
        db.session.add(article)
        db.session.commit()
        flash("Article saved.", "success")
        return redirect(url_for("admin.kb_articles"))
    return render_template("admin/kb_article_form.html", form=form, article=None)


@bp.route("/kb/<int:article_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def kb_article_edit(article_id):
    article = KBArticle.query.get_or_404(article_id)
    form = KBArticleForm(obj=article)
    if form.validate_on_submit():
        article.title = form.title.data
        article.body = form.body.data
        article.category = form.category.data.strip() if form.category.data else None
        article.is_published = form.is_published.data
        db.session.commit()
        flash("Article updated.", "success")
        return redirect(url_for("admin.kb_articles"))
    return render_template("admin/kb_article_form.html", form=form, article=article)


@bp.route("/kb/<int:article_id>/delete", methods=["POST"])
@login_required
@admin_required
def kb_article_delete(article_id):
    article = KBArticle.query.get_or_404(article_id)
    db.session.delete(article)
    db.session.commit()
    flash("Article deleted.", "success")
    return redirect(url_for("admin.kb_articles"))


def _make_slug(title):
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    base = slug
    n = 1
    while KBArticle.query.filter_by(slug=slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ── Ticket Templates (Service Catalog) ───────────────────────────────────────

def _ticket_template_choices(form):
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    form.product_id.choices = [(0, "— No product —")] + [(p.id, p.name) for p in products]


@bp.route("/ticket-templates")
@login_required
@admin_required
def ticket_templates():
    templates = TicketTemplate.query.order_by(TicketTemplate.category, TicketTemplate.name).all()
    return render_template("admin/ticket_templates.html", templates=templates)


@bp.route("/ticket-templates/new", methods=["GET", "POST"])
@login_required
@admin_required
def ticket_template_new():
    form = TicketTemplateForm()
    _ticket_template_choices(form)
    if form.validate_on_submit():
        tmpl = TicketTemplate(
            name=form.name.data,
            description=form.description.data,
            category=form.category.data.strip() if form.category.data else None,
            subject=form.subject.data,
            body=form.body.data,
            default_priority=form.default_priority.data,
            product_id=form.product_id.data or None,
            is_active=form.is_active.data,
            created_by=current_user.id,
        )
        db.session.add(tmpl)
        db.session.commit()
        flash(f'Ticket template "{tmpl.name}" created.', "success")
        return redirect(url_for("admin.ticket_templates"))
    return render_template("admin/ticket_template_form.html", form=form, tmpl=None)


@bp.route("/ticket-templates/<int:tmpl_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def ticket_template_edit(tmpl_id):
    tmpl = TicketTemplate.query.get_or_404(tmpl_id)
    form = TicketTemplateForm(obj=tmpl)
    _ticket_template_choices(form)
    if request.method == "GET":
        form.product_id.data = tmpl.product_id or 0
    if form.validate_on_submit():
        tmpl.name = form.name.data
        tmpl.description = form.description.data
        tmpl.category = form.category.data.strip() if form.category.data else None
        tmpl.subject = form.subject.data
        tmpl.body = form.body.data
        tmpl.default_priority = form.default_priority.data
        tmpl.product_id = form.product_id.data or None
        tmpl.is_active = form.is_active.data
        db.session.commit()
        flash("Ticket template updated.", "success")
        return redirect(url_for("admin.ticket_templates"))
    return render_template("admin/ticket_template_form.html", form=form, tmpl=tmpl)


@bp.route("/ticket-templates/<int:tmpl_id>/delete", methods=["POST"])
@login_required
@admin_required
def ticket_template_delete(tmpl_id):
    tmpl = TicketTemplate.query.get_or_404(tmpl_id)
    db.session.delete(tmpl)
    db.session.commit()
    flash("Ticket template deleted.", "success")
    return redirect(url_for("admin.ticket_templates"))


# ── SLA Policies ──────────────────────────────────────────────────────────────

@bp.route("/sla-policies")
@login_required
@admin_required
def sla_policies():
    policies = SLAPolicy.query.order_by(
        db.case({"urgent": 0, "high": 1, "medium": 2, "low": 3}, value=SLAPolicy.priority)
    ).all()
    return render_template("admin/sla_policies.html", policies=policies)


@bp.route("/sla-policies/new", methods=["GET", "POST"])
@login_required
@admin_required
def sla_policy_new():
    form = SLAPolicyForm()
    if form.validate_on_submit():
        existing = SLAPolicy.query.filter_by(priority=form.priority.data).first()
        if existing:
            flash(f"A policy for '{form.priority.data}' already exists. Edit it instead.", "warning")
            return redirect(url_for("admin.sla_policies"))
        policy = SLAPolicy(
            priority=form.priority.data,
            response_hours=form.response_hours.data,
            resolve_hours=form.resolve_hours.data,
            is_active=form.is_active.data,
        )
        db.session.add(policy)
        db.session.commit()
        flash(f"SLA policy for '{policy.priority}' created.", "success")
        return redirect(url_for("admin.sla_policies"))
    return render_template("admin/sla_policy_form.html", form=form, policy=None)


@bp.route("/sla-policies/<int:policy_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def sla_policy_edit(policy_id):
    policy = SLAPolicy.query.get_or_404(policy_id)
    form = SLAPolicyForm(obj=policy)
    if form.validate_on_submit():
        policy.priority = form.priority.data
        policy.response_hours = form.response_hours.data
        policy.resolve_hours = form.resolve_hours.data
        policy.is_active = form.is_active.data
        db.session.commit()
        flash("SLA policy updated.", "success")
        return redirect(url_for("admin.sla_policies"))
    return render_template("admin/sla_policy_form.html", form=form, policy=policy)


@bp.route("/sla-policies/<int:policy_id>/delete", methods=["POST"])
@login_required
@admin_required
def sla_policy_delete(policy_id):
    policy = SLAPolicy.query.get_or_404(policy_id)
    ticket_count = Ticket.query.filter_by(priority=policy.priority).count()
    if ticket_count > 0:
        flash(
            f"Cannot delete: {ticket_count} ticket(s) currently use the '{policy.priority}' priority. "
            "Reassign or close them first.",
            "warning",
        )
        return redirect(url_for("admin.sla_policies"))
    db.session.delete(policy)
    db.session.commit()
    flash("SLA policy deleted.", "success")
    return redirect(url_for("admin.sla_policies"))


# ── Shared Installations ──────────────────────────────────────────────────────

def _shared_installation_form_choices(form):
    form.product_id.choices = [(p.id, p.name) for p in
                               Product.query.filter_by(active=True).order_by(Product.name).all()]
    form.hospital_ids.choices = [(h.id, h.name) for h in
                                 Hospital.query.filter_by(active=True).order_by(Hospital.name).all()]


@bp.route("/shared-installations")
@login_required
@admin_required
def shared_installations():
    installations = SharedInstallation.query.order_by(SharedInstallation.name).all()
    return render_template("admin/shared_installations.html", installations=installations)


@bp.route("/shared-installations/new", methods=["GET", "POST"])
@login_required
@admin_required
def shared_installation_new():
    form = SharedInstallationForm()
    _shared_installation_form_choices(form)
    if form.validate_on_submit():
        valid_hosp_ids = {h.id for h in Hospital.query.all()}
        selected_hosp_ids = set(form.hospital_ids.data or []) & valid_hosp_ids
        if len(selected_hosp_ids) < 2:
            flash("A shared installation requires at least two hospitals.", "warning")
        else:
            inst = SharedInstallation(name=form.name.data, product_id=form.product_id.data)
            inst.hospitals = Hospital.query.filter(Hospital.id.in_(selected_hosp_ids)).all()
            db.session.add(inst)
            db.session.commit()
            flash(f'Shared installation "{inst.name}" created.', "success")
            return redirect(url_for("admin.shared_installations"))
    return render_template("admin/shared_installation_form.html", form=form, inst=None)


@bp.route("/shared-installations/<int:inst_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def shared_installation_edit(inst_id):
    inst = SharedInstallation.query.get_or_404(inst_id)
    form = SharedInstallationForm(obj=inst)
    _shared_installation_form_choices(form)
    if request.method == "GET":
        form.hospital_ids.data = [h.id for h in inst.hospitals]
    if form.validate_on_submit():
        valid_hosp_ids = {h.id for h in Hospital.query.all()}
        selected_hosp_ids = set(form.hospital_ids.data or []) & valid_hosp_ids
        if len(selected_hosp_ids) < 2:
            flash("A shared installation requires at least two hospitals.", "warning")
        else:
            inst.name = form.name.data
            inst.product_id = form.product_id.data
            inst.hospitals = Hospital.query.filter(Hospital.id.in_(selected_hosp_ids)).all()
            db.session.commit()
            flash("Shared installation updated.", "success")
            return redirect(url_for("admin.shared_installations"))
    return render_template("admin/shared_installation_form.html", form=form, inst=inst)


@bp.route("/shared-installations/<int:inst_id>/delete", methods=["POST"])
@login_required
@admin_required
def shared_installation_delete(inst_id):
    inst = SharedInstallation.query.get_or_404(inst_id)
    db.session.delete(inst)
    db.session.commit()
    flash(f'Shared installation "{inst.name}" deleted.', "success")
    return redirect(url_for("admin.shared_installations"))


# ── Hub pages ─────────────────────────────────────────────────────────────────

@bp.route("/templates")
@login_required
@admin_required
def templates_hub():
    ticket_templates = TicketTemplate.query.order_by(TicketTemplate.category, TicketTemplate.name).all()
    project_templates = ProjectTemplate.query.order_by(ProjectTemplate.name).all()
    return render_template("admin/templates_hub.html",
                           ticket_templates=ticket_templates,
                           project_templates=project_templates)


@bp.route("/automation")
@login_required
@admin_required
def automation_hub():
    from app.models.assignment_rule import AssignmentRule
    from app.models.canned_response import CannedResponse
    sla_policies = SLAPolicy.query.order_by(
        db.case({"urgent": 1, "high": 2, "medium": 3, "low": 4}, value=SLAPolicy.priority)
    ).all()
    rules = AssignmentRule.query.order_by(AssignmentRule.rule_order).all()
    canned = CannedResponse.query.order_by(CannedResponse.title).all()
    return render_template("admin/automation_hub.html",
                           sla_policies=sla_policies, rules=rules, canned=canned)


# ── Ticket Statuses ───────────────────────────────────────────────────────────

@bp.route("/ticket-statuses")
@login_required
@admin_required
def ticket_statuses():
    statuses = TicketStatus.query.order_by(TicketStatus.order).all()
    return render_template("admin/ticket_statuses.html", statuses=statuses)


@bp.route("/ticket-statuses/new", methods=["GET", "POST"])
@login_required
@admin_required
def ticket_status_new():
    form = NewTicketStatusForm()
    if form.validate_on_submit():
        if TicketStatus.query.get(form.slug.data):
            form.slug.errors = ["This slug is already in use."]
        else:
            color = form.color.data.strip()
            if not color.startswith("#"):
                color = "#" + color
            max_order = db.session.query(func.max(TicketStatus.order)).scalar() or 0
            status = TicketStatus(
                slug=form.slug.data,
                label=form.label.data.strip(),
                color=color,
                order=max_order + 1,
                is_system=False,
            )
            db.session.add(status)
            db.session.commit()
            flash(f'Status "{status.label}" created.', "success")
            return redirect(url_for("admin.ticket_statuses"))
    return render_template("admin/ticket_status_new.html", form=form)


@bp.route("/ticket-statuses/<slug>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def ticket_status_edit(slug):
    status = TicketStatus.query.get_or_404(slug)
    form = TicketStatusForm(obj=status)
    if form.validate_on_submit():
        status.label = form.label.data.strip()
        color = form.color.data.strip()
        if not color.startswith("#"):
            color = "#" + color
        status.color = color
        db.session.commit()
        flash(f'Status "{status.label}" updated.', "success")
        return redirect(url_for("admin.ticket_statuses"))
    return render_template("admin/ticket_status_form.html", form=form, status=status)


@bp.route("/ticket-statuses/<slug>/delete", methods=["POST"])
@login_required
@admin_required
def ticket_status_delete(slug):
    status = TicketStatus.query.get_or_404(slug)
    if status.is_system:
        flash("System statuses cannot be deleted.", "warning")
        return redirect(url_for("admin.ticket_statuses"))
    ticket_count = Ticket.query.filter_by(status=slug).count()
    if ticket_count > 0:
        flash(f"Cannot delete: {ticket_count} ticket(s) currently use this status.", "warning")
        return redirect(url_for("admin.ticket_statuses"))
    db.session.delete(status)
    db.session.commit()
    flash(f'Status "{status.label}" deleted.', "success")
    return redirect(url_for("admin.ticket_statuses"))


# ── Hospital Credentials ──────────────────────────────────────────────────────

def _agent_or_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@bp.route("/hospitals/<int:hospital_id>/credentials/add", methods=["GET", "POST"])
@login_required
@_agent_or_admin_required
def credential_add(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    form = CredentialForm()
    if form.validate_on_submit():
        cred = HospitalCredential(
            hospital_id=hospital_id,
            category=form.category.data,
            label=form.label.data,
            username=form.username.data or None,
            password_enc=encrypt(form.password.data) if form.password.data else None,
            host_enc=encrypt(form.host.data) if form.host.data else None,
            role_enc=encrypt(form.role.data) if form.role.data else None,
            url=form.url.data or None,
            notes=form.notes.data or None,
            created_by=current_user.id,
        )
        db.session.add(cred)
        db.session.commit()
        flash("Credential added.", "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id, tab="access"))
    return render_template("admin/credential_form.html", form=form, hospital=hospital, cred=None)


@bp.route("/hospitals/<int:hospital_id>/credentials/<int:cred_id>/edit", methods=["GET", "POST"])
@login_required
@_agent_or_admin_required
def credential_edit(hospital_id, cred_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    cred = HospitalCredential.query.filter_by(id=cred_id, hospital_id=hospital_id).first_or_404()
    form = CredentialForm(obj=cred)
    if form.validate_on_submit():
        cred.category = form.category.data
        cred.label = form.label.data
        cred.username = form.username.data or None
        if form.password.data:
            cred.password_enc = encrypt(form.password.data)
        if form.host.data:
            cred.host_enc = encrypt(form.host.data)
        if form.role.data:
            cred.role_enc = encrypt(form.role.data)
        cred.url = form.url.data or None
        cred.notes = form.notes.data or None
        db.session.commit()
        flash("Credential updated.", "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id, tab="access"))
    return render_template("admin/credential_form.html", form=form, hospital=hospital, cred=cred)


@bp.route("/hospitals/<int:hospital_id>/credentials/<int:cred_id>/delete", methods=["POST"])
@login_required
@_agent_or_admin_required
def credential_delete(hospital_id, cred_id):
    cred = HospitalCredential.query.filter_by(id=cred_id, hospital_id=hospital_id).first_or_404()
    db.session.delete(cred)
    db.session.commit()
    flash("Credential deleted.", "success")
    return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id, tab="access"))


@bp.route("/hospitals/<int:hospital_id>/credentials/<int:cred_id>/reveal", methods=["POST"])
@csrf.exempt
@login_required
@_agent_or_admin_required
def credential_reveal(hospital_id, cred_id):
    cred = HospitalCredential.query.filter_by(id=cred_id, hospital_id=hospital_id).first_or_404()
    data = request.get_json(silent=True) or {}
    entered = data.get("key", "")
    master = current_app.config.get("CREDENTIAL_MASTER_KEY", "")
    if not master or entered != master:
        return jsonify({"ok": False}), 403
    return jsonify({
        "ok": True,
        "password": decrypt(cred.password_enc) if cred.password_enc else "",
        "host": decrypt(cred.host_enc) if cred.host_enc else "",
        "role": decrypt(cred.role_enc) if cred.role_enc else "",
    })


@bp.route("/hospitals/<int:hospital_id>/access")
@login_required
@_agent_or_admin_required
def hospital_access(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    credentials = HospitalCredential.query.filter_by(hospital_id=hospital_id).order_by(
        HospitalCredential.category, HospitalCredential.label
    ).all()
    return render_template("admin/hospital_access.html", hospital=hospital, credentials=credentials)


# ── Email Diagnostics ─────────────────────────────────────────────────────────

@bp.route("/email/test", methods=["GET", "POST"])
@login_required
@admin_required
def email_test():
    from app.models.email_config import EmailConfig
    from app.services.email_settings import get_effective_config
    cfg = current_app.config
    token_ok = False
    token_error = ""
    send_result = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_config":
            tenant_id = (request.form.get("tenant_id") or "").strip()
            client_id = (request.form.get("client_id") or "").strip()
            client_secret = (request.form.get("client_secret") or "").strip()
            mailbox = (request.form.get("mailbox") or "").strip()

            import re
            guid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
            errors = []
            if tenant_id and not guid_re.match(tenant_id):
                errors.append("Tenant ID must be a valid GUID (8-4-4-4-12 hex format).")
            if client_id and not guid_re.match(client_id):
                errors.append("Client ID must be a valid GUID (8-4-4-4-12 hex format).")

            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                try:
                    row = EmailConfig.get_singleton()
                    row.tenant_id = tenant_id or None
                    row.client_id = client_id or None
                    row.mailbox = mailbox or None
                    if client_secret:
                        row.client_secret_enc = encrypt(client_secret)
                    row.updated_by = current_user.id
                    db.session.commit()
                    flash("Email configuration saved. Changes apply immediately to new requests.", "success")
                    return redirect(url_for("admin.email_test"))
                except Exception as e:
                    db.session.rollback()
                    msg = str(e)
                    if "email_config" in msg and ("does not exist" in msg or "no such table" in msg.lower()):
                        flash("The email_config table is missing — run 'flask db upgrade' on the server, then try again.", "danger")
                    else:
                        flash(f"Save failed: {e}", "danger")
                    current_app.logger.exception("email_config save failed")

        elif action == "test_token":
            try:
                import msal
                eff = get_effective_config()
                if not all([eff["tenant_id"], eff["client_id"], eff["client_secret"]]):
                    flash("Missing one or more credentials — fill them in above and Save first.", "warning")
                else:
                    authority = f"https://login.microsoftonline.com/{eff['tenant_id']}"
                    app_obj = msal.ConfidentialClientApplication(
                        eff["client_id"],
                        authority=authority,
                        client_credential=eff["client_secret"],
                    )
                    result = app_obj.acquire_token_for_client(
                        scopes=["https://graph.microsoft.com/.default"]
                    )
                    if "access_token" in result:
                        token_ok = True
                        flash("Graph API token acquired successfully.", "success")
                    else:
                        token_error = result.get("error_description", result.get("error", "Unknown error"))
                        flash(f"Token error: {token_error}", "danger")
            except Exception as e:
                token_error = str(e)
                flash(f"Exception: {e}", "danger")

        elif action == "send_test":
            recipient = request.form.get("recipient", "").strip()
            if not recipient:
                flash("Enter a recipient address.", "warning")
            else:
                try:
                    from app.services.email_outbound import send_diagnostic
                    import datetime as _dt
                    ok, msg = send_diagnostic(
                        recipient,
                        subject="[Intermedic Support] Email Test",
                        text=(
                            f"This is a test email from the Intermedic Support Desk.\n\n"
                            f"Mailbox: {get_effective_config()['mailbox']}\n"
                            f"Time: {_dt.datetime.utcnow().isoformat()} UTC"
                        ),
                    )
                    if ok:
                        flash(f"Test email accepted by Graph API for {recipient}. {msg}", "success")
                    else:
                        flash(f"Send failed — {msg}", "danger")
                        current_app.logger.error("email send_test failed: %s", msg)
                except Exception as e:
                    flash(f"Send failed (exception): {e}", "danger")
                    current_app.logger.exception("email send_test crashed")

        elif action == "poll_now":
            try:
                from app.services.email_inbound import fetch_and_process
                fetch_and_process(current_app._get_current_object())
                flash("Email poll completed — check logs for details.", "success")
            except Exception as e:
                flash(f"Poll failed: {e}", "danger")

    eff = get_effective_config()
    try:
        row = EmailConfig.query.first()
    except Exception:
        db.session.rollback()
        row = None
        current_app.logger.warning("email_config table not available — run 'flask db upgrade'")
    status = {
        "tenant_id":     bool(eff["tenant_id"]),
        "client_id":     bool(eff["client_id"]),
        "client_secret": bool(eff["client_secret"]),
        "mailbox":       eff["mailbox"],
        "poll_interval": cfg.get("EMAIL_POLL_INTERVAL_SECONDS", 60),
        "source":        eff["source"],
    }
    form_values = {
        "tenant_id": (row.tenant_id if row else "") or "",
        "client_id": (row.client_id if row else "") or "",
        "mailbox":   (row.mailbox if row else "") or "",
        "has_secret": bool(row and row.client_secret_enc),
        "updated_at": row.updated_at if row else None,
    }
    return render_template("admin/email_test.html", status=status,
                           token_ok=token_ok, token_error=token_error,
                           form_values=form_values)


# ── Excel bulk import ──────────────────────────────────────────────────────────

@bp.route("/import-excel", methods=["GET", "POST"])
@login_required
@admin_required
def import_excel():
    import os, tempfile
    from app.services.excel_import import import_sites_excel

    if request.method == "POST":
        f = request.files.get("excel_file")
        if not f or not f.filename.lower().endswith((".xlsx", ".xls")):
            flash("Please upload a valid .xlsx file.", "error")
            return redirect(url_for("admin.import_excel"))

        suffix = ".xlsx" if f.filename.lower().endswith(".xlsx") else ".xls"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            f.save(tmp.name)
            tmp.close()
            stats = import_sites_excel(tmp.name, created_by=current_user.id)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Excel import failed")
            flash(f"Import failed: {e}", "error")
            return redirect(url_for("admin.import_excel"))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        flash(
            f"Import complete — {stats['hospitals']} sites processed, "
            f"{stats['credentials']} credentials imported.",
            "success",
        )
        return redirect(url_for("admin.import_excel"))

    return render_template("admin/import_excel.html")
