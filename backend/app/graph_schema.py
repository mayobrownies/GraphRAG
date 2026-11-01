"""Inputs for the paper graph with one Paper node per document."""
from dataclasses import dataclass
import math
import unicodedata

# Lowest cosine similarity stored as an edge. Tune once real paper embeddings exist.
MIN_WEIGHT = 0.3


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def normalize_name(name: str) -> str:
    required_text(name, "name")
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


@dataclass(frozen=True)
class Paper:
    doc_id: str
    name: str
    embedding: tuple[float, ...]

    def __post_init__(self):
        required_text(self.doc_id, "doc_id")
        normalize_name(self.name)
        values = tuple(self.embedding)
        if not values or any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
            raise ValueError("embedding must be a non-empty list of finite numbers")
        object.__setattr__(self, "embedding", values)
