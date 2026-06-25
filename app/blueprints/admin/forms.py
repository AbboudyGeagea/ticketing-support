from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SelectMultipleField, BooleanField, SubmitField, PasswordField, IntegerField, FloatField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError, URL, NumberRange, Regexp
from app.models.user import User


class HospitalForm(FlaskForm):
    name = StringField("Hospital Name", validators=[DataRequired(), Length(max=200)])
    email_domain = StringField("Email Domain (e.g. hospital.com)", validators=[Optional(), Length(max=100)])
    address = StringField("Address", validators=[Optional(), Length(max=500)])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)])
    rustdesk_server_url = StringField("RustDesk Server URL", validators=[Optional(), Length(max=500)])
    rustdesk_server_key = StringField("RustDesk Server Key", validators=[Optional(), Length(max=200)])
    rustdesk_id = StringField("RustDesk Device ID", validators=[Optional(), Length(max=50)])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Hospital")


class ProductForm(FlaskForm):
    name = StringField("Product Name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save Product")


class CustomerUserForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=200)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Create User")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower().strip()).first():
            raise ValidationError("This email is already registered.")


class AgentForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=200)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    role = SelectField("Role", choices=[("agent", "Agent"), ("admin", "Admin"), ("viewer", "Viewer")], default="agent")
    submit = SubmitField("Create Agent")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower().strip()).first():
            raise ValidationError("This email is already registered.")


class EditUserForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(max=200)])
    active = BooleanField("Active")
    product_ids = SelectMultipleField("Product Access", coerce=int, validators=[], validate_choice=False)
    submit = SubmitField("Save Changes")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    submit = SubmitField("Reset Password")


class CannedResponseForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=300)])
    body = TextAreaField("Response Body", validators=[DataRequired()])
    is_shared = BooleanField("Shared with all agents", default=True)
    submit = SubmitField("Save")


class AssignmentRuleForm(FlaskForm):
    hospital_id = SelectField("Hospital (any = leave blank)", coerce=int, validators=[Optional()])
    product_id = SelectField("Product (any = leave blank)", coerce=int, validators=[Optional()])
    priority = SelectField("Priority (any = leave blank)", choices=[
        ("", "Any"),
        ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent"),
    ], validators=[Optional()])
    assigned_to = SelectField("Assign to Agent", coerce=int, validators=[DataRequired()])
    rule_order = IntegerField("Order (lower runs first)", default=0, validators=[NumberRange(min=0)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Rule")


class WebhookConfigForm(FlaskForm):
    url = StringField("Endpoint URL", validators=[DataRequired(), URL(), Length(max=500)])
    secret = StringField("Signing Secret (optional)", validators=[Optional(), Length(max=200)])
    events = SelectField("Event(s)", choices=[], validators=[DataRequired()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Webhook")


class ProjectTemplateForm(FlaskForm):
    name = StringField("Template Name", validators=[DataRequired(), Length(max=300)])
    description = TextAreaField("Description", validators=[Optional()])
    submit = SubmitField("Save Template")


class KBArticleForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=500)])
    category = StringField("Category", validators=[Optional(), Length(max=100)])
    body = TextAreaField("Content (Markdown supported)", validators=[DataRequired()])
    is_published = BooleanField("Published (visible to customers)", default=False)
    submit = SubmitField("Save Article")


class TicketTemplateForm(FlaskForm):
    name = StringField("Template Name", validators=[DataRequired(), Length(max=200)])
    description = StringField("Short description", validators=[Optional(), Length(max=500)])
    category = StringField("Category (e.g. Hardware, Software)", validators=[Optional(), Length(max=100)])
    subject = StringField("Default Subject", validators=[DataRequired(), Length(max=500)])
    body = TextAreaField("Default Description", validators=[DataRequired()])
    default_priority = SelectField("Default Priority", choices=[
        ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent"),
    ], default="medium")
    product_id = SelectField("Product (optional)", coerce=int, validators=[Optional()])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Template")


class TicketStatusForm(FlaskForm):
    label = StringField("Display Label", validators=[DataRequired(), Length(max=100)])
    color = StringField("Color (hex)", validators=[DataRequired(), Length(min=4, max=7)])
    submit = SubmitField("Save")


class NewTicketStatusForm(FlaskForm):
    slug = StringField("Slug", validators=[
        DataRequired(), Length(max=50),
        Regexp(r'^[a-z0-9_]+$', message="Lowercase letters, numbers, and underscores only."),
    ])
    label = StringField("Display Label", validators=[DataRequired(), Length(max=100)])
    color = StringField("Color (hex)", validators=[DataRequired(), Length(min=4, max=7)])
    submit = SubmitField("Create Status")


class SharedInstallationForm(FlaskForm):
    name = StringField("Installation Name", validators=[DataRequired(), Length(max=200)])
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    hospital_ids = SelectMultipleField("Hospitals", coerce=int, validators=[], validate_choice=False)
    submit = SubmitField("Save")


class CredentialForm(FlaskForm):
    category = SelectField("Category", choices=[
        ("remote_desktop", "Remote Desktop"),
        ("vpn", "VPN"),
        ("network", "Network / IP"),
        ("admin_account", "Admin Account"),
        ("os_account", "OS Account"),
        ("app_access", "Application Access"),
        ("other", "Other"),
    ])
    label = StringField("Label", validators=[DataRequired(), Length(max=200)])
    username = StringField("Username / Login", validators=[Optional(), Length(max=200)])
    password = PasswordField("Password", validators=[Optional()])
    host = StringField("Host / IP Address", validators=[Optional(), Length(max=200)])
    role = StringField("Role / Function", validators=[Optional(), Length(max=200)])
    url = StringField("URL", validators=[Optional(), Length(max=500)])
    notes = TextAreaField("Notes (non-sensitive)", validators=[Optional()])
    submit = SubmitField("Save Credential")


class SLAPolicyForm(FlaskForm):
    priority = SelectField("Priority", choices=[
        ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent"),
    ], validators=[DataRequired()])
    response_hours = FloatField("First Response (hours)", validators=[DataRequired(), NumberRange(min=0.1)])
    resolve_hours = FloatField("Resolution (hours)", validators=[DataRequired(), NumberRange(min=0.1)])
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Save Policy")
