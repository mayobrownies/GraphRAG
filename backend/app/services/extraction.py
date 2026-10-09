"""
Entity and relationship extraction with Qwen through Ollama
Send one chunk and the allowed types from graph_schema to models.chat, and ask for JSON back
Validate the result: drop any type not in graph_schema, normalize names, assign entity ids
Output per chunk: accepted entities and relationships, each tied to its chunk id
"""