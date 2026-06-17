import json
from datetime import date
from functools import wraps
from flask import render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.blueprints.projects import bp
from app.blueprints.projects.forms import ProjectForm, MilestoneForm, ProjectTaskForm, CommentForm
from app.models.project import (
    Project, ProjectMilestone, ProjectTask, ProjectComment,
    ProjectTemplate, ProjectTemplateTask, ProjectTemplateRequirement,
    ProjectRequirement, REQ_TYPES,
)
from app.models.hospital import Hospital
from app.models.user import User
from app.extensions import db


# ── Decorators ────────────────────────────────────────────────────────────────

def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def customer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_customer:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hospital_choices():
    """Return list of (id, name) tuples for active hospitals."""
    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).all()
    return [(h.id, h.name) for h in hospitals]


def _agent_choices():
    """Return list of (id, name) tuples for agents/admins, plus a blank option."""
    agents = (
        User.query.filter(User.role.in_(["agent", "admin"]), User.active == True)
        .order_by(User.name)
        .all()
    )
    return [(0, "— Unassigned —")] + [(u.id, u.name) for u in agents]


# ── Agent Routes ──────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
@agent_required
def list_projects():
    status_filter = request.args.get("status", "")
    hospital_filter = request.args.get("hospital_id", type=int)
    page = request.args.get("page", 1, type=int)

    query = Project.query.options(joinedload(Project.hospital))

    if status_filter:
        query = query.filter(Project.status == status_filter)
    if hospital_filter:
        query = query.filter(Project.hospital_id == hospital_filter)

    query = query.order_by(Project.updated_at.desc())
    pagination = query.paginate(page=page, per_page=20, error_out=False)
    projects = pagination.items

    # Batch-compute task totals and done counts in 1 query instead of 2×N
    project_ids = [p.id for p in projects]
    if project_ids:
        task_rows = (
            db.session.query(
                ProjectTask.project_id,
                func.count(ProjectTask.id).label("total"),
                func.sum(db.case((ProjectTask.status == "done", 1), else_=0)).label("done"),
            )
            .filter(ProjectTask.project_id.in_(project_ids))
            .group_by(ProjectTask.project_id)
            .all()
        )
        task_stats = {r.project_id: (r.total, r.done or 0) for r in task_rows}
    else:
        task_stats = {}

    hospitals = Hospital.query.filter_by(active=True).order_by(Hospital.name).all()

    return render_template(
        "projects/agent/list.html",
        projects=projects,
        pagination=pagination,
        task_stats=task_stats,
        status_filter=status_filter,
        hospital_filter=hospital_filter,
        hospitals=hospitals,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@agent_required
def new_project():
    form = ProjectForm()
    form.hospital_id.choices = _hospital_choices()

    if form.validate_on_submit():
        project = Project(
            name=form.name.data,
            description=form.description.data,
            hospital_id=form.hospital_id.data,
            status=form.status.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            is_customer_visible=form.is_customer_visible.data,
            created_by=current_user.id,
        )
        db.session.add(project)
        db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/agent/form.html", form=form, project=None)


@bp.route("/project/<int:project_id>")
@login_required
@agent_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    milestones = project.milestones.all()
    tasks = project.tasks.all()
    comments = project.comments.all()
    comment_form = CommentForm()
    templates = ProjectTemplate.query.order_by(ProjectTemplate.name).all()

    gantt_data = _build_gantt_data(project, tasks, milestones)

    requirements = project.requirements.all()
    top_level_tasks = [t for t in tasks if t.parent_id is None]
    agents = User.query.filter(User.role.in_(["agent", "admin"]), User.active == True).order_by(User.name).all()

    return render_template(
        "projects/agent/detail.html",
        project=project,
        milestones=milestones,
        tasks=tasks,
        top_level_tasks=top_level_tasks,
        comments=comments,
        comment_form=comment_form,
        templates=templates,
        gantt_data=gantt_data,
        requirements=requirements,
        req_types=REQ_TYPES,
        agents=agents,
        today=date.today(),
    )


def _build_gantt_data(project, tasks, milestones):
    """Return JSON string with tasks and milestones for the ECharts Gantt chart."""
    proj_start = project.start_date or date.today()
    gantt_tasks = []
    for t in tasks:
        if not t.due_date:
            continue
        gantt_tasks.append({
            "title": t.title,
            "start": proj_start.isoformat(),
            "end": t.due_date.isoformat(),
            "status": t.status,
            "assignee": t.assignee.name if t.assignee else None,
        })
    gantt_milestones = [
        {"name": ms.name, "date": ms.due_date.isoformat(), "done": ms.status == "completed"}
        for ms in milestones if ms.due_date
    ]
    return json.dumps({"tasks": gantt_tasks, "milestones": gantt_milestones})


@bp.route("/project/<int:project_id>/toggle-gantt", methods=["POST"])
@login_required
@agent_required
def toggle_gantt(project_id):
    project = Project.query.get_or_404(project_id)
    project.is_gantt_visible = not project.is_gantt_visible
    db.session.commit()
    state = "shown to" if project.is_gantt_visible else "hidden from"
    flash(f"Gantt chart {state} customers.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))


@bp.route("/project/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
@agent_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    form = ProjectForm(obj=project)
    form.hospital_id.choices = _hospital_choices()

    if form.validate_on_submit():
        project.name = form.name.data
        project.description = form.description.data
        project.hospital_id = form.hospital_id.data
        project.status = form.status.data
        project.start_date = form.start_date.data
        project.end_date = form.end_date.data
        project.is_customer_visible = form.is_customer_visible.data
        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/agent/form.html", form=form, project=project)


@bp.route("/project/<int:project_id>/delete", methods=["POST"])
@login_required
@agent_required
def delete_project(project_id):
    if not current_user.is_admin:
        abort(403)
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted.", "success")
    return redirect(url_for("projects.list_projects"))


# ── Milestone Routes ──────────────────────────────────────────────────────────

@bp.route("/project/<int:project_id>/milestones/new", methods=["GET", "POST"])
@login_required
@agent_required
def new_milestone(project_id):
    project = Project.query.get_or_404(project_id)
    form = MilestoneForm()

    if form.validate_on_submit():
        ms = ProjectMilestone(
            project_id=project.id,
            name=form.name.data,
            description=form.description.data,
            due_date=form.due_date.data,
            status=form.status.data,
        )
        db.session.add(ms)
        db.session.commit()
        flash("Milestone added.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/agent/milestone_form.html", form=form, project=project, milestone=None)


@bp.route("/project/<int:project_id>/milestones/<int:ms_id>/toggle", methods=["POST"])
@login_required
@agent_required
def toggle_milestone(project_id, ms_id):
    ms = ProjectMilestone.query.filter_by(id=ms_id, project_id=project_id).first_or_404()
    ms.status = "completed" if ms.status == "pending" else "pending"
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "status": ms.status})
    flash("Milestone status updated.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))


@bp.route("/project/<int:project_id>/milestones/<int:ms_id>/delete", methods=["POST"])
@login_required
@agent_required
def delete_milestone(project_id, ms_id):
    ms = ProjectMilestone.query.filter_by(id=ms_id, project_id=project_id).first_or_404()
    db.session.delete(ms)
    db.session.commit()
    flash("Milestone deleted.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))


# ── Task Routes ───────────────────────────────────────────────────────────────

@bp.route("/project/<int:project_id>/tasks/new", methods=["GET", "POST"])
@login_required
@agent_required
def new_project_task(project_id):
    project = Project.query.get_or_404(project_id)
    form = ProjectTaskForm()
    form.assigned_to.choices = _agent_choices()

    if form.validate_on_submit():
        assigned = form.assigned_to.data if form.assigned_to.data else None
        if assigned == 0:
            assigned = None
        task = ProjectTask(
            project_id=project.id,
            title=form.title.data,
            description=form.description.data,
            assigned_to=assigned,
            priority=form.priority.data,
            status=form.status.data,
            due_date=form.due_date.data,
        )
        db.session.add(task)
        db.session.commit()
        flash("Task added.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/agent/task_form.html", form=form, project=project, task=None)


@bp.route("/project/<int:project_id>/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
@agent_required
def edit_project_task(project_id, task_id):
    project = Project.query.get_or_404(project_id)
    task = ProjectTask.query.filter_by(id=task_id, project_id=project_id).first_or_404()
    form = ProjectTaskForm(obj=task)
    form.assigned_to.choices = _agent_choices()

    if form.validate_on_submit():
        assigned = form.assigned_to.data if form.assigned_to.data else None
        if assigned == 0:
            assigned = None
        task.title = form.title.data
        task.description = form.description.data
        task.assigned_to = assigned
        task.priority = form.priority.data
        task.status = form.status.data
        task.due_date = form.due_date.data
        db.session.commit()
        flash("Task updated.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/agent/task_form.html", form=form, project=project, task=task)


@bp.route("/project/<int:project_id>/tasks/<int:task_id>/status", methods=["POST"])
@login_required
@agent_required
def update_task_status(project_id, task_id):
    task = ProjectTask.query.filter_by(id=task_id, project_id=project_id).first_or_404()
    new_status = request.form.get("status", "")
    if new_status in ("todo", "in_progress", "done"):
        task.status = new_status
        db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "status": task.status})
    return redirect(url_for("projects.project_detail", project_id=project_id))


@bp.route("/project/<int:project_id>/apply-template", methods=["POST"])
@login_required
@agent_required
def apply_template(project_id):
    project = Project.query.get_or_404(project_id)
    tmpl_id = request.form.get("template_id", type=int)
    tmpl = ProjectTemplate.query.get_or_404(tmpl_id)
    _instantiate_template(project, tmpl)
    db.session.commit()
    flash(f'Template "{tmpl.name}" applied — tasks and requirements added.', "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))


# ── Comment Routes (Agent) ────────────────────────────────────────────────────

@bp.route("/project/<int:project_id>/comment", methods=["POST"])
@login_required
@agent_required
def post_comment(project_id):
    project = Project.query.get_or_404(project_id)
    form = CommentForm()
    if form.validate_on_submit():
        comment = ProjectComment(
            project_id=project.id,
            author_id=current_user.id,
            body=form.body.data,
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment posted.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))


# ── Portal Routes (Customer) ──────────────────────────────────────────────────

@bp.route("/portal")
@login_required
@customer_required
def portal_list():
    projects = (
        Project.query.filter_by(
            is_customer_visible=True,
            hospital_id=current_user.hospital_id,
        )
        .order_by(Project.updated_at.desc())
        .all()
    )
    project_ids = [p.id for p in projects]
    if project_ids:
        task_rows = (
            db.session.query(
                ProjectTask.project_id,
                func.count(ProjectTask.id).label("total"),
                func.sum(db.case((ProjectTask.status == "done", 1), else_=0)).label("done"),
            )
            .filter(ProjectTask.project_id.in_(project_ids))
            .group_by(ProjectTask.project_id)
            .all()
        )
        task_stats = {r.project_id: (r.total, r.done or 0) for r in task_rows}
    else:
        task_stats = {}
    return render_template("projects/portal/list.html", projects=projects, task_stats=task_stats)


@bp.route("/portal/<int:project_id>")
@login_required
@customer_required
def portal_detail(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.is_customer_visible or project.hospital_id != current_user.hospital_id:
        abort(403)

    milestones = project.milestones.all()
    tasks = project.tasks.all()
    top_level_tasks = [t for t in tasks if t.parent_id is None]
    requirements = project.requirements.all()
    comments = project.comments.all()
    comment_form = CommentForm()
    gantt_data = _build_gantt_data(project, tasks, milestones) if project.is_gantt_visible else None

    return render_template(
        "projects/portal/detail.html",
        project=project,
        milestones=milestones,
        tasks=tasks,
        top_level_tasks=top_level_tasks,
        requirements=requirements,
        comments=comments,
        comment_form=comment_form,
        gantt_data=gantt_data,
    )


@bp.route("/portal/<int:project_id>/comment", methods=["POST"])
@login_required
@customer_required
def portal_comment(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.is_customer_visible or project.hospital_id != current_user.hospital_id:
        abort(403)

    form = CommentForm()
    if form.validate_on_submit():
        comment = ProjectComment(
            project_id=project.id,
            author_id=current_user.id,
            body=form.body.data,
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comment posted.", "success")
    return redirect(url_for("projects.portal_detail", project_id=project_id))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _instantiate_template(project, tmpl):
    """Create ProjectTasks (with subtasks) and ProjectRequirements from a template."""
    # Only top-level template tasks; subtasks carry parent_id
    top_tasks = [t for t in tmpl.tasks if t.parent_id is None]
    id_map = {}  # template_task.id → new ProjectTask.id

    for tt in sorted(top_tasks, key=lambda x: x.order):
        pt = ProjectTask(
            project_id=project.id,
            title=tt.title,
            description=tt.description,
            priority=tt.default_priority,
            status="todo",
        )
        db.session.add(pt)
        db.session.flush()
        id_map[tt.id] = pt.id

        for sub in sorted(tt.subtasks, key=lambda x: x.order):
            ps = ProjectTask(
                project_id=project.id,
                parent_id=pt.id,
                title=sub.title,
                description=sub.description,
                priority=sub.default_priority,
                status="todo",
            )
            db.session.add(ps)

    for tr in tmpl.requirements:
        pr = ProjectRequirement(
            project_id=project.id,
            title=tr.title,
            description=tr.description,
            req_type=tr.req_type,
            status="pending",
        )
        db.session.add(pr)

    project.template_id = tmpl.id


# ── Start Project from Hospital ────────────────────────────────────────────────

@bp.route("/start/<int:hospital_id>", methods=["POST"])
@login_required
@agent_required
def start_project(hospital_id):
    from app.models.hospital import Hospital
    hospital = Hospital.query.get_or_404(hospital_id)
    tmpl_id = request.form.get("template_id", type=int)
    name = request.form.get("name", "").strip()

    if not tmpl_id or not name:
        flash("Project name and template are required.", "error")
        return redirect(url_for("admin.hospital_detail", hospital_id=hospital_id, tab="projects"))

    tmpl = ProjectTemplate.query.get_or_404(tmpl_id)
    project = Project(
        hospital_id=hospital_id,
        name=name,
        status="planning",
        is_customer_visible=False,
        created_by=current_user.id,
    )
    db.session.add(project)
    db.session.flush()
    _instantiate_template(project, tmpl)
    db.session.commit()
    flash(f'Project "{name}" created with {len(tmpl.tasks)} tasks.', "success")
    return redirect(url_for("projects.project_detail", project_id=project.id))


# ── Requirements (Agent) ───────────────────────────────────────────────────────

@bp.route("/project/<int:project_id>/requirements/add", methods=["POST"])
@login_required
@agent_required
def requirement_add(project_id):
    from app.services.email_outbound import notify_requirement_assigned
    project = Project.query.get_or_404(project_id)

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip() or None
    req_type = request.form.get("req_type", "provide")
    due_date_str = request.form.get("due_date", "").strip()
    assigned_user_id = request.form.get("assigned_to_id", type=int)
    assigned_email = request.form.get("assigned_to_email", "").strip() or None
    assigned_agent_id = request.form.get("assigned_agent_id", type=int)

    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("projects.project_detail", project_id=project_id, tab="requirements"))

    from datetime import date as date_type
    due_date = None
    if due_date_str:
        try:
            due_date = date_type.fromisoformat(due_date_str)
        except ValueError:
            pass

    req = ProjectRequirement(
        project_id=project_id,
        title=title,
        description=description,
        req_type=req_type if req_type in ("provide", "approve", "question") else "provide",
        status="pending",
        assigned_to_id=assigned_user_id or None,
        assigned_to_email=assigned_email if not assigned_user_id else None,
        assigned_agent_id=assigned_agent_id or None,
        due_date=due_date,
    )
    db.session.add(req)
    db.session.flush()

    notify_requirement_assigned(req)
    req.email_sent = True
    db.session.commit()
    flash("Requirement added and assignee notified.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id, tab="requirements"))


@bp.route("/project/<int:project_id>/requirements/<int:req_id>/edit", methods=["POST"])
@login_required
@agent_required
def requirement_edit(project_id, req_id):
    req = ProjectRequirement.query.filter_by(id=req_id, project_id=project_id).first_or_404()

    req.title = request.form.get("title", req.title).strip()
    req.description = request.form.get("description", "").strip() or None
    req.req_type = request.form.get("req_type", req.req_type)
    req.status = request.form.get("status", req.status)

    due_date_str = request.form.get("due_date", "").strip()
    if due_date_str:
        from datetime import date as date_type
        try:
            req.due_date = date_type.fromisoformat(due_date_str)
        except ValueError:
            pass
    else:
        req.due_date = None

    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "status": req.status})
    flash("Requirement updated.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id, tab="requirements"))


@bp.route("/project/<int:project_id>/requirements/<int:req_id>/delete", methods=["POST"])
@login_required
@agent_required
def requirement_delete(project_id, req_id):
    req = ProjectRequirement.query.filter_by(id=req_id, project_id=project_id).first_or_404()
    db.session.delete(req)
    db.session.commit()
    flash("Requirement deleted.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id, tab="requirements"))


# ── Requirements (Customer portal) ────────────────────────────────────────────

@bp.route("/portal/<int:project_id>/requirements/<int:req_id>/respond", methods=["POST"])
@login_required
@customer_required
def requirement_respond(project_id, req_id):
    project = Project.query.get_or_404(project_id)
    if not project.is_customer_visible or project.hospital_id != current_user.hospital_id:
        abort(403)

    req = ProjectRequirement.query.filter_by(id=req_id, project_id=project_id).first_or_404()
    response_text = request.form.get("response_text", "").strip()
    action = request.form.get("action", "submit")  # submit | approve | reject

    if response_text:
        req.response_text = response_text

    if action == "approve":
        req.status = "approved"
    elif action == "reject":
        req.status = "rejected"
    else:
        req.status = "submitted"

    db.session.commit()
    flash("Response submitted.", "success")
    return redirect(url_for("projects.portal_detail", project_id=project_id))


# ── Project task subtask (quick add inline) ────────────────────────────────────

@bp.route("/project/<int:project_id>/tasks/<int:task_id>/subtask", methods=["POST"])
@login_required
@agent_required
def add_subtask(project_id, task_id):
    parent = ProjectTask.query.filter_by(id=task_id, project_id=project_id).first_or_404()
    title = request.form.get("title", "").strip()
    if not title:
        flash("Subtask title required.", "error")
        return redirect(url_for("projects.project_detail", project_id=project_id))

    sub = ProjectTask(
        project_id=project_id,
        parent_id=parent.id,
        title=title,
        priority=parent.priority,
        status="todo",
    )
    db.session.add(sub)
    db.session.commit()
    return redirect(url_for("projects.project_detail", project_id=project_id))


# ── Project complete → auto-hide ───────────────────────────────────────────────

@bp.route("/project/<int:project_id>/complete", methods=["POST"])
@login_required
@agent_required
def complete_project(project_id):
    project = Project.query.get_or_404(project_id)
    project.status = "completed"
    project.is_customer_visible = False
    db.session.commit()
    flash("Project marked complete and hidden from customer portal.", "success")
    return redirect(url_for("projects.project_detail", project_id=project_id))
