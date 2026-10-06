"""Allowed graph schema, extraction validation and normalization (req 3.5.2, 3.5.3)."""
import hashlib
import re
from dataclasses import dataclass, field

NODE_TYPES = [
    "Disease", "Symptom", "Drug", "Treatment", "Procedure", "Gene",
    "Protein", "Biomarker", "Organism", "BodyPart", "RiskFactor",
]
REL_TYPES = [
    "TREATS", "CAUSES", "ASSOCIATED_WITH", "SYMPTOM_OF", "INTERACTS_WITH",
    "DIAGNOSES", "LOCATED_IN", "PREVENTS", "INCREASES_RISK_OF",
]
_NODE_LOOKUP = {t.lower(): t for t in NODE_TYPES}
_REL_LOOKUP = {t: t for t in REL_TYPES}
MAX_NAME_LEN = 120


def normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name)).strip().lower()
    return name.strip(" .,;:()[]\"'")


def entity_id(scope: str, etype: str, norm: str) -> str:
    return hashlib.sha1(f"{scope}|{etype}|{norm}".encode()).hexdigest()[:16]


@dataclass
class ValidatedExtraction:
    entities: list[dict] = field(default_factory=list)   # name, norm, type, id
    relations: list[dict] = field(default_factory=list)  # a, b, type
    rejected: int = 0


def validate_extraction(raw: dict, scope: str) -> ValidatedExtraction:
    out = ValidatedExtraction()
    by_norm: dict[str, dict] = {}
    for e in (raw.get("entities") or []):
        if not isinstance(e, dict):
            out.rejected += 1
            continue
        name = str(e.get("name", "")).strip()
        etype = _NODE_LOOKUP.get(str(e.get("type", "")).strip().lower())
        norm = normalize_name(name)
        if not etype or not norm or len(name) > MAX_NAME_LEN:
            out.rejected += 1
            continue
        ent = {"name": name, "norm": norm, "type": etype, "id": entity_id(scope, etype, norm), "scope": scope}
        if norm not in by_norm:
            by_norm[norm] = ent
            out.entities.append(ent)
    seen = set()
    for r in (raw.get("relations") or []):
        if not isinstance(r, dict):
            out.rejected += 1
            continue
        rtype = _REL_LOOKUP.get(str(r.get("type", "")).strip().upper().replace(" ", "_"))
        a = by_norm.get(normalize_name(r.get("source", "")))
        b = by_norm.get(normalize_name(r.get("target", "")))
        if not rtype or not a or not b or a["id"] == b["id"]:
            out.rejected += 1
            continue
        key = (a["id"], b["id"], rtype)
        if key in seen:
            continue
        seen.add(key)
        out.relations.append({"a": a["id"], "b": b["id"], "type": rtype})
    return out
