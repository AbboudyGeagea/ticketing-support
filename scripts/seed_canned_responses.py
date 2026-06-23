"""One-shot script: insert default canned responses."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.canned_response import CannedResponse
from app.models.user import User

RESPONSES = [
    (
        "Initial Acknowledgment",
        "Thank you for reaching out to Intermedic Support. We have received your request and it will be assigned to our team. We will review the details and get back to you shortly.",
    ),
    (
        "Needs More Information",
        "To better assist you, could you please provide more details, including any error messages, screenshots, or the steps that led to this issue? This will help us resolve it as quickly as possible.",
    ),
    (
        "Under Investigation",
        "We have reviewed your request and our team is currently investigating the issue. We will keep you updated on our progress and notify you once a resolution is available.",
    ),
    (
        "Pending Your Response",
        "We are waiting for additional information from your side in order to proceed. Please reply at your earliest convenience so we can continue working on your request.",
    ),
    (
        "Workaround Available",
        "While we work on a permanent fix, we'd like to share the following workaround to minimize disruption on your end. Please let us know if you need any assistance applying it.",
    ),
    (
        "Escalated to Technical Team",
        "Your request has been escalated to our technical team for further review. We appreciate your patience and will follow up with an update as soon as we have more information.",
    ),
    (
        "Scheduled Fix / Planned Deployment",
        "We have identified the root cause of your issue and a fix is being prepared. It will be deployed during our next scheduled maintenance window. We will notify you once it has been applied.",
    ),
    (
        "Resolved — Please Confirm",
        "We believe your issue has been resolved. Could you please confirm on your end that everything is now working as expected? If the problem persists, don't hesitate to reply and we will continue to assist you.",
    ),
    (
        "Closing Due to Inactivity",
        "We have not received a response to our last message and will be closing this ticket. If you still need assistance, please don't hesitate to open a new request or reply to this message to reopen it.",
    ),
    (
        "After Hours Notice",
        "Thank you for contacting Intermedic Support. Our team is currently outside of regular business hours. Your request has been logged and we will respond on the next business day. For urgent cases, outage or system down, please contact the hotline.",
    ),
]

app = create_app()

with app.app_context():
    admin = User.query.filter(
        User.role.in_(["admin", "agent"]),
        User.active == True,
    ).order_by(User.id).first()

    if not admin:
        print("ERROR: No active agent/admin user found. Aborting.")
        sys.exit(1)

    print(f"Using creator: {admin.name} (id={admin.id})")

    created = 0
    skipped = 0
    for title, body in RESPONSES:
        if CannedResponse.query.filter_by(title=title).first():
            print(f"  SKIP (already exists): {title}")
            skipped += 1
            continue
        cr = CannedResponse(
            title=title,
            body=body,
            is_shared=True,
            created_by=admin.id,
        )
        db.session.add(cr)
        print(f"  ADD: {title}")
        created += 1

    db.session.commit()
    print(f"\nDone — {created} created, {skipped} skipped.")
