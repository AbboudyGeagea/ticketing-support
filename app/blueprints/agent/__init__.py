from flask import Blueprint

bp = Blueprint("agent", __name__, template_folder="../../templates/agent")

from app.blueprints.agent import routes  # noqa: F401, E402
