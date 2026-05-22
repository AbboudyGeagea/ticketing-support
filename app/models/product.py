from datetime import datetime
from app.extensions import db

hospital_products = db.Table(
    "hospital_products",
    db.Column("hospital_id", db.Integer, db.ForeignKey("hospitals.id"), primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id"), primary_key=True),
)

user_products = db.Table(
    "user_products",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id"), primary_key=True),
)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hospitals = db.relationship("Hospital", secondary=hospital_products, back_populates="products")
    tickets = db.relationship("Ticket", back_populates="product", lazy="dynamic")

    def __repr__(self):
        return f"<Product {self.name}>"
