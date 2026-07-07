"""JSON document for the Typst template (assets/cv.typ, via sys.inputs "data").

The template dereferences every field directly (e.g.
`data.personal_info.phone != none`), so every key must be present in the
JSON — None serializes to null, which Typst reads as `none`. Open-ended
experience end dates are normalized to the literal "Present" so the
date range never renders with a dangling dash.
"""

import json

from cv_shared.models import CV

PRESENT = "Present"


def cv_to_typst_json(cv: CV) -> str:
    doc = cv.model_dump(mode="json")
    for exp in doc["experience"]:
        if exp["end_date"] is None:
            exp["end_date"] = PRESENT
    return json.dumps(doc, ensure_ascii=False)
