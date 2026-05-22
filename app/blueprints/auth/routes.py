import hmac
from datetime import datetime
from urllib.parse import urlparse
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.blueprints.auth import bp
from app.blueprints.auth.forms import LoginForm, ChangePasswordForm
from app.models.user import User
from app.extensions import db, limiter


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.active and user.check_password(form.password.data):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get("next")
            # Reject absolute URLs to prevent open-redirect
            if next_page and urlparse(next_page).netloc:
                next_page = None
            return redirect(next_page or _redirect_url(user))
        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per minute")
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(_redirect_url(current_user))

    return render_template("auth/change_password.html", form=form)


def _redirect_url(user):
    if user.is_admin or user.is_agent:
        return url_for("agent.dashboard")
    if user.is_customer:
        return url_for("portal.dashboard")
    return url_for("auth.login")


def _redirect_by_role(user):
    return redirect(_redirect_url(user))


@bp.route("/lookup", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def ticket_lookup():
    """Public route — no login required. Looks up ticket status by ref + email."""
    result = None
    error = None
    if request.method == "POST":
        ref = request.form.get("ref", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        if ref and email:
            from app.models.ticket import Ticket
            ticket = Ticket.query.filter_by(ref=ref).first()
            # Always evaluate both sides to avoid timing-based email enumeration
            creator_email = ticket.creator.email.lower() if (ticket and ticket.creator) else ""
            match = hmac.compare_digest(creator_email, email)
            if match and ticket:
                result = ticket
            else:
                error = "No ticket found with that reference and email. Check your details."
        else:
            error = "Please enter both a ticket reference and your email address."
    return render_template("auth/ticket_lookup.html", result=result, error=error)


@bp.route("/feedback/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def csat_feedback(token):
    """Public CSAT feedback route — no login required."""
    from app.models.csat_feedback import CSATFeedback
    from app.extensions import db
    from datetime import datetime

    csat = CSATFeedback.query.filter_by(token=token).first_or_404()

    if csat.submitted_at:
        return render_template("auth/feedback.html", csat=csat, already_submitted=True)

    # Pre-fill rating from query param (clicked from email)
    prefill_rating = request.args.get("rating", type=int)

    if request.method == "POST":
        rating = request.form.get("rating", type=int)
        comment = request.form.get("comment", "").strip()
        if rating and 1 <= rating <= 5:
            csat.rating = rating
            csat.comment = comment or None
            csat.submitted_at = datetime.utcnow()
            db.session.commit()
            return render_template("auth/feedback.html", csat=csat, submitted=True)
        flash("Please select a rating.", "warning")

    return render_template("auth/feedback.html", csat=csat, prefill_rating=prefill_rating,
                           already_submitted=False, submitted=False)
