"""Analytics behind the Reports dashboard.

Everything is computed in Python from plain column queries (no date_trunc /
extract), so the same code runs on PostgreSQL and on the SQLite test database.
`ReportBuilder` exposes each dataset as a lazily cached property, so the
previous-period comparison only pays for the handful of KPIs it actually reads.

Definitions (also surfaced as tooltips in the template):
- Resolution moment: the first time a ticket reached "resolved", or its
  closed_at if it was closed without ever being resolved. A ticket counts as
  resolved in the period that contains its resolution moment.
- Resolution TAT: resolution moment − created_at (calendar hours).
- Resolver: the agent who set "resolved" (falls back to the assignee).
- Resolution outcome: what happened next to a "resolved" status change —
  customer accepted, customer rejected/reopened, auto-closed with no answer,
  closed or reopened by an agent, or still awaiting the customer.
"""
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cached_property
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.extensions import db
from app.models.csat_feedback import CSATFeedback
from app.models.hospital import Hospital
from app.models.product import Product
from app.models.task import TimeEntry
from app.models.ticket import (
    Ticket, TicketHistory, TicketMessage,
    ALL_PRIORITIES, PRIORITY_LABELS, STATUS_LABELS, TYPE_LABELS,
)
from app.models.user import User
from app.services import text_analytics as ta

UTC = ZoneInfo("UTC")
AGENT_ROLES = ("agent", "admin", "viewer")
OPEN_EXCLUDED = ("resolved", "closed")
CHUNK = 900                 # keeps IN (...) lists well under every driver's parameter cap
DESC_CAP = 20000            # chars of a ticket description analysed
MSG_CAP = 6000              # chars of a follow-up message analysed (quoted history is cut anyway)
AUTO_CLOSE_HOURS = 48       # see reminder_tasks.auto_close_resolved_tickets

# ── Date ranges ───────────────────────────────────────────────────────────────

PRESETS = [
    ("today", "Today"), ("yesterday", "Yesterday"),
    ("7d", "Last 7 days"), ("30d", "Last 30 days"), ("90d", "Last 90 days"),
    ("this_month", "This month"), ("last_month", "Last month"),
    ("this_quarter", "This quarter"), ("last_quarter", "Last quarter"),
    ("ytd", "Year to date"), ("last_year", "Last year"), ("12m", "Last 12 months"),
    ("all", "All time"),
]
PRESET_LABELS = dict(PRESETS)
DEFAULT_PRESET = "30d"


def _quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def preset_dates(key: str, today: date, earliest: date | None = None) -> tuple[date, date]:
    if key == "today":
        return today, today
    if key == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if key in ("7d", "30d", "90d"):
        return today - timedelta(days=int(key[:-1]) - 1), today
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "this_quarter":
        return _quarter_start(today), today
    if key == "last_quarter":
        end = _quarter_start(today) - timedelta(days=1)
        return _quarter_start(end), end
    if key == "ytd":
        return date(today.year, 1, 1), today
    if key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "12m":
        return today - timedelta(days=364), today
    if key == "all":
        return min(earliest or today, today), today
    raise KeyError(key)


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


@dataclass
class DateRange:
    start: date
    end: date            # inclusive
    preset: str          # a PRESETS key, "custom" or "previous"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def label(self) -> str:
        if self.preset in PRESET_LABELS:
            return PRESET_LABELS[self.preset]
        return "Custom range"

    @property
    def span_label(self) -> str:
        if self.start == self.end:
            return self.start.strftime("%d %b %Y")
        fmt_start = "%d %b" if self.start.year == self.end.year else "%d %b %Y"
        return f"{self.start.strftime(fmt_start)} – {self.end.strftime('%d %b %Y')}"

    @property
    def granularity(self) -> str:
        if self.days <= 45:
            return "day"
        if self.days <= 200:
            return "week"
        return "month"

    def utc_bounds(self, tz) -> tuple[datetime, datetime]:
        """[start, end) as naive-UTC datetimes covering whole local days."""
        lo = datetime.combine(self.start, time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        hi = datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        return lo, hi

    def previous(self) -> "DateRange":
        end = self.start - timedelta(days=1)
        return DateRange(end - timedelta(days=self.days - 1), end, "previous")


def parse_range(args, today: date, earliest_fn) -> DateRange:
    """Build the range from ?start=&end= (custom) or ?range=<preset>."""
    start, end = _parse_date(args.get("start")), _parse_date(args.get("end"))
    if start or end:
        end = end or today
        start = start or end - timedelta(days=29)
        if start > end:
            start, end = end, start
        start = max(start, date(2000, 1, 1))
        return DateRange(start, end, "custom")
    key = args.get("range", DEFAULT_PRESET)
    if key not in PRESET_LABELS:
        key = DEFAULT_PRESET
    s, e = preset_dates(key, today, earliest_fn() if key == "all" else None)
    return DateRange(s, e, key)


@dataclass
class Filters:
    hospital_id: int = 0
    product_id: int = 0
    agent_id: int = 0
    priority: str = ""

    @classmethod
    def from_args(cls, args):
        priority = args.get("priority", "")
        return cls(
            hospital_id=args.get("hospital_id", 0, type=int),
            product_id=args.get("product_id", 0, type=int),
            agent_id=args.get("agent_id", 0, type=int),
            priority=priority if priority in ALL_PRIORITIES else "",
        )

    def as_args(self) -> dict:
        return {k: v for k, v in vars(self).items() if v}

    @property
    def active(self) -> bool:
        return bool(self.as_args())


# ── Small stats helpers ───────────────────────────────────────────────────────

def _hours(td: timedelta) -> float:
    return td.total_seconds() / 3600


def _round(x, nd=1):
    return round(x, nd) if x is not None else None


def percentile(xs, p):
    """Nearest-rank percentile; None for an empty list."""
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return s[k]


def summary(xs) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "avg": None, "median": None, "p90": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "avg": _round(sum(xs) / len(xs)),
        "median": _round(statistics.median(xs)),
        "p90": _round(percentile(xs, 90)),
        "min": _round(min(xs)),
        "max": _round(max(xs)),
    }


def rate(part, whole):
    return round(part / whole * 100, 1) if whole else None


def bucketize(values, buckets) -> list[int]:
    """Count values into [(label, upper_bound_exclusive), ...]; last bound may be inf."""
    counts = [0] * len(buckets)
    for v in values:
        for i, (_, hi) in enumerate(buckets):
            if v < hi:
                counts[i] += 1
                break
    return counts


INF = float("inf")
TAT_BUCKETS = [("< 1h", 1), ("1–4h", 4), ("4–24h", 24), ("1–3d", 72), ("3–7d", 168), ("1–4w", 672), ("> 4w", INF)]
RESPONSE_BUCKETS = [("< 1h", 1), ("1–4h", 4), ("4–24h", 24), ("1–2d", 48), ("2–7d", 168), ("> 7d", INF)]
AGE_BUCKETS = [("< 1d", 24), ("1–3d", 72), ("3–7d", 168), ("1–4w", 672), ("> 4w", INF)]
WORD_BUCKETS = [("0–10", 11), ("11–25", 26), ("26–50", 51), ("51–100", 101), ("101–250", 251), ("250+", INF)]

OUTCOMES = [
    ("accepted", "Accepted by customer"),
    ("rejected", "Rejected / reopened by customer"),
    ("auto_closed", "Auto-closed, no answer"),
    ("closed_by_agent", "Closed by agent"),
    ("agent_reopened", "Reopened by agent"),
    ("pending", "Awaiting customer"),
    ("untracked", "Left resolved (untracked)"),
]
OUTCOME_LABELS = dict(OUTCOMES)
# Categorical slots in fixed order (CVD-validated as adjacent pairs); a red/green
# status pair would be indistinguishable for deuteranopes in the stacked bars.
OUTCOME_COLORS = {
    "accepted": "#2a78d6", "rejected": "#eb6834", "auto_closed": "#1baf7a",
    "closed_by_agent": "#eda100", "agent_reopened": "#e87ba4", "pending": "#008300",
    "untracked": "#6250d6",
}
# Priority is ordered, so it gets a one-hue ordinal ramp (light = low).
PRIORITY_COLORS = {"low": "#86b6ef", "medium": "#3987e5", "high": "#1c5cab", "urgent": "#0d366b"}


def _chunked(ids, size=CHUNK):
    ids = list(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


_TICKET_COLS = (
    Ticket.id, Ticket.ref, Ticket.subject, Ticket.hospital_id, Ticket.product_id,
    Ticket.assigned_to, Ticket.created_by, Ticket.status, Ticket.priority, Ticket.type,
    Ticket.source, Ticket.created_at, Ticket.closed_at, Ticket.first_response_at,
    Ticket.sla_response_due, Ticket.sla_resolve_due, Ticket.sla_breached, Ticket.phi_flagged,
)


# ── Builder ───────────────────────────────────────────────────────────────────

class ReportBuilder:
    def __init__(self, rng: DateRange, filters: Filters, tz, now: datetime | None = None):
        self.rng = rng
        self.filters = filters
        self.tz = tz
        self.start, self.end = rng.utc_bounds(tz)
        self.now = now or datetime.utcnow()
        self._tickets = {}          # id -> ticket row
        self._first_res = {}        # id -> (first resolved at, changed_by) | None

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _scoped(self, q):
        f = self.filters
        if f.hospital_id:
            q = q.filter(Ticket.hospital_id == f.hospital_id)
        if f.product_id:
            q = q.filter(Ticket.product_id == f.product_id)
        if f.agent_id:
            q = q.filter(Ticket.assigned_to == f.agent_id)
        if f.priority:
            q = q.filter(Ticket.priority == f.priority)
        return q

    def _in_range(self, dt) -> bool:
        return dt is not None and self.start <= dt < self.end

    def local(self, dt: datetime) -> datetime:
        return dt.replace(tzinfo=UTC).astimezone(self.tz)

    def _tickets_by_ids(self, ids) -> dict:
        missing = [i for i in ids if i not in self._tickets]
        for chunk in _chunked(missing):
            for t in db.session.query(*_TICKET_COLS).filter(Ticket.id.in_(chunk)):
                self._tickets[t.id] = t
        return {i: self._tickets[i] for i in ids if i in self._tickets}

    def _first_resolved(self, ids) -> dict:
        missing = [i for i in ids if i not in self._first_res]
        for chunk in _chunked(missing):
            rows = (
                db.session.query(TicketHistory.ticket_id, TicketHistory.created_at, TicketHistory.changed_by)
                .filter(TicketHistory.ticket_id.in_(chunk),
                        TicketHistory.action == "status_change",
                        TicketHistory.new_value == "resolved")
            )
            for r in rows:
                cur = self._first_res.get(r.ticket_id)
                if cur is None or r.created_at < cur[0]:
                    self._first_res[r.ticket_id] = (r.created_at, r.changed_by)
            for i in chunk:
                self._first_res.setdefault(i, None)
        return {i: self._first_res.get(i) for i in ids}

    def _resolution_of(self, t):
        """(resolution moment, resolver id) for a ticket row — see module docstring."""
        fr = self._first_res.get(t.id)
        candidates = [x for x in ((fr[0] if fr else None), t.closed_at) if x]
        if not candidates:
            return None, None
        moment = min(candidates)
        by = fr[1] if fr and fr[0] == moment else None
        return moment, (by if by in self.agent_names else t.assigned_to)

    # ── reference data ────────────────────────────────────────────────────────

    @cached_property
    def agent_users(self) -> dict:
        rows = db.session.query(User.id, User.name, User.active, User.role).filter(User.role.in_(AGENT_ROLES))
        return {r.id: r for r in rows}

    @cached_property
    def agent_names(self) -> dict:
        return {i: r.name for i, r in self.agent_users.items()}

    @cached_property
    def hospital_names(self) -> dict:
        return dict(db.session.query(Hospital.id, Hospital.name).all())

    @cached_property
    def product_names(self) -> dict:
        return dict(db.session.query(Product.id, Product.name).all())

    # ── core datasets ─────────────────────────────────────────────────────────

    @cached_property
    def created(self) -> list:
        q = db.session.query(*_TICKET_COLS).filter(Ticket.created_at >= self.start, Ticket.created_at < self.end)
        rows = self._scoped(q).order_by(Ticket.created_at).all()
        for t in rows:
            self._tickets[t.id] = t
        return rows

    @cached_property
    def closed_in_range(self) -> list:
        q = db.session.query(Ticket.id, Ticket.closed_at).filter(Ticket.closed_at >= self.start, Ticket.closed_at < self.end)
        return self._scoped(q).all()

    @cached_property
    def _resolved_events_raw(self) -> list:
        q = (
            db.session.query(TicketHistory.id, TicketHistory.ticket_id, TicketHistory.created_at, TicketHistory.changed_by)
            .join(Ticket, Ticket.id == TicketHistory.ticket_id)
            .filter(TicketHistory.action == "status_change", TicketHistory.new_value == "resolved",
                    TicketHistory.created_at >= self.start, TicketHistory.created_at < self.end)
        )
        return self._scoped(q).order_by(TicketHistory.created_at, TicketHistory.id).all()

    @cached_property
    def resolved(self) -> list:
        """Tickets whose resolution moment falls in the range."""
        cand = {e.ticket_id for e in self._resolved_events_raw} | {r.id for r in self.closed_in_range}
        tickets = self._tickets_by_ids(cand)
        self._first_resolved(cand)
        out = []
        for t in tickets.values():
            moment, resolver = self._resolution_of(t)
            if self._in_range(moment):
                out.append(SimpleNamespace(t=t, moment=moment, resolver=resolver,
                                           hours=max(0.0, _hours(moment - t.created_at))))
        return out

    @cached_property
    def created_resolution(self) -> dict:
        """ticket id -> resolution hours for tickets created in range (whenever they resolved)."""
        self._first_resolved([t.id for t in self.created])
        out = {}
        for t in self.created:
            moment, _ = self._resolution_of(t)
            if moment:
                out[t.id] = max(0.0, _hours(moment - t.created_at))
        return out

    @cached_property
    def resolution_events(self) -> list:
        """Every 'resolved' status change in range, classified by what happened next."""
        raw = self._resolved_events_raw
        if not raw:
            return []
        ids = {r.ticket_id for r in raw}
        tickets = self._tickets_by_ids(ids)
        first_res = self._first_resolved(ids)

        transitions = defaultdict(list)
        t0 = raw[0].created_at
        for chunk in _chunked(ids):
            rows = (
                db.session.query(TicketHistory.id, TicketHistory.ticket_id, TicketHistory.created_at,
                                 TicketHistory.action, TicketHistory.old_value, TicketHistory.new_value,
                                 TicketHistory.changed_by)
                .filter(TicketHistory.ticket_id.in_(chunk),
                        TicketHistory.action.in_(("status_change", "auto_close")),
                        TicketHistory.created_at >= t0)
            )
            for h in rows:
                transitions[h.ticket_id].append(h)
        for lst in transitions.values():
            lst.sort(key=lambda h: (h.created_at, h.id))

        events = []
        for r in raw:
            t = tickets.get(r.ticket_id)
            if t is None:
                continue
            nxt = next((h for h in transitions[r.ticket_id] if (h.created_at, h.id) > (r.created_at, r.id)), None)
            outcome, gap = self._classify(r, nxt, t)
            fr = first_res.get(r.ticket_id)
            events.append(SimpleNamespace(
                id=r.id, t=t, at=r.created_at, outcome=outcome, hours=gap,
                resolver=r.changed_by if r.changed_by in self.agent_names else t.assigned_to,
                is_first=bool(fr and fr[0] == r.created_at),
                waited=_hours(self.now - r.created_at) if outcome == "pending" else None,
            ))
        self._resolve_untracked(events)
        return events

    def _classify(self, ev, nxt, t):
        if nxt is None or nxt.old_value not in (None, "resolved"):
            # No logged transition out of "resolved": still waiting, or it left the
            # state through a path that didn't log history (older email replies).
            return ("pending", None) if t.status == "resolved" and nxt is None else ("untracked", None)
        gap = max(0.0, _hours(nxt.created_at - ev.created_at))
        by_agent = nxt.changed_by in self.agent_names
        if nxt.new_value == "closed":
            if nxt.action == "auto_close":
                return "auto_closed", gap
            if by_agent:
                return "closed_by_agent", gap
            # Before auto-close got its own history action it logged a plain
            # system status_change; the 48h floor tells it apart from the
            # customer's emailed "Yes, close it" link.
            if nxt.changed_by is None and gap >= AUTO_CLOSE_HOURS:
                return "auto_closed", gap
            return "accepted", gap
        return ("agent_reopened" if by_agent else "rejected"), gap

    def _resolve_untracked(self, events):
        """A ticket that left 'resolved' without history was reopened by a customer
        email; time the rejection from that customer's first message."""
        pending = [e for e in events if e.outcome == "untracked"]
        if not pending:
            return
        since = min(e.at for e in pending)
        msgs = defaultdict(list)
        for chunk in _chunked({e.t.id for e in pending}):
            rows = (
                db.session.query(TicketMessage.ticket_id, TicketMessage.created_at, TicketMessage.sender_id)
                .filter(TicketMessage.ticket_id.in_(chunk), TicketMessage.is_internal == False,  # noqa: E712
                        TicketMessage.created_at > since)
            )
            for m in rows:
                if m.sender_id not in self.agent_names:
                    msgs[m.ticket_id].append(m.created_at)
        for e in pending:
            after = sorted(x for x in msgs[e.t.id] if x > e.at)
            if after:
                e.outcome, e.hours = "rejected", _hours(after[0] - e.at)

    @cached_property
    def created_messages(self) -> dict:
        """ticket id -> messages (oldest first) for tickets created in range."""
        out = defaultdict(list)
        ids = [t.id for t in self.created]
        for chunk in _chunked(ids):
            rows = db.session.query(
                TicketMessage.id, TicketMessage.ticket_id, TicketMessage.sender_id,
                TicketMessage.is_internal, TicketMessage.created_at,
                func.substr(TicketMessage.body, 1, DESC_CAP).label("body"),
            ).filter(TicketMessage.ticket_id.in_(chunk))
            for m in rows:
                out[m.ticket_id].append(m)
        for lst in out.values():
            lst.sort(key=lambda m: (m.created_at, m.id))
        return out

    @cached_property
    def description_ids(self) -> set:
        return {msgs[0].id for msgs in self.created_messages.values() if msgs}

    @cached_property
    def period_messages(self) -> list:
        """Message metadata sent in range (agent activity); bodies only for agents."""
        agent_ids = list(self.agent_names) or [-1]
        q = (
            db.session.query(
                TicketMessage.id, TicketMessage.ticket_id, TicketMessage.sender_id,
                TicketMessage.is_internal, TicketMessage.created_at,
            )
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .filter(TicketMessage.created_at >= self.start, TicketMessage.created_at < self.end)
        )
        rows = self._scoped(q).all()
        bodies = {}
        bq = (
            db.session.query(TicketMessage.id, func.substr(TicketMessage.body, 1, MSG_CAP))
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .filter(TicketMessage.created_at >= self.start, TicketMessage.created_at < self.end,
                    TicketMessage.sender_id.in_(agent_ids), Ticket.phi_flagged == False)  # noqa: E712
        )
        for mid, body in self._scoped(bq):
            bodies[mid] = body
        return [SimpleNamespace(**m._asdict(), body=bodies.get(m.id)) for m in rows]

    @cached_property
    def csat(self) -> list:
        q = (
            db.session.query(CSATFeedback.rating, CSATFeedback.comment, CSATFeedback.submitted_at,
                             Ticket.ref, Ticket.assigned_to, Ticket.hospital_id)
            .join(Ticket, Ticket.id == CSATFeedback.ticket_id)
            .filter(CSATFeedback.rating.isnot(None),
                    CSATFeedback.submitted_at >= self.start, CSATFeedback.submitted_at < self.end)
        )
        return self._scoped(q).order_by(CSATFeedback.submitted_at.desc()).all()

    @cached_property
    def csat_sent(self) -> int:
        q = (
            db.session.query(func.count(CSATFeedback.id))
            .join(Ticket, Ticket.id == CSATFeedback.ticket_id)
            .filter(CSATFeedback.sent_at >= self.start, CSATFeedback.sent_at < self.end)
        )
        return self._scoped(q).scalar() or 0

    @cached_property
    def backlog(self) -> list:
        """Open tickets right now (ignores the date range, honours the filters)."""
        q = db.session.query(Ticket.id, Ticket.status, Ticket.assigned_to, Ticket.created_at,
                             Ticket.priority, Ticket.sla_breached).filter(Ticket.status.notin_(OPEN_EXCLUDED))
        return self._scoped(q).all()

    @cached_property
    def awaiting_confirmation(self) -> list:
        """Tickets currently sitting in 'resolved', oldest first."""
        q = db.session.query(*_TICKET_COLS).filter(Ticket.status == "resolved")
        rows = self._scoped(q).all()
        if not rows:
            return []
        last_resolved = {}
        for chunk in _chunked([t.id for t in rows]):
            for tid, at in (
                db.session.query(TicketHistory.ticket_id, func.max(TicketHistory.created_at))
                .filter(TicketHistory.ticket_id.in_(chunk), TicketHistory.action == "status_change",
                        TicketHistory.new_value == "resolved")
                .group_by(TicketHistory.ticket_id)
            ):
                last_resolved[tid] = at
        out = []
        for t in rows:
            since = last_resolved.get(t.id) or t.created_at
            out.append(SimpleNamespace(t=t, since=since, waited=_hours(self.now - since)))
        out.sort(key=lambda x: x.since)
        return out

    @cached_property
    def minutes_logged(self) -> dict:
        q = (
            db.session.query(TimeEntry.logged_by, func.sum(TimeEntry.minutes))
            .filter(TimeEntry.logged_at >= self.start, TimeEntry.logged_at < self.end)
        )
        if self.filters.agent_id:
            q = q.filter(TimeEntry.logged_by == self.filters.agent_id)
        return {uid: int(m or 0) for uid, m in q.group_by(TimeEntry.logged_by)}

    # ── derived: first response ───────────────────────────────────────────────

    @cached_property
    def first_responses(self) -> dict:
        """ticket id -> (hours, responding agent) for tickets created in range.

        Uses the first public agent message after the description; falls back to
        Ticket.first_response_at (credited to the assignee) when messages don't say.
        """
        out = {}
        for t in self.created:
            msgs = self.created_messages.get(t.id, [])
            reply = next((m for m in msgs[1:] if not m.is_internal and m.sender_id in self.agent_names), None)
            if reply:
                out[t.id] = (max(0.0, _hours(reply.created_at - t.created_at)), reply.sender_id)
            elif t.first_response_at:
                out[t.id] = (max(0.0, _hours(t.first_response_at - t.created_at)), t.assigned_to)
        return out

    # ── KPIs ──────────────────────────────────────────────────────────────────

    @cached_property
    def kpis(self) -> dict:
        res_hours = [r.hours for r in self.resolved]
        frt = [h for h, _ in self.first_responses.values()]
        ev = Counter(e.outcome for e in self.resolution_events)
        decided = ev["accepted"] + ev["rejected"]
        ratings = [c.rating for c in self.csat]
        return {
            "created": len(self.created),
            "resolved": len(self.resolved),
            "closed": len(self.closed_in_range),
            "median_tat": _round(statistics.median(res_hours)) if res_hours else None,
            "avg_tat": _round(sum(res_hours) / len(res_hours)) if res_hours else None,
            "median_frt": _round(statistics.median(frt)) if frt else None,
            "acceptance_rate": rate(ev["accepted"], decided),
            "reopen_rate": rate(ev["rejected"] + ev["agent_reopened"], len(self.resolution_events)),
            "csat": _round(sum(ratings) / len(ratings), 2) if ratings else None,
            "csat_n": len(ratings),
        }

    # ── Overview ──────────────────────────────────────────────────────────────

    def _bucket_key(self, d: date) -> date:
        g = self.rng.granularity
        if g == "week":
            return d - timedelta(days=d.weekday())
        if g == "month":
            return d.replace(day=1)
        return d

    @cached_property
    def buckets(self) -> list:
        keys, cur, last = [], self._bucket_key(self.rng.start), self._bucket_key(self.rng.end)
        while cur <= last:
            keys.append(cur)
            if self.rng.granularity == "day":
                cur += timedelta(days=1)
            elif self.rng.granularity == "week":
                cur += timedelta(days=7)
            else:
                cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        return keys

    def bucket_labels(self) -> list:
        g = self.rng.granularity
        if g == "month":
            return [k.strftime("%b %Y") for k in self.buckets]
        fmt = "%d %b" if self.rng.start.year == self.rng.end.year else "%d %b %y"
        return [k.strftime(fmt) for k in self.buckets]

    def _series(self, dts) -> list:
        idx = {k: i for i, k in enumerate(self.buckets)}
        out = [0] * len(self.buckets)
        for dt in dts:
            i = idx.get(self._bucket_key(self.local(dt).date()))
            if i is not None:
                out[i] += 1
        return out

    def _median_series(self, pairs) -> list:
        """pairs of (utc datetime, hours) -> per-bucket median (None for empty buckets)."""
        idx = {k: i for i, k in enumerate(self.buckets)}
        vals = [[] for _ in self.buckets]
        for dt, h in pairs:
            i = idx.get(self._bucket_key(self.local(dt).date()))
            if i is not None:
                vals[i].append(h)
        return [_round(statistics.median(v)) if v else None for v in vals]

    @cached_property
    def overview(self) -> dict:
        created = self.created
        heat = Counter()
        for t in created:
            lt = self.local(t.created_at)
            heat[(lt.weekday(), lt.hour)] += 1

        # SLA compliance for tickets created in range
        resp_met = resp_missed = res_met = res_missed = 0
        for t in created:
            if t.sla_response_due:
                fr = t.first_response_at
                if fr and fr <= t.sla_response_due:
                    resp_met += 1
                elif (fr and fr > t.sla_response_due) or (not fr and t.sla_response_due < self.now):
                    resp_missed += 1
            if t.sla_resolve_due:
                h = self.created_resolution.get(t.id)
                moment = t.created_at + timedelta(hours=h) if h is not None else None
                if moment and moment <= t.sla_resolve_due:
                    res_met += 1
                elif (moment and moment > t.sla_resolve_due) or (not moment and t.sla_resolve_due < self.now):
                    res_missed += 1

        # TAT by priority (resolved in range)
        by_pri = defaultdict(list)
        for r in self.resolved:
            by_pri[r.t.priority].append(r.hours)
        pri_rows = [
            {"key": p, "label": PRIORITY_LABELS.get(p, p), **summary(by_pri.get(p, []))}
            for p in reversed(ALL_PRIORITIES)
        ]

        backlog_age = bucketize([_hours(self.now - b.created_at) for b in self.backlog], AGE_BUCKETS)

        def mix(attr, labels):
            c = Counter(getattr(t, attr) or "unknown" for t in created)
            return [{"key": k, "name": labels.get(k, str(k).replace("_", " ").title()), "value": v}
                    for k, v in c.most_common()]

        return {
            "labels": self.bucket_labels(),
            "granularity": self.rng.granularity,
            "created_series": self._series(t.created_at for t in created),
            "resolved_series": self._series(r.moment for r in self.resolved),
            "closed_series": self._series(r.closed_at for r in self.closed_in_range),
            "tat_series": self._median_series((r.moment, r.hours) for r in self.resolved),
            "frt_series": self._median_series(
                (self._tickets[tid].created_at, h) for tid, (h, _) in self.first_responses.items()),
            "heatmap": [[hour, dow, heat[(dow, hour)]] for dow in range(7) for hour in range(24)],
            "heat_max": max(heat.values()) if heat else 0,
            "tat_hist": bucketize([r.hours for r in self.resolved], TAT_BUCKETS),
            "tat_hist_labels": [b[0] for b in TAT_BUCKETS],
            "tat_summary": summary([r.hours for r in self.resolved]),
            "frt_summary": summary([h for h, _ in self.first_responses.values()]),
            "priority_rows": pri_rows,
            "priority_mix": sorted(
                ({**m, "itemStyle": {"color": PRIORITY_COLORS.get(m["key"], "#898781")}}
                 for m in mix("priority", PRIORITY_LABELS)),
                key=lambda m: ALL_PRIORITIES.index(m["key"]) if m["key"] in ALL_PRIORITIES else 99,
            ),
            "type_mix": mix("type", TYPE_LABELS),
            "source_mix": mix("source", {"portal": "Portal", "email": "Email", "agent": "Agent"}),
            "status_mix": mix("status", STATUS_LABELS),
            "sla": {
                "resp_met": resp_met, "resp_missed": resp_missed, "resp_rate": rate(resp_met, resp_met + resp_missed),
                "res_met": res_met, "res_missed": res_missed, "res_rate": rate(res_met, res_met + res_missed),
                "breached_flag": sum(1 for t in created if t.sla_breached),
            },
            "backlog_total": len(self.backlog),
            "backlog_unassigned": sum(1 for b in self.backlog if not b.assigned_to),
            "backlog_breached": sum(1 for b in self.backlog if b.sla_breached),
            "backlog_age": backlog_age,
            "backlog_age_labels": [b[0] for b in AGE_BUCKETS],
            "backlog_status": [
                {"name": STATUS_LABELS.get(s, s), "value": c}
                for s, c in Counter(b.status for b in self.backlog).most_common()
            ],
        }

    # ── Agents ────────────────────────────────────────────────────────────────

    @cached_property
    def agents(self) -> list:
        S = defaultdict(lambda: {
            "assigned": 0, "open_now": 0, "tat": [], "frt": [], "outcomes": Counter(),
            "accept_h": [], "reject_h": [], "replies": 0, "notes": 0, "reply_words": [],
            "ratings": [], "sla_breached": 0,
        })
        for t in self.created:
            if t.assigned_to:
                S[t.assigned_to]["assigned"] += 1
                if t.sla_breached:
                    S[t.assigned_to]["sla_breached"] += 1
        for b in self.backlog:
            if b.assigned_to:
                S[b.assigned_to]["open_now"] += 1
        for r in self.resolved:
            if r.resolver:
                S[r.resolver]["tat"].append(r.hours)
        for h, who in self.first_responses.values():
            if who:
                S[who]["frt"].append(h)
        for e in self.resolution_events:
            if e.resolver:
                S[e.resolver]["outcomes"][e.outcome] += 1
                if e.outcome == "accepted":
                    S[e.resolver]["accept_h"].append(e.hours)
                elif e.outcome == "rejected" and e.hours is not None:
                    S[e.resolver]["reject_h"].append(e.hours)
        for m in self.period_messages:
            if m.sender_id in self.agent_names and m.id not in self.description_ids:
                s = S[m.sender_id]
                if m.is_internal:
                    s["notes"] += 1
                else:
                    s["replies"] += 1
                    if m.body is not None:
                        s["reply_words"].append(ta.word_count(ta.strip_quoted(m.body)))
        for c in self.csat:
            if c.assigned_to:
                S[c.assigned_to]["ratings"].append(c.rating)

        rows = []
        for uid, u in self.agent_users.items():
            if self.filters.agent_id and uid != self.filters.agent_id:
                continue
            s = S.get(uid)
            minutes = self.minutes_logged.get(uid, 0)
            if s is None and not minutes and not (u.active and u.role in ("agent", "admin")):
                continue
            s = s or S[uid]
            oc = s["outcomes"]
            decided = oc["accepted"] + oc["rejected"]
            tat, frt = summary(s["tat"]), summary(s["frt"])
            rows.append({
                "id": uid, "name": u.name, "active": u.active,
                "assigned": s["assigned"], "open_now": s["open_now"],
                "resolved": tat["n"], "tat": tat, "frt": frt,
                "resolutions": sum(oc.values()),
                "outcomes": {k: oc[k] for k, _ in OUTCOMES},
                "acceptance_rate": rate(oc["accepted"], decided),
                "accept_median": summary(s["accept_h"])["median"],
                "reject_median": summary(s["reject_h"])["median"],
                "replies": s["replies"], "notes": s["notes"],
                "avg_reply_words": summary(s["reply_words"])["avg"],
                "csat": _round(sum(s["ratings"]) / len(s["ratings"]), 2) if s["ratings"] else None,
                "csat_n": len(s["ratings"]),
                "sla_breached": s["sla_breached"],
                "hours_logged": round(minutes / 60, 1),
            })
        rows.sort(key=lambda r: (-r["resolved"], -r["replies"], r["name"].lower()))
        return rows

    # ── Resolution acceptance ─────────────────────────────────────────────────

    @cached_property
    def acceptance(self) -> dict:
        ev = self.resolution_events
        counts = Counter(e.outcome for e in ev)
        accept_h = [e.hours for e in ev if e.outcome == "accepted"]
        reject_h = [e.hours for e in ev if e.outcome == "rejected" and e.hours is not None]
        decided = counts["accepted"] + counts["rejected"]
        concluded = len(ev) - counts["pending"] - counts["untracked"]
        firsts = [e for e in ev if e.is_first and e.outcome not in ("pending", "untracked")]
        first_fix = sum(1 for e in firsts if e.outcome in ("accepted", "auto_closed", "closed_by_agent"))

        by_h = defaultdict(lambda: {"total": 0, "c": Counter(), "resp": []})
        for e in ev:
            h = by_h[e.t.hospital_id]
            h["total"] += 1
            h["c"][e.outcome] += 1
            if e.outcome in ("accepted", "rejected") and e.hours is not None:
                h["resp"].append(e.hours)
        hospital_rows = sorted((
            {
                "id": hid, "name": self.hospital_names.get(hid, "—"), "total": v["total"],
                "accepted": v["c"]["accepted"], "rejected": v["c"]["rejected"],
                "auto_closed": v["c"]["auto_closed"], "pending": v["c"]["pending"],
                "acceptance_rate": rate(v["c"]["accepted"], v["c"]["accepted"] + v["c"]["rejected"]),
                "engagement": rate(v["c"]["accepted"] + v["c"]["rejected"],
                                   v["total"] - v["c"]["pending"] - v["c"]["untracked"]),
                "resp_median": summary(v["resp"])["median"],
            }
            for hid, v in by_h.items()
        ), key=lambda r: -r["total"])

        return {
            "total": len(ev),
            "counts": {k: counts[k] for k, _ in OUTCOMES},
            "mix": [{"key": k, "name": lbl, "value": counts[k], "color": OUTCOME_COLORS[k]}
                    for k, lbl in OUTCOMES if counts[k]],
            "acceptance_rate": rate(counts["accepted"], decided),
            "engagement_rate": rate(decided, concluded),
            "first_fix_rate": rate(first_fix, len(firsts)),
            "accept": summary(accept_h),
            "reject": summary(reject_h),
            "accept_hist": bucketize(accept_h, RESPONSE_BUCKETS),
            "reject_hist": bucketize(reject_h, RESPONSE_BUCKETS),
            "hist_labels": [b[0] for b in RESPONSE_BUCKETS],
            "hospital_rows": hospital_rows,
            "awaiting": self.awaiting_confirmation,
            "awaiting_hist": bucketize([a.waited for a in self.awaiting_confirmation], RESPONSE_BUCKETS),
        }

    # ── Customers ─────────────────────────────────────────────────────────────

    @cached_property
    def customers(self) -> dict:
        res_by_h, res_by_p = defaultdict(list), defaultdict(list)
        for r in self.resolved:
            res_by_h[r.t.hospital_id].append(r.hours)
            res_by_p[r.t.product_id].append(r.hours)
        csat_by_h = defaultdict(list)
        for c in self.csat:
            csat_by_h[c.hospital_id].append(c.rating)
        acc_by_h = {r["id"]: r for r in self.acceptance["hospital_rows"]}

        created_h = Counter(t.hospital_id for t in self.created)
        open_h = Counter(b_t.hospital_id for b_t in self.created if b_t.status not in OPEN_EXCLUDED)
        urgent_h = Counter(t.hospital_id for t in self.created if t.priority in ("urgent", "high"))
        hospitals = []
        for hid in set(created_h) | set(res_by_h):
            name = self.hospital_names.get(hid, "—")
            ratings = csat_by_h.get(hid, [])
            hospitals.append({
                "name": name, "created": created_h[hid], "still_open": open_h[hid],
                "high_share": rate(urgent_h[hid], created_h[hid]),
                "resolved": len(res_by_h.get(hid, [])),
                "tat_median": summary(res_by_h.get(hid, []))["median"],
                "acceptance_rate": (acc_by_h.get(hid) or {}).get("acceptance_rate"),
                "csat": _round(sum(ratings) / len(ratings), 2) if ratings else None,
                "words": self.text["desc_words_by_hospital"].get(hid),
            })
        hospitals.sort(key=lambda r: (-r["created"], r["name"]))

        created_p = Counter(t.product_id for t in self.created)
        products = []
        for pid in set(created_p) | set(res_by_p):
            products.append({
                "name": self.product_names.get(pid, "No product") if pid else "No product",
                "created": created_p[pid], "resolved": len(res_by_p.get(pid, [])),
                "tat_median": summary(res_by_p.get(pid, []))["median"],
                "tat_p90": summary(res_by_p.get(pid, []))["p90"],
                "keywords": self.text["product_keywords"].get(pid, []),
            })
        products.sort(key=lambda r: (-r["created"], r["name"]))

        requesters = Counter(t.created_by for t in self.created if t.created_by)
        top = requesters.most_common(10)
        names = {}
        if top:
            names = {u.id: u for u in db.session.query(User.id, User.name, User.hospital_id)
                     .filter(User.id.in_([uid for uid, _ in top]))}
        return {
            "hospitals": hospitals,
            "products": products,
            "requesters": [
                {"name": names[uid].name if uid in names else "—",
                 "hospital": self.hospital_names.get(names[uid].hospital_id, "") if uid in names else "",
                 "count": n}
                for uid, n in top
            ],
            "csat_dist": [sum(1 for c in self.csat if c.rating == i) for i in range(1, 6)],
            "csat_comments": [c for c in self.csat if c.comment][:6],
            "csat_response_rate": rate(len(self.csat), self.csat_sent),
        }

    # ── Text analytics ────────────────────────────────────────────────────────

    @cached_property
    def text(self) -> dict:
        kw, subj_kw, bi, codes = ta.TermCounter(), ta.TermCounter(), ta.TermCounter(), Counter()
        product_kw = defaultdict(ta.TermCounter)
        langs, urgency_terms, frustration_terms = Counter(), Counter(), Counter()
        subj_w, desc_w, cust_w, msgs_per_ticket = [], [], [], []
        desc_by_h = defaultdict(list)
        len_bucket_tat = [[] for _ in WORD_BUCKETS]
        len_bucket_n = [0] * len(WORD_BUCKETS)
        urgent_tat, calm_tat = [], []
        urgent_ids, frustrated_ids, with_customer_text = set(), set(), 0
        underprioritized = []
        vocab = set()
        analysed = 0

        for t in self.created:
            if t.phi_flagged:
                continue
            analysed += 1
            msgs = self.created_messages.get(t.id, [])
            desc = ta.strip_quoted(msgs[0].body or "", is_reply=False) if msgs else ""
            s_tok, d_tok = ta.tokenize(t.subject), ta.tokenize(desc)
            sw, dw = ta.word_count(t.subject), ta.word_count(desc)
            subj_w.append(sw)
            desc_w.append(dw)
            desc_by_h[t.hospital_id].append(dw)

            terms = ta.content_terms(s_tok + d_tok)
            vocab.update(terms)
            kw.add(terms)
            subj_kw.add(ta.content_terms(s_tok))
            bi.add(ta.phrases(t.subject) + ta.phrases(desc))
            product_kw[t.product_id].add(terms)
            codes.update(ta.error_codes(f"{t.subject}\n{desc}"))
            langs[ta.detect_language(f"{t.subject}\n{desc}", s_tok + d_tok)] += 1

            hits = ta.urgency_hits(f"{t.subject}\n{desc}")
            tat = self.created_resolution.get(t.id)
            if hits:
                urgent_ids.add(t.id)
                urgency_terms.update(set(hits))
                if tat is not None:
                    urgent_tat.append(tat)
                if t.priority in ("low", "medium"):
                    underprioritized.append(t)
            elif tat is not None:
                calm_tat.append(tat)

            bi_idx = next(i for i, (_, hi) in enumerate(WORD_BUCKETS) if dw < hi)
            len_bucket_n[bi_idx] += 1
            if tat is not None:
                len_bucket_tat[bi_idx].append(tat)

            customer_texts = [desc] if msgs and msgs[0].sender_id not in self.agent_names else []
            public = 0
            for m in msgs:
                if m.is_internal:
                    continue
                public += 1
                if m is msgs[0] or m.sender_id in self.agent_names:
                    continue
                body = ta.strip_quoted((m.body or "")[:MSG_CAP])
                cust_w.append(ta.word_count(body))
                customer_texts.append(body)
            msgs_per_ticket.append(public)
            if customer_texts:
                with_customer_text += 1
                f_hits = ta.frustration_hits("\n".join(customer_texts))
                if f_hits:
                    frustrated_ids.add(t.id)
                    frustration_terms.update(set(f_hits))

        agent_reply_w, note_w = [], []
        for m in self.period_messages:
            if m.sender_id in self.agent_names and m.body is not None and m.id not in self.description_ids:
                (note_w if m.is_internal else agent_reply_w).append(ta.word_count(ta.strip_quoted(m.body)))

        cloud = [{"name": w, "value": n} for w, n in kw.top(80)]
        return {
            "analysed": analysed,
            "phi_excluded": len(self.created) - analysed,
            "length_rows": [
                {"field": "Subject", **summary(subj_w)},
                {"field": "Description (first message)", **summary(desc_w)},
                {"field": "Customer follow-ups", **summary(cust_w)},
                {"field": "Agent replies (sent in range)", **summary(agent_reply_w)},
                {"field": "Internal notes (sent in range)", **summary(note_w)},
            ],
            "msgs_per_ticket": summary(msgs_per_ticket),
            "vocabulary": len(vocab),
            "keywords": kw.top(25),
            "subject_keywords": subj_kw.top(15),
            "bigrams": bi.top(15),
            "cloud": cloud,
            "languages": [{"name": k, "value": v} for k, v in langs.most_common()],
            "desc_hist": len_bucket_n,
            "desc_hist_labels": [b[0] for b in WORD_BUCKETS],
            "len_tat": [_round(statistics.median(v)) if v else None for v in len_bucket_tat],
            "urgency": {
                "count": len(urgent_ids), "share": rate(len(urgent_ids), analysed),
                "terms": urgency_terms.most_common(8),
                "tat_with": summary(urgent_tat)["median"], "tat_without": summary(calm_tat)["median"],
                "underprioritized": underprioritized[:8], "underprioritized_n": len(underprioritized),
            },
            "frustration": {
                "count": len(frustrated_ids), "share": rate(len(frustrated_ids), with_customer_text),
                "terms": frustration_terms.most_common(8),
            },
            "codes": codes.most_common(12),
            "product_keywords": {pid: [w for w, _ in c.top(4)] for pid, c in product_kw.items()},
            "desc_words_by_hospital": {hid: _round(sum(v) / len(v)) for hid, v in desc_by_h.items() if v},
        }

    # ── Comparison ────────────────────────────────────────────────────────────

    def deltas(self, prev: "ReportBuilder") -> dict:
        """Signed change vs the previous period for each KPI (None when not comparable)."""
        out = {}
        cur, old = self.kpis, prev.kpis
        for k in ("created", "resolved", "closed", "median_tat", "median_frt", "acceptance_rate",
                  "reopen_rate", "csat"):
            a, b = cur.get(k), old.get(k)
            if a is None or b is None:
                out[k] = None
            elif k in ("acceptance_rate", "reopen_rate"):
                out[k] = {"abs": round(a - b, 1), "unit": "pts", "prev": b}
            elif k == "csat":
                out[k] = {"abs": round(a - b, 2), "unit": "", "prev": b}
            else:
                out[k] = {"pct": rate(a - b, b) if b else None, "abs": round(a - b, 1), "prev": b}
        return out


def earliest_ticket_date(tz) -> date | None:
    first = db.session.query(func.min(Ticket.created_at)).scalar()
    return first.replace(tzinfo=UTC).astimezone(tz).date() if first else None
