"""AI assistant chat: a Groq-hosted language model that answers questions about the open project.

Each question goes to Groq together with a short summary of the project: counts, cable lengths, BOQ total,
QA issues, the design rules, and what the trained Photo AI model found on the survey photos. Raw coordinates,
personal names from the home list and photos themselves are not sent. The assistant only advises; it never
changes the design.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass

from . import calc, validate
from .model import Design

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_MESSAGES = 20
MAX_CHARS = 4000

SYSTEM = (
    "You are ArchPlanner's assistant for FTTH (fibre-to-the-home) network planning in Kenya. You help planners "
    "with survey data, HLD/LLD design, splitter and FAT sizing, fibre allocation, BOM/BOQ and QA before approval. "
    "Use the project summary below as the facts about the open project; say so when something is not in it rather "
    "than guessing. Photo findings come from the company's trained survey-photo model: treat them as suggestions "
    "a planner must confirm. Point to the app's tools by name (Auto-design, Auto-allocate, Assign homes, "
    "Survey & validation, HLD map, Materials & rules, LLD drawing, Generate deliverables) when they solve the "
    "question. Be concise, use short lists, and give numbers with units. You cannot change the design yourself."
)


@dataclass
class Config:
    key: str = ""
    model: str = "openai/gpt-oss-120b"
    url: str = GROQ_URL
    timeout: float = 60.0

    @property
    def enabled(self) -> bool:
        return bool(self.key and self.model and self.url)


class AssistantError(Exception):
    pass


def project_context(d: Design) -> str:
    """Compact, anonymised facts about the project for the model."""
    s = calc.summary(d)
    issues = validate.validate(d)
    sev = Counter(i["severity"] for i in issues)
    codes = Counter((i["severity"], i["code"]) for i in issues)
    lines = calc.bom(d)
    top = sorted((ln for ln in lines if ln.total), key=lambda ln: -ln.total)[:12]
    r = d.rules
    photos = [p for p in d.photos if p.analysis]
    found = Counter(o.get("label") for p in photos for o in p.analysis.get("objects", []) if o.get("label"))
    photo_issues = [i for p in photos for i in p.analysis.get("issues", [])][:15]
    ctx = {
        "project": {k: getattr(d.info, k) for k in ("name", "area", "client", "region", "zone", "cluster", "currency",
                                                    "design_status", "survey_status", "design_style",
                                                    "interception_node", "interception_nodes") if hasattr(d.info, k)},
        "counts": {"poles": s["poles"], "new_poles": s["poles_new"], "premises": s["homes"],
                   "homepasses": s["homepasses"], "premises_without_fat": s["homes_unassigned"],
                   "equipment": s["nodes"], "splitters": dict(Counter(f"stage {x.stage} 1x{x.outputs}"
                                                                     for x in d.splitters)),
                   "cables": dict(Counter(f"{c.status} {c.kind} {c.cores}C" for c in d.cables)),
                   "fats_by_ports": dict(Counter(n.ports or r.default_fat_ports for n in d.nodes if n.kind == "FAT"))},
        "proposed_cable_m": s["cable_m"],
        "boq_total": s["boq_total"],
        "top_boq_lines": [{"item": ln.description[:60], "qty": round(ln.qty, 1), "unit": ln.unit, "total": ln.total}
                          for ln in top],
        "qa": {"errors": sev.get("error", 0), "warnings": sev.get("warning", 0),
               "by_code": {f"{k[0]}:{k[1]}": n for k, n in codes.most_common(15)},
               "first_errors": [i["message"][:160] for i in issues if i["severity"] == "error"][:10]},
        "rules": {k: getattr(r, k) for k in ("default_fat_ports", "default_fat_split", "default_pon_split",
                                             "fat_load_take_rate", "share_fat_splitters", "cable_extra_pct",
                                             "slack_per_cable_end_m", "slack_per_passing_node_m",
                                             "tension_pole_passing", "upb_tension_per_bracket")},
        "photo_ai": {"photos": len(d.photos), "analysed": len(photos), "objects_found": dict(found.most_common(15)),
                     "issues_seen": photo_issues},
    }
    return json.dumps(ctx, default=str, separators=(",", ":"))


def clean_messages(messages) -> list[dict]:
    """The conversation as the client sent it, limited to user / assistant turns of reasonable size."""
    if not isinstance(messages, list) or not messages:
        raise AssistantError("Ask a question first")
    out = []
    for m in messages[-MAX_MESSAGES:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()[:MAX_CHARS]
        if text:
            out.append({"role": m["role"], "content": text})
    if not out or out[-1]["role"] != "user":
        raise AssistantError("Ask a question first")
    return out


IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp")
TEXT_TYPES = (".csv", ".txt", ".kml", ".json", ".geojson", ".md")
SHEET_TYPES = (".xlsx", ".xlsm")
MAX_IMAGE = 10 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_ATTACHED_CHARS = 12000


def attachment_text(name: str, data: bytes, vision_cfg=None) -> str:
    """What the model is told about an attached file. Photos go through the trained survey-photo model first;
    spreadsheets and text files are passed as text (shortened)."""
    from . import vision
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_TYPES:
        if len(data) > MAX_IMAGE:
            raise AssistantError("Photos must be smaller than 10 MB")
        if vision_cfg is None or not vision_cfg.enabled:
            raise AssistantError("Photo AI is not set up on this server, so photos cannot be checked")
        try:
            r = vision.analyse(data, vision_cfg)
        except vision.VisionError as e:
            raise AssistantError(str(e)) from None
        except OSError:
            raise AssistantError("That file is not a readable image") from None
        found = "; ".join(f"{o['label']}" + (f" ({o['confidence']:.0%})" if o.get("confidence") is not None else "")
                          + (f" - {o['note']}" if o.get("note") else "") for o in r.get("objects", [])) or "nothing"
        return (f"Attached photo '{name}', checked by the company's trained survey-photo model. Objects: {found}. "
                f"Pole / equipment labels read: {', '.join(r.get('pole_labels') or []) or 'none'}. "
                f"Visible issues: {', '.join(r.get('issues') or []) or 'none'}. Scene: {r.get('summary') or '-'}")
    if len(data) > MAX_FILE:
        raise AssistantError("Files must be smaller than 2 MB")
    if ext in SHEET_TYPES:
        from .importers import read_workbook
        try:
            sheets = read_workbook(data)
        except Exception:  # noqa: BLE001 - any unreadable workbook
            raise AssistantError("That spreadsheet could not be read") from None
        parts = []
        for title, rows in sheets[:5]:
            cols = list(rows[0].keys()) if rows else []
            lines = [", ".join(map(str, cols))] + [", ".join("" if r.get(c) is None else str(r.get(c)) for c in cols)
                                                   for r in rows[:200]]
            parts.append(f"Sheet '{title}' ({len(rows)} rows):\n" + "\n".join(lines))
        text = "\n\n".join(parts)
    elif ext in TEXT_TYPES:
        text = data.decode("utf-8", "replace")
    else:
        raise AssistantError("Attach a photo (JPG, PNG, WEBP), a spreadsheet (XLSX, CSV) or a text file (TXT, KML, JSON)")
    cut = len(text) > MAX_ATTACHED_CHARS
    return f"Attached file '{name}'" + (" (first part only)" if cut else "") + ":\n" + text[:MAX_ATTACHED_CHARS]


def chat(d: Design, messages, cfg: Config, attachment: str | None = None) -> str:
    if not cfg.enabled:
        raise AssistantError("The AI assistant is not set up on this server: add AI_CHAT_KEY (a Groq API key) to its environment variables")
    convo = clean_messages(messages)
    if attachment:  # the file goes with the latest question
        convo[-1]["content"] += "\n\n" + attachment
    body = {"model": cfg.model, "temperature": 0.3, "max_tokens": 900,
            "messages": [{"role": "system", "content": SYSTEM + "\n\nProject summary (JSON):\n" + project_context(d)}]
            + convo}
    req = urllib.request.Request(cfg.url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.key}",
                                          "User-Agent": "ArchPlanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise AssistantError(f"{e.code} from the AI service: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise AssistantError(f"Could not reach the AI service: {getattr(e, 'reason', e)}") from None
    except json.JSONDecodeError:
        raise AssistantError("The AI service did not return JSON") from None
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError):
        raise AssistantError("The AI service returned no answer") from None
