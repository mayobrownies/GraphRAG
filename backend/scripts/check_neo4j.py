"""Run from backend: python -m scripts.check_neo4j [--init-schema].

Reads the repository-root .env or existing process environment. No secrets are
printed. Schema creation is explicit; the default check only reads the server.
"""
import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.repositories.graph_store import GraphStore


async def check(initialize: bool):
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    names = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing environment variables: " + ", ".join(missing))
    store = GraphStore.connect(*(os.environ[name] for name in names), database=os.getenv("NEO4J_DATABASE", "neo4j"))
    try:
        await store.verify_connection()
        print("Neo4j connection and database query succeeded.")
        if initialize:
            await store.create_constraints()
            print("Neo4j graph uniqueness constraints are ready.")
    except (Neo4jError, ServiceUnavailable) as error:
        raise SystemExit(f"Neo4j check failed: {getattr(error, 'code', type(error).__name__)}") from None
    finally:
        await store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-schema", action="store_true")
    asyncio.run(check(parser.parse_args().init_schema))
