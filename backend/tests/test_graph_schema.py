import math

import pytest

from app.graph_schema import Paper, normalize_name


def test_names_normalize_unicode_whitespace_and_case():
    assert normalize_name("  ＢＲＣＡ１  Gene\n") == "brca1 gene"


def test_paper_stores_embedding_as_tuple():
    paper = Paper("doc", "BRCA1 review", [0.1, 2, -3.5])
    assert paper.embedding == (0.1, 2, -3.5)


@pytest.mark.parametrize("doc_id,name", [("", "name"), ("doc", ""), ("doc", "   ")])
def test_paper_requires_doc_id_and_name(doc_id, name):
    with pytest.raises(ValueError):
        Paper(doc_id, name, [1.0])


@pytest.mark.parametrize("embedding", [[], [math.nan], [math.inf], [True], ["0.5"], [None]])
def test_paper_rejects_empty_or_non_numeric_embedding(embedding):
    with pytest.raises(ValueError):
        Paper("doc", "name", embedding)
