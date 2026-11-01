"""Validated extraction inputs and stable identities for the medical graph.

Identifiers are shared with Qdrant's entity_ids payload. No LLM output is
interpolated into Cypher unless it has passed this module's fixed allowlist.
"""
from dataclasses import dataclass
import json
import unicodedata
from uuid import NAMESPACE_URL, uuid5

NODE_TYPES = frozenset({"Gene", "Protein", "Disease", "Drug"})
RELATIONSHIP_RULES = {
    "ENCODES": frozenset({("Gene", "Protein")}),
    "ASSOCIATED_WITH": frozenset({("Gene", "Disease"), ("Protein", "Disease")}),
    "TARGETS": frozenset({("Drug", "Protein")}),
    "STUDIED_FOR": frozenset({("Drug", "Disease")}),
    "TREATS": frozenset({("Drug", "Disease")}),
}
RELATIONSHIP_TYPES = frozenset(RELATIONSHIP_RULES)


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def normalize_name(name: str) -> str:
    required_text(name, "name")
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, json.dumps(parts, ensure_ascii=False)))


def entity_id(account: str, node_type: str, name: str) -> str:
    required_text(account, "account")
    if node_type not in NODE_TYPES:
        raise ValueError(f"Unsupported node type: {node_type}")
    return stable_id("graphrag-entity-v1", account, node_type, normalize_name(name))


@dataclass(frozen=True)
class Entity:
    name: str
    node_type: str

    def __post_init__(self):
        normalize_name(self.name)
        if self.node_type not in NODE_TYPES:
            raise ValueError(f"Unsupported node type: {self.node_type}")

    def id_for(self, account: str) -> str:
        return entity_id(account, self.node_type, self.name)


@dataclass(frozen=True)
class Relationship:
    source: Entity
    target: Entity
    relationship_type: str

    def __post_init__(self):
        pair = (self.source.node_type, self.target.node_type)
        if pair not in RELATIONSHIP_RULES.get(self.relationship_type, ()):
            raise ValueError(f"Unsupported relationship: {pair} {self.relationship_type}")


@dataclass(frozen=True)
class GraphChunk:
    doc_id: str
    chunk_id: str
    page: int
    text: str
    entities: tuple[Entity, ...] = ()
    relationships: tuple[Relationship, ...] = ()

    def __post_init__(self):
        required_text(self.doc_id, "doc_id")
        required_text(self.chunk_id, "chunk_id")
        required_text(self.text, "text")
        if type(self.page) is not int or self.page < 1:
            raise ValueError("page must be a positive integer")
        declared = set(self.entities)
        if any(r.source not in declared or r.target not in declared for r in self.relationships):
            raise ValueError("Relationship endpoints must be declared in the same chunk")
