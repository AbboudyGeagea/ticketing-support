from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.blueprints.admin import bp
from app.blueprints.admin.forms import (
    HospitalForm, ProductForm, CustomerUserForm, AgentForm, EditUserForm, ResetPasswordForm,
    CannedResponseForm, AssignmentRuleForm, WebhookConfigForm, ProjectTemplateForm,
    KBArticleForm, TicketTemplateForm, SLAPolicyForm, SharedInstallationForm, TicketStatusForm,
)
from app.models.hospital import Hospital
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
from app.extensions import db
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
    all_hospitals = Hospital.query.order_by(Hospital.name).all()
    return render_template("admin/hospitals.html", hospitals=all_hospitals)


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

    active_tab = request.args.get("tab", "users")
    return render_template("admin/hospital_detail.html", hospital=hospital, users=users,
                           subscribed_ids=subscribed_ids, available_products=available_products,
                           hospital_product_list=hospital_product_list,
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
        hospital.active = form.active.data
        db.session.commit()
        flash("Hospital updated.", "success")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital.id))
    return render_template("admin/hospital_form.html", form=form, hospital=hospital)


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
