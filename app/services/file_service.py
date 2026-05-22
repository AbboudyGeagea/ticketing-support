import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "gif", "txt", "csv", "zip"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file, ticket_id):
    """Save uploaded file. Returns (stored_filename, original_name, mimetype, size) or raises ValueError."""
    if not file or not file.filename:
        raise ValueError("No file provided")
    if not allowed_file(file.filename):
        raise ValueError("File type not allowed")
    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4()}.{ext}"
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(ticket_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)
    file.save(file_path)
    size = os.path.getsize(file_path)
    mimetype = file.mimetype or "application/octet-stream"
    return stored_name, original_name, mimetype, size


def delete_attachment(ticket_id, stored_filename):
    """Delete file from disk. Silently ignores if not found."""
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], str(ticket_id), stored_filename)
    if os.path.exists(path):
        os.remove(path)
