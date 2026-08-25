"""Hardcoded product-access -> department classification rules.

A customer's department is inferred from which of these product groups they
have access to. A customer whose access spans more than one group is left
unclassified here (could be biomedical or IT) rather than guessed at.
"""

CATEGORY_PRODUCT_NAMES = {
    "Medical Imaging": {"pacs", "vue pacs", "vue motion", "my vue", "myvue", "ris", "vue ris", "wim"},
    "Pharmacy": {"pyxis"},
    "Cathlab": {"cvis", "ibe", "xperim", "xper im"},
}


def categories_for_products(products):
    """Return the set of department categories implied by these products."""
    matched = set()
    for p in products:
        name = p.name.strip().lower()
        for category, names in CATEGORY_PRODUCT_NAMES.items():
            if name in names:
                matched.add(category)
                break
    return matched


def department_category_for_products(products):
    """Return the single department category implied by these products, or None
    if none of them match a known category, or if they span more than one."""
    matched = categories_for_products(products)
    return next(iter(matched)) if len(matched) == 1 else None


def get_or_create_department(category):
    from app.extensions import db
    from app.models.department import Department

    dept = Department.query.filter_by(name=category).first()
    if dept is None:
        dept = Department(name=category, active=True)
        db.session.add(dept)
        db.session.flush()
    return dept
