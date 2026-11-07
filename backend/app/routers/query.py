"""
query: question + group_id -> GraphRAG Response over the group's 'ready' papers
benchmark: same question and group -> {"standard": Response, "graph": Response} - should each have their own reports
404 for a group the user doesn't own; a group with no 'ready' papers has no context to answer from
"""