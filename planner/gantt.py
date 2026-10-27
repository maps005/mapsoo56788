"""Project timeline for the admin Gantt chart.

Each project gets a planned bar (its start and due dates, set in the admin) and its actual phases, taken from
what happened in the app:
  Survey  - project created until the survey was approved
  Design  - survey approved until the design was first sent for review
  Review  - first sent for review until the design was approved
A phase still under way runs to today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.utils import timezone

PHASES = [("survey", "Survey"), ("design", "Design"), ("review", "Review")]


@dataclass
class Segment:
    kind: str
    label: str
    start: date
    end: date
    left: float = 0.0   # % of the chart width
    width: float = 0.0


@dataclass
class Row:
    project: object
    status: str
    segments: list[Segment] = field(default_factory=list)
    planned: Segment | None = None
    approved_on: date | None = None
    late: bool = False
    marker_left: float | None = None

    @property
    def status_label(self) -> str:
        return {"draft": "Draft", "in_review": "In review", "approved": "Approved"}.get(self.status, self.status)


def _day(v) -> date | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return timezone.localtime(v).date() if timezone.is_aware(v) else v.date()
    if isinstance(v, date):
        return v
    try:
        return _day(datetime.fromisoformat(str(v)))
    except ValueError:
        return None


def build(projects, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    rows: list[Row] = []
    for p in projects:
        info = (p.data or {}).get("info", {})
        status = info.get("design_status", "draft")
        revs = sorted(p.revisions.all(), key=lambda r: r.version)
        created = _day(p.created) or today
        survey_ok = _day(info.get("survey_approved_at"))
        sent = next((_day(r.created) for r in revs if r.status == "in_review"), None)
        approved = next((_day(r.created) for r in revs if r.status == "approved"), None) if status == "approved" else None
        row = Row(project=p, status=status, approved_on=approved)
        survey_end = survey_ok or sent or approved or today
        row.segments.append(Segment("survey", "Survey", created, max(created, survey_end)))
        if survey_ok or sent or approved:
            d_start = survey_ok or sent or approved
            d_end = sent or approved or today
            row.segments.append(Segment("design", "Design", d_start, max(d_start, d_end)))
        if sent:
            row.segments.append(Segment("review", "Review", sent, max(sent, approved or today)))
        if p.start_date or p.due_date:
            ps = p.start_date or created
            pe = p.due_date or ps
            row.planned = Segment("planned", "Planned", ps, max(ps, pe))
            row.late = bool(p.due_date and (approved or today) > p.due_date)
        rows.append(row)

    days = [d for r in rows for s in r.segments + ([r.planned] if r.planned else []) for d in (s.start, s.end)]
    start = min(days + [today]) - timedelta(days=3)
    end = max(days + [today]) + timedelta(days=7)
    span = max((end - start).days, 1)

    def pct(d: date) -> float:
        return round(100 * (d - start).days / span, 3)

    for r in rows:
        for s in r.segments + ([r.planned] if r.planned else []):
            s.left = pct(s.start)
            s.width = max(round(100 * ((s.end - s.start).days + 1) / span, 3), 0.6)
        if r.approved_on:
            r.marker_left = pct(r.approved_on)

    ticks, d = [], date(start.year, start.month, 1)
    weekly = span <= 62
    if weekly:
        d = start - timedelta(days=start.weekday())
    while d <= end:
        if d >= start:
            ticks.append({"left": pct(d), "label": d.strftime("%d %b") if weekly else d.strftime("%b %Y")})
        d = d + timedelta(days=7) if weekly else date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return {"rows": rows, "ticks": ticks, "today_left": pct(today), "start": start, "end": end, "today": today,
            "phases": PHASES}
