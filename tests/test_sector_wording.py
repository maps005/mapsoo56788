"""Non-fibre projects' documents speak their sector: no FTTH, homepasses, FATs, splitters or cores in them."""
import io
import re
import zipfile

import pytest

from ftth import occupations, script, sectors
from ftth.exporters import package
from ftth.exporters.common import stamp
from ftth.model import Design

FIBRE = re.compile(r"\b(FTTH|fibre|fiber|homepass\w*|HPs?|cores?|OLT|splitters?|FATs?|PON|drop cable|splice\w*)\b", re.I)
NET = """name "Kiambu extension"
pop S01 -1.3120,36.8200
pole M001 -1.3122,36.8206 status=proposed
pole M002 -1.3125,36.8213 status=proposed
home K001 -1.3127,36.8215 units=2
fat MT01 on=M002 ports=8
cable L001 main {size} S01 > M001 > M002
boundary -1.3110,36.8190; -1.3110,36.8230; -1.3140,36.8230; -1.3140,36.8190
assign max=250
"""


def _text(fmt, data):
    if fmt == "pdf":
        from pypdf import PdfReader
        return " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    if fmt == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True)
        return " ".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v)
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8", "replace")


@pytest.mark.parametrize("sector", ["water", "electricity", "sanitation"])
def test_documents_use_the_sectors_words(sector):
    d = Design()
    sectors.apply(d, sector)
    script.run(d, NET.format(size=sectors.get(sector)["sizes"][-3]), occupations.features(sector, ""))
    assert "splicing" not in package.relevant(d)
    found = []
    for deliv in package.relevant(d):
        if deliv == "project":  # the raw data workbook keeps the data model's field names
            continue
        for fmt in package.DELIVERABLES[deliv]:
            if fmt in ("pdf", "xlsx", "docx"):
                t = _text(fmt, package.build(d, deliv, fmt, stamp(d, 1), None))
                found += [f"{deliv}.{fmt}: ...{t[max(0, m.start() - 30):m.end() + 20]}..." for m in FIBRE.finditer(t)]
    assert not found, "\n".join(found[:10])
