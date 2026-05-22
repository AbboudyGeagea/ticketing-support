from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class NewTicketForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(max=500)])
    product_id = SelectField("Product / Module", coerce=int, validators=[DataRequired(message="Please select a product.")])
    body = TextAreaField("Description", validators=[DataRequired()])
    priority = SelectField("Priority", choices=[
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ], default="medium")
    attachment = FileField("Attach file", validators=[
        FileAllowed(["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "gif", "txt", "csv", "zip"], "Unsupported file type")
    ])
    rustdesk_peer_id = StringField("RustDesk Device ID (optional — for remote support)", validators=[Optional(), Length(max=100)])
    submit = SubmitField("Submit Ticket")


class ReplyForm(FlaskForm):
    body = TextAreaField("Your Reply", validators=[DataRequired()])
    attachment = FileField("Attach file", validators=[
        FileAllowed(["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "gif", "txt", "csv", "zip"], "Unsupported file type")
    ])
    submit = SubmitField("Send")
