"""Preventive maintenance (PM). Internal only: every route requires an agent
(agent / admin / viewer); customers never reach any of this."""
from datetime import date, timedelta
from functools import wraps

from flask import (
    render_template, redirect, url_for, flash, request, abort, send_file,
    send_from_directory, jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.blueprints.pm import bp
from app.extensions import db
from app.models.hospital import Hospital
from app.models.product import Product
from app.models.user import User
from app.models.pm import (
    PMCheck, PMCheckField, PMCheckup, PMResult, PMReading, PMAttachment,
    PM_STATUSES, PM_FLAGGED, PM_STATUS_LABELS, PM_ATTENTION, PM_ALERT,
    CHECKUP_SUBMITTED, FIELD_TYPES, FIELD_TYPE_LABELS, FIELD_TEXT,
    DIRECTION_ABOVE, DIRECTION_BELOW,
)
from app.services import pm_service


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_agent:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _agents():
    return (
        User.query.filter(User.role.in_(["agent", "admin"]), User.active == True)  # noqa: E712
        .order_by(User.name)
        .all()
    )


def _safe_next(default):
    nxt = request.form.get("next") or request.args.get("next") or ""
    return nxt if nxt.startswith("/pm") else default


def _parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


# ── Overview ──────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
@agent_required
def overview():
    today = pm_service.local_today()
    rows, skipped = pm_service.overview(today)
    state_counts = {}
    for row in rows:
        state_counts[row.state] = state_counts.get(row.state, 0) + 1
    state_filter = request.args.get("state", "")
    shown = [r for r in rows if r.state == state_filter] if state_filter else rows

    open_counts = dict(
        db.session.query(PMResult.status, func.count(PMResult.id))
        .join(PMCheckup)
        .filter(
            PMCheckup.status == CHECKUP_SUBMITTED,
            PMResult.status.in_(PM_FLAGGED),
            PMResult.resolved_at.is_(None),
        )
        .group_by(PMResult.status)
        .all()
    )
    recent = (
        PMCheckup.query
        .options(joinedload(PMCheckup.hospital), joinedload(PMCheckup.performer),
                 selectinload(PMCheckup.results))
        .order_by(PMCheckup.check_date.desc(), PMCheckup.id.desc())
        .limit(15)
        .all()
    )
    return render_template(
        "pm/overview.html", rows=shown, all_count=len(rows), state_counts=state_counts,
        state_filter=state_filter, skipped=skipped, open_counts=open_counts,
        recent=recent, agents=_agents(), today=today,
    )


@bp.route("/hospitals/<int:hospital_id>/owner", methods=["POST"])
@login_required
@agent_required
def set_owner(hospital_id):
    Hospital.query.get_or_404(hospital_id)
    owner_id = request.form.get("owner_id", type=int) or None
    if owner_id and not User.query.filter(User.id == owner_id, User.role.in_(["agent", "admin"])).first():
        abort(400)
    pm_service.set_owner(hospital_id, owner_id)
    flash("Responsible agent updated.", "success")
    return redirect(url_for("pm.overview", state=request.form.get("state") or None))


# ── Create ────────────────────────────────────────────────────────────────────

@bp.route("/new", methods=["GET", "POST"])
@login_required
@agent_required
def new_checkup():
    today = pm_service.local_today()
    if request.method == "POST":
        hospital = Hospital.query.get_or_404(request.form.get("hospital_id", type=int) or 0)
        check_date = _parse_date(request.form.get("check_date")) or today
        draft = PMCheckup.query.filter_by(hospital_id=hospital.id, status="draft").first()
        if draft:
            flash(f"{hospital.name} already has a draft checkup — continuing it.", "info")
            return redirect(url_for("pm.checkup_detail", checkup_id=draft.id))
        if not pm_service.hospital_plan(hospital):
            flash(f"{hospital.name} has no products with PM checks. Add checks under Admin → PM Checks.", "warning")
            return redirect(url_for("pm.new_checkup"))
        checkup = pm_service.create_checkup(hospital, check_date, current_user)
        return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id))

    rows, _ = pm_service.overview(today)
    return render_template(
        "pm/new.html", rows=rows, today=today,
        selected_id=request.args.get("hospital_id", type=int),
    )


# ── Checkup: edit draft / view report ─────────────────────────────────────────

def _load_checkup(checkup_id):
    return (
        PMCheckup.query
        .options(
            joinedload(PMCheckup.hospital), joinedload(PMCheckup.performer),
            selectinload(PMCheckup.results).selectinload(PMResult.readings),
            selectinload(PMCheckup.results).selectinload(PMResult.attachments),
            selectinload(PMCheckup.results).joinedload(PMResult.product),
            selectinload(PMCheckup.results).joinedload(PMResult.resolver),
            selectinload(PMCheckup.results).joinedload(PMResult.task),
        )
        .filter(PMCheckup.id == checkup_id)
        .first_or_404()
    )


@bp.route("/<int:checkup_id>", methods=["GET", "POST"])
@login_required
@agent_required
def checkup_detail(checkup_id):
    checkup = _load_checkup(checkup_id)

    if request.method == "POST":
        if not checkup.is_draft:
            flash("This checkup is already submitted and can't be edited.", "warning")
            return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id))
        problems = pm_service.apply_form(checkup, request.form)
        if request.form.get("action") != "submit":
            db.session.commit()
            for p in problems:
                flash(p, "warning")
            flash("Draft saved.", "success")
            return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id))

        missing = pm_service.missing_statuses(checkup)
        if problems or missing:
            db.session.commit()   # keep everything typed so far
            for p in problems:
                flash(p, "warning")
            if missing:
                names = ", ".join(f"{r.product.name} — {r.check_name}" for r in missing[:6])
                more = f" and {len(missing) - 6} more" if len(missing) > 6 else ""
                flash(f"Not submitted: {len(missing)} check(s) still need a status ({names}{more}). "
                      f"Use N/A for checks that don't apply.", "warning")
            anchor = f"result-{missing[0].id}" if missing else None
            return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id, _anchor=anchor))

        alerts = pm_service.submit_checkup(checkup)
        if alerts:
            flash(f"Checkup submitted. {len(alerts)} alert(s) were emailed to the agents.", "success")
        else:
            flash("Checkup submitted.", "success")
        return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id))

    groups = pm_service.grouped_results(checkup)
    if checkup.is_draft:
        return render_template(
            "pm/checkup_form.html", checkup=checkup, groups=groups,
            previous=pm_service.previous_results(checkup),
            fields_by_id={f.id: f for f in PMCheckField.query.filter(
                PMCheckField.id.in_([rd.field_id for r in checkup.results for rd in r.readings if rd.field_id])
            ).all()},
            statuses=PM_STATUSES, status_labels=PM_STATUS_LABELS,
        )
    return render_template(
        "pm/checkup_report.html", checkup=checkup, groups=groups, counts=checkup.counts(),
        streaks=pm_service.flagged_streaks(checkup.results), agents=_agents(),
        default_deadline=pm_service.local_today() + timedelta(days=7),
    )


@bp.route("/<int:checkup_id>/delete", methods=["POST"])
@login_required
@agent_required
def checkup_delete(checkup_id):
    from app.services.file_service import delete_pm_attachment
    checkup = PMCheckup.query.get_or_404(checkup_id)
    if not checkup.is_draft:
        flash("Submitted checkups can't be deleted.", "warning")
        return redirect(url_for("pm.checkup_detail", checkup_id=checkup.id))
    for r in checkup.results:
        for att in r.attachments:
            delete_pm_attachment(checkup.id, att.filename)
    hospital_name = checkup.hospital.name
    db.session.delete(checkup)
    db.session.commit()
    flash(f"Draft checkup for {hospital_name} deleted.", "success")
    return redirect(url_for("pm.overview"))


@bp.route("/<int:checkup_id>/print")
@login_required
@agent_required
def checkup_print(checkup_id):
    checkup = _load_checkup(checkup_id)
    return render_template(
        "pm/print.html", checkup=checkup, groups=pm_service.grouped_results(checkup),
        counts=checkup.counts(),
    )


@bp.route("/<int:checkup_id>/export.xlsx")
@login_required
@agent_required
def checkup_export(checkup_id):
    checkup = _load_checkup(checkup_id)
    buf = pm_service.checkup_workbook(checkup)
    name = f"PM_{checkup.hospital.name}_{checkup.check_date:%Y-%m-%d}.xlsx".replace(" ", "_")
    return send_file(
        buf, as_attachment=True, download_name=name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Attachments (uploaded while the checkup is a draft) ───────────────────────

@bp.route("/results/<int:result_id>/attachments", methods=["POST"])
@login_required
@agent_required
def attachment_upload(result_id):
    from app.services.file_service import save_pm_attachment
    result = PMResult.query.get_or_404(result_id)
    if not result.checkup.is_draft:
        return jsonify({"error": "This checkup is submitted; files can't be added."}), 400
    saved = []
    for f in request.files.getlist("files"):
        try:
            stored, original, mimetype, size = save_pm_attachment(f, result.checkup_id)
        except ValueError as exc:
            return jsonify({"error": f"{f.filename}: {exc}"}), 400
        att = PMAttachment(result_id=result.id, uploaded_by=current_user.id, filename=stored,
                           original_name=original, mimetype=mimetype, size=size)
        db.session.add(att)
        db.session.flush()
        saved.append(att)
    db.session.commit()
    return jsonify({"files": [
        {"id": a.id, "name": a.original_name, "is_image": a.is_image,
         "url": url_for("pm.attachment_download", att_id=a.id),
         "delete_url": url_for("pm.attachment_delete", att_id=a.id)}
        for a in saved
    ]})


@bp.route("/attachments/<int:att_id>")
@login_required
@agent_required
def attachment_download(att_id):
    from app.services.file_service import pm_attachment_dir
    att = PMAttachment.query.get_or_404(att_id)
    return send_from_directory(
        pm_attachment_dir(att.result.checkup_id), att.filename,
        download_name=att.original_name, as_attachment=not att.is_image,
    )


@bp.route("/attachments/<int:att_id>/delete", methods=["POST"])
@login_required
@agent_required
def attachment_delete(att_id):
    from app.services.file_service import delete_pm_attachment
    att = PMAttachment.query.get_or_404(att_id)
    checkup = att.result.checkup
    if not checkup.is_draft:
        return jsonify({"error": "This checkup is submitted; files can't be removed."}), 400
    delete_pm_attachment(checkup.id, att.filename)
    db.session.delete(att)
    db.session.commit()
    return jsonify({"ok": True})


# ── Findings ──────────────────────────────────────────────────────────────────

def _findings_filters():
    args = request.args
    statuses = [s for s in args.getlist("status") if s in PM_STATUSES]
    if "f" not in args:            # first visit: open issues only
        statuses = [PM_ATTENTION, PM_ALERT]
    state = args.get("state", "open")
    if state not in ("open", "resolved", "all"):
        state = "open"
    return {
        "statuses": statuses,
        "state": state,
        "hospital_id": args.get("hospital_id", 0, type=int),
        "product_id": args.get("product_id", 0, type=int),
        "check": args.get("check", "").strip(),
        "date_from": _parse_date(args.get("date_from")),
        "date_to": _parse_date(args.get("date_to")),
    }


def _findings_query(flt):
    q = (
        PMResult.query.join(PMCheckup)
        .filter(PMCheckup.status == CHECKUP_SUBMITTED)
        .options(
            joinedload(PMResult.checkup).joinedload(PMCheckup.hospital),
            joinedload(PMResult.product), joinedload(PMResult.resolver),
            joinedload(PMResult.task), selectinload(PMResult.readings),
            selectinload(PMResult.attachments),
        )
    )
    if flt["statuses"]:
        q = q.filter(PMResult.status.in_(flt["statuses"]))
    if flt["state"] == "open":
        q = q.filter(PMResult.resolved_at.is_(None))
    elif flt["state"] == "resolved":
        q = q.filter(PMResult.resolved_at.isnot(None))
    if flt["hospital_id"]:
        q = q.filter(PMCheckup.hospital_id == flt["hospital_id"])
    if flt["product_id"]:
        q = q.filter(PMResult.product_id == flt["product_id"])
    if flt["check"]:
        q = q.filter(PMResult.check_name == flt["check"])
    if flt["date_from"]:
        q = q.filter(PMCheckup.check_date >= flt["date_from"])
    if flt["date_to"]:
        q = q.filter(PMCheckup.check_date <= flt["date_to"])
    return q.order_by(PMCheckup.check_date.desc(), PMCheckup.id.desc(), PMResult.sort_order)


@bp.route("/findings")
@login_required
@agent_required
def findings():
    flt = _findings_filters()
    query = _findings_query(flt)

    if request.args.get("format") == "xlsx":
        results = query.all()
        buf = pm_service.findings_workbook(results, pm_service.flagged_streaks(results))
        return send_file(
            buf, as_attachment=True,
            download_name=f"PM_findings_{pm_service.local_today():%Y-%m-%d}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    page = query.paginate(page=request.args.get("page", 1, type=int), per_page=50, error_out=False)
    check_names = [n for (n,) in db.session.query(PMResult.check_name).distinct().order_by(PMResult.check_name)]
    return render_template(
        "pm/findings.html", page=page, flt=flt,
        streaks=pm_service.flagged_streaks(page.items),
        hospitals=Hospital.query.filter_by(active=True).order_by(Hospital.name).all(),
        products=Product.query.order_by(Product.name).all(),
        check_names=check_names, statuses=PM_STATUSES, status_labels=PM_STATUS_LABELS,
        agents=_agents(), default_deadline=pm_service.local_today() + timedelta(days=7),
        export_args={**request.args.to_dict(flat=False), "format": "xlsx"},
        page_args={k: v for k, v in request.args.to_dict(flat=False).items() if k != "page"},
    )


def _flagged_open_result(result_id):
    result = PMResult.query.get_or_404(result_id)
    if result.checkup.status != CHECKUP_SUBMITTED or result.status not in PM_FLAGGED:
        abort(400)
    return result


@bp.route("/results/<int:result_id>/resolve", methods=["POST"])
@login_required
@agent_required
def resolve(result_id):
    result = _flagged_open_result(result_id)
    back = _safe_next(url_for("pm.findings"))
    if result.resolved_at:
        flash("That finding was already resolved.", "info")
        return redirect(back)
    pm_service.resolve_result(result, current_user, (request.form.get("note") or "").strip())
    flash(f"Resolved: {result.checkup.hospital.name} — {result.check_name}. "
          f"The original status ({result.status_label}) is kept in the report.", "success")
    return redirect(back)


@bp.route("/results/<int:result_id>/task", methods=["POST"])
@login_required
@agent_required
def create_task(result_id):
    result = _flagged_open_result(result_id)
    back = _safe_next(url_for("pm.findings"))
    if result.task_id:
        flash("A follow-up task already exists for that finding.", "info")
        return redirect(back)
    assignee_id = request.form.get("assigned_to", type=int)
    if not assignee_id or not User.query.filter(User.id == assignee_id, User.role.in_(["agent", "admin"])).first():
        flash("Choose who the follow-up task is for.", "warning")
        return redirect(back)
    title = (request.form.get("title") or "").strip() or \
        f"PM: {result.check_name} — {result.checkup.hospital.name} ({result.product.name})"
    task = pm_service.create_followup_task(
        result, current_user, assignee_id, _parse_date(request.form.get("deadline")), title,
    )
    flash(f"Follow-up task created for {task.assignee.name}. Completing it will resolve the finding.", "success")
    return redirect(back)


# ── Admin: check catalog ──────────────────────────────────────────────────────

@bp.route("/admin/checks")
@login_required
@agent_required
def catalog():
    checks = (
        PMCheck.query.options(joinedload(PMCheck.products), joinedload(PMCheck.fields))
        .order_by(PMCheck.sort_order, PMCheck.name)
        .all()
    )
    used = {cid for (cid,) in db.session.query(PMResult.check_id).distinct()}
    return render_template("pm/catalog.html", checks=checks, used=used)


def _save_check(check):
    form = request.form
    name = (form.get("name") or "").strip()
    if not name:
        return "Name is required."
    check.name = name[:200]
    check.description = (form.get("description") or "").strip() or None
    check.sort_order = form.get("sort_order", 0, type=int) or 0
    check.active = form.get("active") == "on"
    product_ids = [int(x) for x in form.getlist("product_ids") if x.isdigit()]
    check.products = Product.query.filter(Product.id.in_(product_ids)).all() if product_ids else []

    def _num(v):
        v = (v or "").strip().replace(",", ".")
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    existing = {f.id: f for f in check.fields}
    keep = []
    rows = zip(
        form.getlist("field_id"), form.getlist("field_label"), form.getlist("field_type"),
        form.getlist("field_unit"), form.getlist("field_direction"),
        form.getlist("field_attention"), form.getlist("field_alert"),
    )
    for order, (fid, label, ftype, unit, direction, attention, alert) in enumerate(rows, start=1):
        label = (label or "").strip()
        if not label:
            continue
        field = existing.get(int(fid)) if fid.isdigit() else None
        if field is None:
            field = PMCheckField()
            check.fields.append(field)
        field.label = label[:100]
        field.field_type = ftype if ftype in FIELD_TYPES else FIELD_TEXT
        field.unit = (unit or "").strip()[:20] or None
        field.direction = direction if direction in (DIRECTION_ABOVE, DIRECTION_BELOW) else DIRECTION_ABOVE
        numeric = field.field_type != FIELD_TEXT
        field.attention_threshold = _num(attention) if numeric else None
        field.alert_threshold = _num(alert) if numeric else None
        field.sort_order = order
        keep.append(field)
    for fid, field in existing.items():
        if field not in keep:
            # Past readings keep their own label/unit snapshot; just unlink them.
            PMReading.query.filter_by(field_id=fid).update({"field_id": None})
            check.fields.remove(field)
    return None


def _catalog_form(check):
    if request.method == "POST":
        # A new check joins the session only once it's filled in, so the
        # product lookup inside _save_check can't autoflush a nameless row.
        error = _save_check(check)
        if error:
            db.session.rollback()
            flash(error, "warning")
        else:
            if check.id is None:
                db.session.add(check)
            db.session.commit()
            flash(f'Check "{check.name}" saved.', "success")
            return redirect(url_for("pm.catalog"))
    return render_template(
        "pm/catalog_form.html", check=check,
        products=Product.query.order_by(Product.name).all(),
        field_types=FIELD_TYPES, field_type_labels=FIELD_TYPE_LABELS,
    )


@bp.route("/admin/checks/new", methods=["GET", "POST"])
@login_required
@agent_required
def catalog_new():
    max_order = db.session.query(func.max(PMCheck.sort_order)).scalar() or 0
    return _catalog_form(PMCheck(active=True, sort_order=max_order + 10))


@bp.route("/admin/checks/<int:check_id>/edit", methods=["GET", "POST"])
@login_required
@agent_required
def catalog_edit(check_id):
    return _catalog_form(PMCheck.query.get_or_404(check_id))


@bp.route("/admin/checks/<int:check_id>/delete", methods=["POST"])
@login_required
@agent_required
def catalog_delete(check_id):
    check = PMCheck.query.get_or_404(check_id)
    if PMResult.query.filter_by(check_id=check.id).count():
        flash(f'"{check.name}" is used in past checkups — deactivate it instead of deleting.', "warning")
        return redirect(url_for("pm.catalog"))
    db.session.delete(check)
    db.session.commit()
    flash(f'Check "{check.name}" deleted.', "success")
    return redirect(url_for("pm.catalog"))
