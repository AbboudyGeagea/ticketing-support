from flask import Blueprint

bp = Blueprint("pm", __name__)

from app.blueprints.pm import routes  # noqa: F401, E402
