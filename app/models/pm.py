"""Preventive maintenance (PM): monthly server checkups per hospital.

PMCheck / PMCheckField are the admin-managed catalog. A PMCheckup is one visit
to a hospital; it gets one PMResult per (check, product) the hospital has, and
each result one PMReading per reading field. Names, labels and units are
snapshotted onto results/readings so old reports don't change when the catalog
is edited later.
"""
from datetime import datetime
from app.extensions import db

PM_NORMAL = "normal"
PM_ATTENTION = "attention"
PM_ALERT = "alert"
PM_NA = "na"
PM_STATUSES = [PM_NORMAL, PM_ATTENTION, PM_ALERT, PM_NA]
PM_FLAGGED = (PM_ATTENTION, PM_ALERT)
PM_STATUS_LABELS = {
    PM_NORMAL: "Normal",
    PM_ATTENTION: "Needs attention",
    PM_ALERT: "Alert",
    PM_NA: "N/A",
}

CHECKUP_DRAFT = "draft"
CHECKUP_SUBMITTED = "submitted"

FIELD_NUMBER = "number"
FIELD_PERCENT = "percent"
FIELD_TEXT = "text"
FIELD_TYPES = [FIELD_NUMBER, FIELD_PERCENT, FIELD_TEXT]
FIELD_TYPE_LABELS = {FIELD_NUMBER: "Number", FIELD_PERCENT: "Percent", FIELD_TEXT: "Text"}

# "below": flagged when the value is less than the threshold (e.g. free storage %).
# "above": flagged when the value reaches the threshold (e.g. failed commands).
DIRECTION_BELOW = "below"
DIRECTION_ABOVE = "above"

pm_check_products = db.Table(
    "pm_check_products",
    db.Column("check_id", db.Integer, db.ForeignKey("pm_checks.id"), primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id"), primary_key=True),
)


class PMHospitalSettings(db.Model):
    """Per-hospital PM settings. Kept out of `hospitals` so it adds no second
    hospitals<->users foreign-key path to the existing relationships."""
    __tablename__ = "pm_hospital_settings"

    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    hospital = db.relationship("Hospital")
    owner = db.relationship("User")


class PMCheck(db.Model):
    __tablename__ = "pm_checks"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)   # guidance shown to the engineer under the check name
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # The backref lets deleting a Product clear its pm_check_products rows.
    products = db.relationship(
        "Product", secondary=pm_check_products, order_by="Product.name", backref="pm_checks",
    )
    fields = db.relationship(
        "PMCheckField", back_populates="check",
        cascade="all, delete-orphan", order_by="PMCheckField.sort_order",
    )

    def __repr__(self):
        return f"<PMCheck {self.name}>"


class PMCheckField(db.Model):
    """A reading the engineer records for a check, optionally with thresholds."""
    __tablename__ = "pm_check_fields"

    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey("pm_checks.id"), nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default=FIELD_NUMBER)
    unit = db.Column(db.String(20))
    direction = db.Column(db.String(10), nullable=False, default=DIRECTION_ABOVE)
    attention_threshold = db.Column(db.Float, nullable=True)
    alert_threshold = db.Column(db.Float, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    check = db.relationship("PMCheck", back_populates="fields")

    @property
    def is_numeric(self):
        return self.field_type in (FIELD_NUMBER, FIELD_PERCENT)

    @property
    def has_thresholds(self):
        return self.is_numeric and (
            self.attention_threshold is not None or self.alert_threshold is not None
        )


class PMCheckup(db.Model):
    __tablename__ = "pm_checkups"

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    check_date = db.Column(db.Date, nullable=False, index=True)
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=CHECKUP_DRAFT, index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)

    hospital = db.relationship("Hospital")
    performer = db.relationship("User", foreign_keys=[performed_by])
    results = db.relationship(
        "PMResult", back_populates="checkup",
        cascade="all, delete-orphan", order_by="PMResult.id",
    )

    @property
    def is_draft(self):
        return self.status == CHECKUP_DRAFT

    def counts(self):
        out = {s: 0 for s in PM_STATUSES}
        for r in self.results:
            if r.status in out:
                out[r.status] += 1
        return out


class PMResult(db.Model):
    __tablename__ = "pm_results"
    __table_args__ = (
        db.UniqueConstraint("checkup_id", "check_id", "product_id", name="uq_pm_result_check_product"),
    )

    id = db.Column(db.Integer, primary_key=True)
    checkup_id = db.Column(db.Integer, db.ForeignKey("pm_checkups.id"), nullable=False, index=True)
    check_id = db.Column(db.Integer, db.ForeignKey("pm_checks.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    check_name = db.Column(db.String(200), nullable=False)
    check_description = db.Column(db.Text)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=True, index=True)   # NULL until chosen
    comment = db.Column(db.Text)

    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolution_note = db.Column(db.Text)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True, index=True)

    checkup = db.relationship("PMCheckup", back_populates="results")
    check = db.relationship("PMCheck")
    product = db.relationship("Product")
    resolver = db.relationship("User", foreign_keys=[resolved_by])
    task = db.relationship("Task")
    readings = db.relationship(
        "PMReading", back_populates="result",
        cascade="all, delete-orphan", order_by="PMReading.sort_order",
    )
    attachments = db.relationship(
        "PMAttachment", back_populates="result",
        cascade="all, delete-orphan", order_by="PMAttachment.created_at",
    )

    @property
    def is_flagged(self):
        return self.status in PM_FLAGGED

    @property
    def status_label(self):
        return PM_STATUS_LABELS.get(self.status, "Not set")


class PMReading(db.Model):
    __tablename__ = "pm_readings"

    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(db.Integer, db.ForeignKey("pm_results.id"), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey("pm_check_fields.id"), nullable=True)
    label = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default=FIELD_NUMBER)
    unit = db.Column(db.String(20))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    value = db.Column(db.String(500))

    result = db.relationship("PMResult", back_populates="readings")
    field = db.relationship("PMCheckField")

    @property
    def display(self):
        if not self.value:
            return ""
        if self.field_type == FIELD_PERCENT:
            return f"{self.value}%"
        return f"{self.value} {self.unit}".strip() if self.unit else self.value


class PMAttachment(db.Model):
    __tablename__ = "pm_attachments"

    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(db.Integer, db.ForeignKey("pm_results.id"), nullable=False, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(200), nullable=False)        # UUID-based stored filename
    original_name = db.Column(db.String(500), nullable=False)
    mimetype = db.Column(db.String(100))
    size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    result = db.relationship("PMResult", back_populates="attachments")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])

    @property
    def is_image(self):
        return (self.mimetype or "").startswith("image/")
