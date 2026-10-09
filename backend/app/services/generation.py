"""
Answer generation
Build the prompt from the retrieved chunks (with document and page) and the graph relationships
The LLM answers ONLY from that context
If the context only partly answers the question, return support 'partial' with the evidence that was found
If the context is empty, don't call the LLM
Input: the question plus the merged context from retrieval (chunks with document and page, graph relationships with their paths)
Output: a Response (schemas.py) with answer text, source references (document, chunk, page), the exact graph path used, and support level
GraphRAG and Standard RAG both call this with the same model and settings so the benchmark is fair
"""