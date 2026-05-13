from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import ROOT_DIR, UPLOADS_DIR
from backend.models import QuestionRequest, SummaryRequest, UploadResponse
from backend.storage import list_books, load_book, save_book
from services.graph.builder import build_temporal_graph
from services.graph.storage import load_graph, save_graph
from services.ingest.parser import build_book_record, slugify
from services.orchestration.service import OrchestrationService
from services.persona.persona_service import list_personas
from services.qa.answering import build_answer
from services.summary.chapter_summary import summarize_chapter


app = FastAPI(title="Muse Reading MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = ROOT_DIR / "frontend" / "public"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


def ensure_demo_book_loaded() -> None:
    demo_path = ROOT_DIR / "examples" / "muse_demo_book.txt"
    if not demo_path.exists():
        return
    title = demo_path.stem
    record = build_book_record(title=title, raw_text=demo_path.read_text(encoding="utf-8"), source_path=demo_path)
    save_book(record)
    save_graph(build_temporal_graph(record))


@app.on_event("startup")
def startup_event() -> None:
    ensure_demo_book_loaded()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/books")
def books() -> list[dict[str, str]]:
    return list_books()


@app.get("/api/personas")
def personas():
    return [persona.model_dump() for persona in list_personas()]


@app.get("/api/books/{book_id}")
def book_detail(book_id: str):
    book = load_book(book_id)
    chapters: dict[int, list[dict[str, str | int]]] = {}
    for chunk in book.chunks:
        chapters.setdefault(chunk.chapter_index, []).append(
            {
                "chunk_id": chunk.chunk_id,
                "paragraph_index": chunk.paragraph_index,
                "text": chunk.text,
            }
        )
    return {
        "book_id": book.book_id,
        "title": book.title,
        "chapter_count": book.chapter_count,
        "chapters": chapters,
    }


@app.get("/api/books/{book_id}/graph")
def graph_detail(book_id: str):
    graph = load_graph(book_id)
    return {
        "graph_id": graph.graph_id,
        "book_id": graph.book_id,
        "title": graph.title,
        "metadata": graph.metadata,
        "episodes": [episode.model_dump() for episode in graph.episodes[:10]],
        "entities": [entity.model_dump() for entity in graph.entities[:20]],
        "relations": [relation.model_dump() for relation in graph.relations[:20]],
        "communities": [community.model_dump() for community in graph.communities[:10]],
        "sagas": [saga.model_dump() for saga in graph.sagas[:10]],
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_book(file: UploadFile = File(...)) -> UploadResponse:
    suffix = Path(file.filename or "uploaded.txt").suffix or ".txt"
    raw_bytes = await file.read()
    text = raw_bytes.decode("utf-8", errors="ignore")
    title = Path(file.filename or "uploaded-book").stem
    safe_name = slugify(title)
    upload_path = UPLOADS_DIR / f"{safe_name}{suffix}"
    upload_path.write_text(text, encoding="utf-8")
    record = build_book_record(title=title, raw_text=text, source_path=upload_path)
    save_book(record)
    save_graph(build_temporal_graph(record))
    return UploadResponse(
        book_id=record.book_id,
        title=record.title,
        chapter_count=record.chapter_count,
        chunk_count=len(record.chunks),
    )


@app.post("/api/qa")
def ask_question(request: QuestionRequest):
    try:
        book = load_book(request.book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    return build_answer(request, book.chunks)


@app.post("/api/orchestrate")
def orchestrate(payload: dict):
    book_id = payload["book_id"]
    book = load_book(book_id)
    graph = load_graph(book_id)
    service = OrchestrationService()
    result = service.orchestrate(
        chunks=book.chunks,
        request_id=payload.get("request_id", f"orchestrate-{book_id}"),
        book_id=book_id,
        query=payload.get("query", ""),
        reading_progress=payload["reading_progress"],
        selection_context=payload.get("selection_context"),
        top_k=payload.get("top_k", 6),
        temporal_graph=graph,
    )
    return result.model_dump()


@app.post("/api/summary")
def chapter_summary(request: SummaryRequest):
    try:
        book = load_book(request.book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    return summarize_chapter(book, request.current_chapter, request.persona_id)
