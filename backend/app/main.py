import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import repo
from .config import get_settings
from .routers import documents, graph, query
from .services import graph_store, vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    graph_store.init_constraints()
    vector_store.ensure_collection()
    repo.mark_stale_processing()  # req 3.4.5: state survives restarts
    log.info("Startup complete")
    yield


app = FastAPI(title="Medical GraphRAG API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(documents.router)
app.include_router(documents.profile_router)
app.include_router(query.router)
app.include_router(graph.router)


@app.get("/health")
def health():
    return {"status": "ok"}
