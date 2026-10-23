from pydantic import BaseModel


class User(BaseModel):
    # id is the Supabase auth.users id (the token's sub): the "account" in Qdrant and Neo4j
    id: str
    email: str | None = None
