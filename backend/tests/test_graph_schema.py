import pytest

from app.graph_schema import Entity, GraphChunk, Relationship, entity_id, normalize_name


def test_names_normalize_unicode_whitespace_and_case():
    assert normalize_name("  ＢＲＣＡ１  Gene\n") == "brca1 gene"


def test_identity_is_stable_but_separated_by_account_and_type():
    identity = entity_id("alice", "Gene", " BRCA1 ")
    assert identity == entity_id("alice", "Gene", "brca1")
    assert identity != entity_id("bob", "Gene", "brca1")
    assert identity != entity_id("alice", "Protein", "brca1")


@pytest.mark.parametrize("name,node_type", [("", "Gene"), ("x", "Anything"), ("x", "Gene) DELETE n")])
def test_rejects_empty_names_and_unapproved_types(name, node_type):
    with pytest.raises(ValueError):
        Entity(name, node_type)


def test_relationship_validates_direction_and_keeps_studied_for_separate():
    drug, disease = Entity("d", "Drug"), Entity("illness", "Disease")
    assert Relationship(drug, disease, "STUDIED_FOR") != Relationship(drug, disease, "TREATS")
    with pytest.raises(ValueError):
        Relationship(disease, drug, "TREATS")
    with pytest.raises(ValueError):
        Relationship(drug, disease, "TREATS] DELETE n")


@pytest.mark.parametrize("page", [0, -1, True, 1.5])
def test_chunk_requires_positive_integer_page(page):
    with pytest.raises(ValueError):
        GraphChunk("doc", "chunk", page, "text")


def test_chunk_rejects_undeclared_relationship_endpoint():
    gene, protein = Entity("a", "Gene"), Entity("b", "Protein")
    with pytest.raises(ValueError):
        GraphChunk("doc", "chunk", 1, "text", (gene,), (Relationship(gene, protein, "ENCODES"),))
