from app.schema import normalize_name, validate_extraction

RAW = {
    "entities": [
        {"name": "Metformin", "type": "drug"},
        {"name": "  type 2 diabetes. ", "type": "Disease"},
        {"name": "Metformin", "type": "Drug"},          # duplicate
        {"name": "Banana", "type": "Fruit"},            # type not in schema
    ],
    "relations": [
        {"source": "Metformin", "target": "Type 2 Diabetes", "type": "treats"},
        {"source": "Metformin", "target": "Unknown", "type": "TREATS"},      # unknown endpoint
        {"source": "Metformin", "target": "Type 2 Diabetes", "type": "LIKES"},  # type not allowed
        {"source": "Metformin", "target": "Type 2 Diabetes", "type": "TREATS"},  # duplicate edge
    ],
}


def test_normalize():
    assert normalize_name("  Type  2 Diabetes. ") == "type 2 diabetes"


def test_validation_filters_and_dedupes():
    out = validate_extraction(RAW, "global")
    assert [e["type"] for e in out.entities] == ["Drug", "Disease"]
    assert len(out.relations) == 1 and out.relations[0]["type"] == "TREATS"
    assert out.rejected == 3


def test_ids_are_scoped():
    a = validate_extraction(RAW, "user-a").entities[0]["id"]
    b = validate_extraction(RAW, "user-b").entities[0]["id"]
    assert a != b
