from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SelectField, BooleanField, SubmitField, DateTimeLocalField, DateField
from wtforms.validators import DataRequired, Optional, Length


class NewTicketForm(FlaskForm):
    hospital_id = SelectField("Hospital", coerce=int, validators=[DataRequired()])
    customer_id = SelectField("Reporter (optional)", coerce=int, validators=[Optional()], validate_choice=False)
    product_id = SelectField("Product", coerce=int, validators=[], validate_choice=False)
    subject = StringField("Subject", validators=[DataRequired(), Length(max=500)])
    body = TextAreaField("Description", validators=[DataRequired()])
    priority = SelectField("Priority", choices=[
        ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent"),
    ], default="medium")
    submit = SubmitField("Create Ticket")


class ReplyForm(FlaskForm):
    body = TextAreaField("Message", validators=[DataRequired()])
    is_internal = BooleanField("Internal note (not visible to customer)")
    attachment = FileField("Attach file", validators=[
        FileAllowed(["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "gif", "txt", "csv", "zip"], "Unsupported file type")
    ])
    submit = SubmitField("Send Reply")


class StatusForm(FlaskForm):
    status = SelectField("Status", choices=[
        ("new", "New"),
        ("assigned", "Assigned"),
        ("awaiting_info", "Awaiting Info"),
        ("in_progress", "In Progress"),
        ("escalated", "Escalated"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ])
    submit = SubmitField("Update Status")


class AssignForm(FlaskForm):
    agent_id = SelectField("Assign To", coerce=int)
    submit = SubmitField("Assign")


class PriorityForm(FlaskForm):
    priority = SelectField("Priority", choices=[
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ])
    submit = SubmitField("Update Priority")


class SprintForm(FlaskForm):
    name = StringField("Sprint Name", validators=[DataRequired(), Length(max=200)])
    goal = TextAreaField("Sprint Goal", validators=[Optional()])
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    status = SelectField("Status", choices=[
        ("planned", "Planned"),
        ("active", "Active"),
        ("completed", "Completed"),
    ], default="planned")
    submit = SubmitField("Save Sprint")


class TaskForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional()])
    assigned_to = SelectField("Assign To", coerce=int)
    priority = SelectField("Priority", choices=[
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ], default="medium")
    status = SelectField("Status", choices=[
        ("todo", "To Do"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
    ], default="todo")
    deadline = DateTimeLocalField("Deadline", validators=[Optional()], format="%Y-%m-%dT%H:%M")
    reminder_at = DateTimeLocalField("Reminder", validators=[Optional()], format="%Y-%m-%dT%H:%M")
    submit = SubmitField("Save Task")
