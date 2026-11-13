import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app, send_from_directory

ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "xls", "pptx", "ppt", "png", "jpg", "jpeg", "gif", "txt", "csv", "zip"}


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


def save_ticket_attachments(files, ticket_id, message_id, uploaded_by):
    """Save every non-empty upload in `files` and add a TicketAttachment row for each
    to the session (caller commits). One bad file never blocks the others.
    Returns the names of the files that could not be saved."""
    from app.extensions import db
    from app.models.attachment import TicketAttachment

    failed = []
    for file in files:
        if not file or not file.filename:
            continue
        try:
            stored_name, original_name, mimetype, size = save_attachment(file, ticket_id)
        except Exception:
            current_app.logger.exception("Attachment save failed for ticket id %s", ticket_id)
            failed.append(secure_filename(file.filename) or "file")
            continue
        db.session.add(TicketAttachment(
            ticket_id=ticket_id,
            message_id=message_id,
            uploaded_by=uploaded_by,
            filename=stored_name,
            original_name=original_name,
            mimetype=mimetype,
            size=size,
        ))
    return failed


def delete_attachment(ticket_id, stored_filename):
    """Delete file from disk. Silently ignores if not found."""
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], str(ticket_id), stored_filename)
    if os.path.exists(path):
        os.remove(path)


def save_kb_attachment(file, article_id):
    """Save a KB article attachment. PDF only. Returns (stored_filename, original_name, mimetype, size) or raises ValueError."""
    if not file or not file.filename:
        raise ValueError("No file provided")
    original_name = secure_filename(file.filename)
    if not original_name.lower().endswith(".pdf"):
        raise ValueError("Only PDF files are allowed")
    stored_name = f"{uuid.uuid4()}.pdf"
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "kb", str(article_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)
    file.save(file_path)
    size = os.path.getsize(file_path)
    mimetype = file.mimetype or "application/pdf"
    return stored_name, original_name, mimetype, size


KB_ATTACHMENT_CACHE_SECONDS = 86400


def send_kb_attachment(att, inline=False):
    """Serve a KB PDF, inline (for the viewer / browser tab) or as a download.

    Stored names are UUIDs and a replaced file gets a new attachment id, so a given URL
    never changes content: the browser may keep it for a day instead of re-downloading
    on every open. "private" keeps shared proxies from caching authenticated content.
    """
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "kb", str(att.kb_article_id))
    resp = send_from_directory(
        upload_dir, att.filename,
        as_attachment=not inline,
        download_name=att.original_name,
        mimetype="application/pdf",
        max_age=KB_ATTACHMENT_CACHE_SECONDS,
    )
    resp.cache_control.public = False
    resp.cache_control.private = True
    return resp


def delete_kb_attachment(article_id, stored_filename):
    """Delete a KB attachment file from disk. Silently ignores if not found."""
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "kb", str(article_id), stored_filename)
    if os.path.exists(path):
        os.remove(path)


def pm_attachment_dir(checkup_id):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "pm", str(checkup_id))


def save_pm_attachment(file, checkup_id):
    """Save a PM finding attachment (screenshot/log). Returns (stored_filename, original_name, mimetype, size) or raises ValueError."""
    if not file or not file.filename:
        raise ValueError("No file provided")
    if not allowed_file(file.filename):
        raise ValueError("File type not allowed")
    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4()}.{ext}"
    upload_dir = pm_attachment_dir(checkup_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)
    file.save(file_path)
    size = os.path.getsize(file_path)
    mimetype = file.mimetype or "application/octet-stream"
    return stored_name, original_name, mimetype, size


def delete_pm_attachment(checkup_id, stored_filename):
    """Delete a PM attachment file from disk. Silently ignores if not found."""
    path = os.path.join(pm_attachment_dir(checkup_id), stored_filename)
    if os.path.exists(path):
        os.remove(path)
