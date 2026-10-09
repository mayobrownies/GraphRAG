"""
extraction tests (3.5.1, 3.5.2)
Entity and relationship types not in graph_schema are dropped
A relationship with the wrong source/target types (e.g. Disease TREATS Drug) is dropped
Names are normalized so "Metformin " and "metformin" get the same entity id
Malformed or non-JSON LLM output is handled without crashing the job
Every accepted entity and relationship keeps its chunk id
"""
