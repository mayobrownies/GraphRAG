"""
Query and benchmark tests (3.6, 3.7, 3.10)
GraphRAG response has answer, source references with page numbers, and the graph path used
No usable context: support 'none', LLM not called (3.6.5)
Partial context: support 'partial' with the evidence found (3.7.5)
Document ids that are not 'ready' or belong to another account are rejected
Benchmark returns standard and graph responses for the same question and documents; standard has no graph path
"""
