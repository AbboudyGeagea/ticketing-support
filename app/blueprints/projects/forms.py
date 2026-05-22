from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField, SubmitField, DateField
from wtforms.validators import DataRequired, Optional, Length


class ProjectForm(FlaskForm):
    name = StringField("Project Name", validators=[DataRequired(), Length(max=300)])
    description = TextAreaField("Description", validators=[Optional()])
    hospital_id = SelectField("Hospital", coerce=int, validators=[DataRequired()])
    status = SelectField(
        "Status",
        choices=[
            ("planning", "Planning"),
            ("active", "Active"),
            ("on_hold", "On Hold"),
            ("completed", "Completed"),
        ],
        default="planning",
    )
    start_date = DateField("Start Date", validators=[Optional()])
    end_date = DateField("End Date", validators=[Optional()])
    is_customer_visible = BooleanField("Visible to hospital's customers")
    submit = SubmitField("Save Project")


class MilestoneForm(FlaskForm):
    name = StringField("Milestone Name", validators=[DataRequired(), Length(max=300)])
    description = TextAreaField("Description", validators=[Optional()])
    due_date = DateField("Due Date", validators=[Optional()])
    status = SelectField(
        "Status",
        choices=[("pending", "Pending"), ("completed", "Completed")],
        default="pending",
    )
    submit = SubmitField("Save Milestone")


class ProjectTaskForm(FlaskForm):
    title = StringField("Task Title", validators=[DataRequired(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional()])
    assigned_to = SelectField("Assign To", coerce=int, validators=[Optional()])
    priority = SelectField(
        "Priority",
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        default="medium",
    )
    status = SelectField(
        "Status",
        choices=[
            ("todo", "To Do"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
        ],
        default="todo",
    )
    due_date = DateField("Due Date", validators=[Optional()])
    submit = SubmitField("Save Task")


class CommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired()])
    submit = SubmitField("Post Comment")
