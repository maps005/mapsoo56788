"""Survey photo analysis with a vision model.

A photo is sent to the configured provider only when the planner presses "Analyse" on it. Two providers:
- "roboflow": a Roboflow serverless workflow (e.g. a Qwen-VL workflow) called with the image and a prompt;
- "groq": an OpenAI-compatible chat-completions endpoint with a vision model (Groq by default).
The answer is reduced to suggestions (objects with confidence, pole labels read from tags, visible issues)
that the planner confirms; nothing in the design changes automatically.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

CLASSES = [
    # primary FTTH infrastructure
    "utility pole", "concrete pole", "wooden pole", "metal pole", "fibre optic cable", "fibre distribution box",
    "fibre access terminal (FAT)", "splice closure", "junction box", "optical network terminal (ONT)",
    "fibre splitter enclosure", "telecommunications cabinet", "fibre distribution hub",
    # supporting infrastructure
    "power line", "streetlight", "road crossing", "cable attachment hardware", "pole bracket", "building",
    "apartment block", "residential house", "road", "manhole", "underground duct", "utility access chamber",
    # survey context
    "pole identification label", "visible cable damage", "damaged pole", "obstructed cable route",
]

PROMPT = (
    "You inspect FTTH (fibre-to-the-home) survey photographs taken on Kenyan roads, estates and buildings. "
    "List only what is clearly visible; do not guess. Use these classes: " + "; ".join(CLASSES) + ". "
    "Read any pole identification label or equipment tag text exactly as written. "
    "Reply with JSON only, no prose, in this form: "
    '{"objects": [{"label": "<class>", "confidence": <0-1>, "box": [x, y, width, height] or null, "note": "<short>"}], '
    '"pole_labels": ["<text read from tags>"], "issues": ["<visible damage, leaning pole, obstruction...>"], '
    '"summary": "<one sentence describing the scene for a survey report>"}. '
    "Boxes are fractions of the image width and height."
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class Config:
    provider: str = ""   # "roboflow" or "groq"
    url: str = ""        # Roboflow workflow URL, or an OpenAI-compatible endpoint for "groq"
    key: str = ""
    model: str = ""      # Roboflow workflow model_version / Groq vision model id
    timeout: float = 90.0

    @property
    def enabled(self) -> bool:
        return self.provider in ("roboflow", "groq") and bool(self.key) and (self.provider == "groq" or bool(self.url)) \
            and (self.provider == "roboflow" or bool(self.model))

    @property
    def label(self) -> str:
        return {"roboflow": "Roboflow workflow", "groq": "Groq"}.get(self.provider, self.provider) + \
            (f" ({self.model})" if self.model else "")


class VisionError(Exception):
    pass


def prepare_image(data: bytes, max_side: int = 1600) -> bytes:
    """JPEG no larger than max_side pixels on its longest side (smaller uploads, same detail for detection)."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=88)
        return out.getvalue()


def _post(url: str, key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "User-Agent": "ArchPlanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise VisionError(f"{e.code} from the vision service: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise VisionError(f"Could not reach the vision service: {getattr(e, 'reason', e)}") from None
    except json.JSONDecodeError:
        raise VisionError("The vision service did not return JSON") from None


def _json_in_text(text: str):
    """First JSON object in a model's text answer (models sometimes wrap it in prose or code fences)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for k in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            if depth == 0:
                try:
                    return json.loads(text[start:k + 1])
                except json.JSONDecodeError:
                    break
        start = text.find("{", start + 1)
    return None


def _walk(x):
    yield x
    if isinstance(x, dict):
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _clip(v, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def normalise(raw) -> dict:
    """Suggestions from any provider answer: a JSON object in text, or Roboflow-style predictions."""
    found = None
    for node in _walk(raw):
        if isinstance(node, dict) and isinstance(node.get("objects"), list):
            found = node
            break
        if isinstance(node, str) and '"objects"' in node:
            found = _json_in_text(node)
            if found:
                break
    objects = []
    if found:
        for o in found.get("objects", [])[:60]:
            if not isinstance(o, dict) or not o.get("label"):
                continue
            box = o.get("box")
            box = [_clip(b) for b in box][:4] if isinstance(box, list) and len(box) == 4 else None
            objects.append({"label": str(o["label"])[:60], "confidence": _clip(o.get("confidence")),
                            "box": box if box and None not in box else None, "note": str(o.get("note") or "")[:120]})
    else:  # Roboflow object-detection predictions
        for node in _walk(raw):
            if isinstance(node, dict) and isinstance(node.get("predictions"), list):
                w = node.get("image", {}).get("width") if isinstance(node.get("image"), dict) else None
                h = node.get("image", {}).get("height") if isinstance(node.get("image"), dict) else None
                for p in node["predictions"][:60]:
                    if isinstance(p, dict) and p.get("class"):
                        box = None
                        if w and h and all(k in p for k in ("x", "y", "width", "height")):
                            box = [_clip((p["x"] - p["width"] / 2) / w), _clip((p["y"] - p["height"] / 2) / h),
                                   _clip(p["width"] / w), _clip(p["height"] / h)]
                        objects.append({"label": str(p["class"])[:60], "confidence": _clip(p.get("confidence")),
                                        "box": box, "note": ""})
                break
    text = lambda k: [str(x)[:80] for x in (found or {}).get(k, []) if str(x).strip()][:20]  # noqa: E731
    summary = str((found or {}).get("summary") or "")[:300]
    if not found and not objects:
        texts = [n for n in _walk(raw) if isinstance(n, str) and len(n) > 20]
        summary = (texts[0] if texts else "")[:300]
    return {"objects": sorted(objects, key=lambda o: -(o["confidence"] or 0)), "pole_labels": text("pole_labels"),
            "issues": text("issues"), "summary": summary}


def analyse(image: bytes, cfg: Config) -> dict:
    if not cfg.enabled:
        raise VisionError("Photo AI is not set up: set PHOTO_AI_PROVIDER, PHOTO_AI_KEY and PHOTO_AI_URL / "
                          "PHOTO_AI_MODEL on the server (see .env.example)")
    b64 = base64.b64encode(prepare_image(image)).decode()
    if cfg.provider == "roboflow":
        inputs = {"image": {"type": "base64", "value": b64}, "prompt": PROMPT}
        if cfg.model:
            inputs["model_version"] = cfg.model
        raw = _post(cfg.url, cfg.key, {"inputs": inputs}, cfg.timeout)
    else:
        raw = _post(cfg.url or GROQ_URL, cfg.key, {
            "model": cfg.model, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        }, cfg.timeout)
    result = normalise(raw)
    result["provider"] = cfg.label
    return result
