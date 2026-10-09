"""
query: question + selected 'ready' document ids -> GraphRAG Response
benchmark: same question and documents -> {"standard": Response, "graph": Response} - should each have their own reports
Reject document ids the user can't access or that aren't 'ready'.
"""