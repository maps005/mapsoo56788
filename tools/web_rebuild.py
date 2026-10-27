"""Rebuild a project through the running web app, as a planner would, and compare with approved files.

Usage: python tools/web_rebuild.py BASE_URL SESSION_ID HLD.kmz HOME_LIST.xlsx APPROVED_BOM.xlsx APPROVED_BOQ.xlsx

Steps (each one is a button in the app): New project -> import HLD KMZ -> import home list ->
Auto-assign homes -> Auto-allocate fibres -> download BOM / BOQ / pole summary / package.
"""
from __future__ import annotations

import http.cookiejar
import io
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from openpyxl import load_workbook



def read_approved_boq(path: Path) -> dict[str, tuple[float, float]]:
    """Material lines of a V Squared BOQ: description -> (quantity, rate)."""
    out = {}
    for r in load_workbook(path, data_only=True).active.iter_rows(values_only=True):
        c = [x for x in r if x is not None]
        # item, description, unit, price, quantity[, total]: totals may be formulas without stored values
        if len(c) >= 5 and isinstance(c[3], (int, float)) and isinstance(c[4], (int, float)) and isinstance(c[1], str):
            out[c[1].strip()] = (float(c[4]), float(c[3]))
    return out


class Web:
    def __init__(self, base: str, session: str):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        host = urllib.parse.urlparse(self.base).hostname
        self.jar.set_cookie(http.cookiejar.Cookie(0, "sessionid", session, None, False, host, False, False, "/", True,
                                                  False, None, False, None, None, {}))
        self.op.open(self.base + "/").read()  # sets csrftoken
        self.csrf = next(c.value for c in self.jar if c.name == "csrftoken")
        self.calls = 0

    def req(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None):
        self.calls += 1
        r = urllib.request.Request(self.base + path, data=body, method=method,
                                   headers={"X-CSRFToken": self.csrf, "Referer": self.base + "/",
                                            **({"Content-Type": ctype} if ctype else {})})
        with self.op.open(r) as resp:
            return resp.read()

    def json(self, method: str, path: str, obj=None):
        return json.loads(self.req(method, path, json.dumps(obj or {}).encode(), "application/json"))

    def upload(self, path: str, file: Path, **fields):
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n'.encode() + file.read_bytes() + b"\r\n")
        return json.loads(self.req("POST", path, b"".join(parts) + f"--{b}--\r\n".encode(),
                                   f"multipart/form-data; boundary={b}"))


def xlsx_rows(data: bytes) -> list[list]:
    ws = load_workbook(io.BytesIO(data), data_only=True).active
    return [list(r) for r in ws.iter_rows(values_only=True)]


def main(base, session, kmz, homes, bom_xlsx, boq_xlsx):
    t0 = time.time()
    w = Web(base, session)
    st = w.json("POST", "/api/projects", {"name": f"Web rebuild test {time.strftime('%H:%M')}"})
    pid = st["id"]
    imp1 = w.upload(f"/api/projects/{pid}/import", Path(kmz), target="auto", status="existing")
    imp2 = w.upload(f"/api/projects/{pid}/import", Path(homes), target="homes", status="existing")
    a = w.json("POST", f"/api/projects/{pid}/assign-homes")
    al = w.json("POST", f"/api/projects/{pid}/allocate")
    calc = json.loads(w.req("GET", f"/api/projects/{pid}/calc"))
    state = json.loads(w.req("GET", f"/api/projects/{pid}"))
    files = {k: len(w.req("GET", f"/api/projects/{pid}/export/{k}")) for k in
             ("pole_summary.xlsx", "bom.xlsx", "boq.xlsx", "lld.dxf", "lld.pdf", "hld.kmz", "splicing.pdf", "report.docx")}
    # compare BOQ lines by description / quantity with the approved BOQ
    approved = read_approved_boq(Path(boq_xlsx))
    mine = {l["description"].strip().lower(): l for l in calc["bom"]}
    rows = []
    for desc, (qty, rate) in approved.items():
        m = mine.get(desc.strip().lower())
        rows.append((desc, qty, m["qty"] if m else None, rate, m["rate"] if m else None))
    appr_total = sum(q * r for _, (q, r) in approved.items())
    print(json.dumps({
        "project": pid, "seconds": round(time.time() - t0, 1), "api_calls": w.calls,
        "import_hld": {"added": imp1["import"]["added"], "first_notes": imp1["import"]["problems"][:4]},
        "import_home_list": {"added": imp2["import"]["added"], "updated": imp2["import"]["updated"]},
        "assigned": a["result"]["assigned"], "unserved": len(a["result"]["unassigned"]),
        "allocation_issues": len(al["result"]["issues"]),
        "counts": state["counts"], "homepasses": state["summary"]["homepasses"],
        "boq_total": calc["boq_total"], "approved_boq_total": appr_total,
        "files_bytes": files,
    }, indent=1))
    print("\nBOQ line comparison (approved qty -> system qty; rate approved -> system):")
    for desc, q_a, q_m, r_a, r_m in rows:
        flag = "" if q_m is not None and abs(q_a - q_m) < 1e-6 and r_m == r_a else "  <--"
        print(f"  {desc[:58]:58} {q_a:>8g} -> {q_m if q_m is not None else '-':>8}   {r_a:>7g} -> {r_m}{flag}")


if __name__ == "__main__":
    main(*sys.argv[1:7])
