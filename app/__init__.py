from datetime import datetime
from flask import Flask
from config import Config
from app.extensions import db, login_manager, migrate, csrf, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    from app.models import product  # noqa: F401 — product defines hospital_products table first
    from app.models import user, hospital, ticket, task, attachment, project  # noqa: F401
    from app.models.task import TaskChecklist, TimeEntry, TaskDependency, Sprint  # noqa: F401
    from app.models import canned_response, assignment_rule, saved_filter, csat_feedback, webhook_config  # noqa: F401
    from app.models import kb_article, ticket_template, sla_policy  # noqa: F401
    from app.models import shared_installation, ticket_status  # noqa: F401

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.portal import bp as portal_bp
    from app.blueprints.agent import bp as agent_bp
    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.reports import bp as reports_bp
    from app.blueprints.projects import bp as projects_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(portal_bp, url_prefix="/portal")
    app.register_blueprint(agent_bp, url_prefix="/agent")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(projects_bp, url_prefix="/projects")

    from flask import redirect, url_for

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    @app.route("/health")
    def health():
        from flask import jsonify
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok", "db": "ok"}), 200
        except Exception as e:
            return jsonify({"status": "error", "db": str(e)}), 503

    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow()}

    @app.context_processor
    def inject_ticket_statuses():
        try:
            from app.models.ticket_status import TicketStatus
            statuses = TicketStatus.query.order_by(TicketStatus.order).all()
            return {"ticket_status_map": {s.slug: s for s in statuses}}
        except Exception:
            return {"ticket_status_map": {}}

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template("errors/500.html"), 500

    _register_cli(app)

    return app


def _register_cli(app):
    import click

    @app.cli.command("seed-admin")
    @click.argument("email")
    @click.argument("name")
    @click.argument("password")
    def seed_admin(email, name, password):
        """Create an initial admin user. Usage: flask seed-admin admin@example.com 'Admin Name' password"""
        from app.models.user import User
        if User.query.filter_by(email=email).first():
            click.echo("User already exists.")
            return
        u = User(email=email, name=name, role="admin", active=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Admin user '{name}' created.")
