from __future__ import annotations

from pathlib import Path
from threading import Thread

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.upload_jobs import upload_job_registry
from backend.assets.data.data_processing_scripts.ingest.parser import (
    SUPPORTED_UPLOAD_SUFFIXES,
    UploadTextExtractionError,
    UnsupportedUploadFormatError,
    build_book_record,
    build_book_record_from_upload,
    read_uploaded_text,
    slugify,
)
from backend.assets.data.data_processing_scripts.storage import list_books, load_book, save_book
from backend.common.config import EXAMPLES_DIR, ROOT_DIR, UPLOADS_DIR
from backend.common.models import (
    CharacterChatRequest,
    CharacterProfileRequest,
    InlineBubbleRequest,
    PersonaPromptPreviewRequest,
    PersonaRAGQueryRequest,
    QuestionRequest,
    SummaryRequest,
    UploadResponse,
)
from backend.knowledge_base.character.service import (
    answer_as_character,
    generate_character_profile,
    generate_inline_bubbles,
    list_character_candidates,
)
from backend.knowledge_base.graph.builder import TemporalGraphBuilder, build_temporal_graph
from backend.knowledge_base.graph.models import GraphQuery
from backend.knowledge_base.graph.retrieval import TemporalGraphRetriever
from backend.knowledge_base.graph.storage import load_graph, load_graph_metadata, save_graph
from backend.knowledge_base.qa.answering import build_answer
from backend.llm_memory.orchestration.service import OrchestrationService
from backend.llm_memory.persona.persona_service import (
    PersonaAgentConfigurationError,
    PersonaAgentInvocationError,
    build_persona_prompt_preview,
    get_persona_agent,
    get_persona_kb_manifest,
    list_persona_agents,
    list_personas,
    retrieve_persona_snippets,
)
from backend.llm_memory.summary.chapter_summary import summarize_chapter


app = FastAPI(title="Muse Reading MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = ROOT_DIR / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


def _upload_stage_percent(stage: str) -> int:
    mapping = {
        "queued": 0,
        "extract-source-text": 5,
        "segment-chapters": 12,
        "construct-episodes": 22,
        "graph-episode-start": 30,
        "llm-skipped": 40,
        "llm-request-dispatched": 46,
        "llm-response-received": 56,
        "llm-request-failed": 56,
        "graph-episode-complete": 66,
        "chapter-consolidation": 76,
        "graph-community-build": 84,
        "graph-saga-build": 88,
        "graph-timeline-build": 92,
        "graph-build-finished": 95,
        "persist-book-record": 97,
        "persist-graph-snapshot": 99,
        "finalize-upload": 99,
        "completed": 100,
        "failed": 100,
    }
    return mapping.get(stage, 0)


def _update_upload_job(job_id: str, **fields):
    stage = fields.get("stage")
    if stage and "percent" not in fields:
        fields["percent"] = _upload_stage_percent(stage)
    upload_job_registry.update(job_id, **fields)


def _process_upload_job(job_id: str, *, original_name: str, suffix: str, raw_bytes: bytes) -> None:
    _update_upload_job(
        job_id,
        status="running",
        stage="extract-source-text",
        title="Extracting source text",
        message=f"Reading uploaded file {original_name} and extracting source text.",
    )
    try:
        text = read_uploaded_text(original_name, raw_bytes)
        title = Path(original_name).stem
        safe_name = slugify(title)
        upload_path = UPLOADS_DIR / f"{safe_name}{suffix}"
        if suffix in SUPPORTED_UPLOAD_SUFFIXES - {".txt"}:
            upload_path.write_bytes(raw_bytes)
        else:
            upload_path.write_text(text, encoding="utf-8")

        _update_upload_job(
            job_id,
            stage="segment-chapters",
            title="Segmenting chapters and paragraphs",
            message="Segmenting the uploaded text into chapter and paragraph episodes.",
            book_title=title,
        )

        def parser_progress(payload: dict) -> None:
            _update_upload_job(job_id, **payload)

        record = build_book_record_from_upload(
            title=title,
            filename=original_name,
            raw_bytes=raw_bytes if suffix != ".txt" else text.encode("utf-8"),
            source_path=upload_path,
            progress_callback=parser_progress,
        )
        _update_upload_job(
            job_id,
            book_id=record.book_id,
            book_title=record.title,
            chunk_count=len(record.chunks),
            chapter_count=record.chapter_count,
            total_snippets=len(record.chunks),
        )

        def graph_progress(payload: dict) -> None:
            _update_upload_job(job_id, **payload)

        graph = TemporalGraphBuilder(progress_callback=graph_progress, strict_llm_extraction=True).build(record)

        _update_upload_job(
            job_id,
            stage="persist-book-record",
            title="Persisting book record",
            message="Persisting the parsed book record.",
            processed_snippets=len(record.chunks),
            total_snippets=len(record.chunks),
        )
        save_book(record)

        _update_upload_job(
            job_id,
            stage="persist-graph-snapshot",
            title="Persisting graph snapshot",
            message="Persisting the temporal graph snapshot, including relations, communities, and sagas.",
            processed_snippets=len(record.chunks),
            total_snippets=len(record.chunks),
            details={
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
                "community_count": len(graph.communities),
                "saga_count": len(graph.sagas),
            },
        )
        save_graph(graph)

        _update_upload_job(
            job_id,
            status="completed",
            stage="completed",
            title="Temporal graph ready",
            message=f"Temporal graph ready for {record.title}.",
            processed_snippets=len(record.chunks),
            total_snippets=len(record.chunks),
            book_id=record.book_id,
            book_title=record.title,
            chunk_count=len(record.chunks),
            chapter_count=record.chapter_count,
        )
    except UnsupportedUploadFormatError as exc:
        _update_upload_job(
            job_id,
            status="failed",
            stage="failed",
            title="Upload failed",
            message=str(exc),
            error=str(exc),
        )
    except UploadTextExtractionError as exc:
        _update_upload_job(
            job_id,
            status="failed",
            stage="failed",
            title="Text extraction failed",
            message=str(exc),
            error=str(exc),
        )
    except Exception as exc:
        _update_upload_job(
            job_id,
            status="failed",
            stage="failed",
            title="Temporal graph build failed",
            message=f"Temporal graph build failed: {exc}",
            error=str(exc),
        )


def ensure_demo_book_loaded() -> None:
    demo_path = EXAMPLES_DIR / "muse_demo_book.txt"
    if not demo_path.exists():
        return
    title = demo_path.stem
    record = build_book_record(title=title, raw_text=demo_path.read_text(encoding="utf-8"), source_path=demo_path)
    save_book(record)
    save_graph(build_temporal_graph(record))


def get_or_build_book(book_id: str):
    try:
        record = load_book(book_id)
    except FileNotFoundError:
        demo_path = EXAMPLES_DIR / f"{book_id}.txt"
        if not demo_path.exists():
            raise
        record = build_book_record(
            title=demo_path.stem,
            raw_text=demo_path.read_text(encoding="utf-8"),
            source_path=demo_path,
        )
        save_book(record)
    if record.chunks:
        return record
    source_path = Path(record.source_path)
    if not source_path.exists():
        return record
    rebuilt = build_book_record_from_upload(
        title=record.title,
        filename=source_path.name,
        raw_bytes=source_path.read_bytes(),
        source_path=source_path,
    )
    if rebuilt.chunks:
        save_book(rebuilt)
        save_graph(build_temporal_graph(rebuilt))
        return rebuilt
    return record


def get_or_build_graph(book_id: str):
    try:
        return load_graph(book_id)
    except FileNotFoundError:
        book = get_or_build_book(book_id)
        graph = build_temporal_graph(book)
        save_graph(graph)
        return graph


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


@app.get("/api/persona-agents")
def persona_agents():
    return [agent.model_dump() for agent in list_persona_agents()]


@app.get("/api/persona-agents/{persona_id}")
def persona_agent_detail(persona_id: str):
    return get_persona_agent(persona_id).model_dump()


@app.get("/api/persona-agents/{persona_id}/kb")
def persona_agent_kb(persona_id: str):
    return get_persona_kb_manifest(persona_id)


@app.post("/api/persona-agents/{persona_id}/retrieve")
def persona_agent_retrieve(persona_id: str, request: PersonaRAGQueryRequest):
    return [hit.model_dump() for hit in retrieve_persona_snippets(persona_id, request)]


@app.post("/api/persona-agents/{persona_id}/prompt-preview")
def persona_agent_prompt_preview(persona_id: str, request: PersonaPromptPreviewRequest):
    return build_persona_prompt_preview(persona_id, request).model_dump()


@app.get("/api/books/{book_id}")
def book_detail(book_id: str):
    book = get_or_build_book(book_id)
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


@app.get("/api/books/{book_id}/characters")
def book_characters(book_id: str, current_chapter: int = 1, limit: int = 10):
    try:
        book = get_or_build_book(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return [item.model_dump() for item in list_character_candidates(book, current_chapter, limit=limit)]
    except (PersonaAgentConfigurationError, PersonaAgentInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/books/{book_id}/characters/profile")
def character_profile(book_id: str, request: CharacterProfileRequest):
    try:
        book = get_or_build_book(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return generate_character_profile(book, request.character_name, request.current_chapter).model_dump()
    except (PersonaAgentConfigurationError, PersonaAgentInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/books/{book_id}/characters/chat")
def character_chat(book_id: str, request: CharacterChatRequest):
    try:
        book = get_or_build_book(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return answer_as_character(
            book,
            character_name=request.character_name,
            question=request.question,
            current_chapter=request.current_chapter,
            conversation_history=request.conversation_history,
            top_k=request.top_k,
        ).model_dump()
    except (PersonaAgentConfigurationError, PersonaAgentInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/books/{book_id}/inline-bubbles")
def inline_bubbles(book_id: str, request: InlineBubbleRequest):
    try:
        book = get_or_build_book(book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return [
            item.model_dump()
            for item in generate_inline_bubbles(
                book,
                current_chapter=request.current_chapter,
                visible_chunk_ids=request.visible_chunk_ids,
                persona_id=request.persona_id,
                assistant_mode=request.assistant_mode,
                character_name=request.character_name,
                max_bubbles=request.max_bubbles,
            )
        ]
    except (PersonaAgentConfigurationError, PersonaAgentInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/books/{book_id}/graph")
def graph_detail(book_id: str):
    graph = get_or_build_graph(book_id)
    return {
        "graph_id": graph.graph_id,
        "book_id": graph.book_id,
        "title": graph.title,
        "graph_version": graph.graph_version,
        "stats": graph.stats().model_dump(),
        "metadata": graph.metadata,
        "chapters": [chapter.model_dump() for chapter in graph.chapters.head(10)],
        "chapter_timeline": [item.model_dump() for item in graph.chapter_timeline[:10]],
        "episodes": [episode.model_dump() for episode in graph.episodes.head(10)],
        "entities": [entity.model_dump() for entity in graph.entities.head(20)],
        "relations": [relation.model_dump() for relation in graph.relations.head(20)],
        "communities": [community.model_dump() for community in graph.communities.head(10)],
        "sagas": [saga.model_dump() for saga in graph.sagas.head(10)],
    }


@app.get("/api/books/{book_id}/graph/metadata")
def graph_metadata(book_id: str):
    try:
        return load_graph_metadata(book_id)
    except FileNotFoundError:
        graph = get_or_build_graph(book_id)
        return {
            "graph_id": graph.graph_id,
            "book_id": graph.book_id,
            "title": graph.title,
            "graph_version": graph.graph_version,
            "storage": graph.metadata.get("storage", {}),
            "stats": graph.stats().model_dump(),
        }


@app.get("/api/books/{book_id}/graph/view")
def graph_view(book_id: str, chapter: int = 1, paragraph: int = 0, limit: int = 18, scope: str = "chapter"):
    graph = get_or_build_graph(book_id)
    normalized_scope = scope.lower().strip()
    if normalized_scope not in {"chapter", "book"}:
        raise HTTPException(status_code=400, detail="invalid_graph_scope")
    max_paragraph = paragraph if paragraph and paragraph > 0 else None
    chapter_key = f"chapter_{chapter:03d}"
    chapter_node = graph.chapters.get(chapter_key)
    timeline_entry = next((item for item in graph.chapter_timeline if item.chapter_index == chapter), None)
    if normalized_scope == "chapter" and chapter_node is None and timeline_entry is None:
        raise HTTPException(status_code=404, detail="chapter_not_found")

    def _entity_is_visible(entity) -> bool:
        if entity.first_seen_chapter > chapter:
            return False
        if max_paragraph is None:
            return True
        return entity.first_seen_chapter < chapter or entity.first_seen_paragraph <= max_paragraph

    if normalized_scope == "book":
        entity_pool = [entity for entity in graph.entities.values() if _entity_is_visible(entity)]
        relation_ids = [
            relation.edge_id
            for relation in graph.relations.values()
            if relation.is_visible(max_chapter=chapter, max_paragraph=max_paragraph)
        ]
        community_candidates = list(graph.communities.values())
    else:
        chapter_entity_ids = list((timeline_entry.entity_ids if timeline_entry else chapter_node.entity_ids) if (timeline_entry or chapter_node) else [])
        entity_pool = [
            graph.entities[entity_id]
            for entity_id in chapter_entity_ids
            if entity_id in graph.entities and _entity_is_visible(graph.entities[entity_id])
        ]
        relation_ids = list((timeline_entry.relation_ids if timeline_entry else chapter_node.relation_ids) if (timeline_entry or chapter_node) else [])
        community_ids = list((timeline_entry.community_ids if timeline_entry else chapter_node.community_ids) if (timeline_entry or chapter_node) else [])
        community_candidates = [graph.communities[community_id] for community_id in community_ids if community_id in graph.communities]

    entity_pool.sort(key=lambda item: item.mention_count, reverse=True)
    selected_entities = entity_pool[: max(6, limit)]
    selected_entity_ids = {entity.entity_id for entity in selected_entities}

    relation_pool = []
    for relation_id in relation_ids:
        relation = graph.relations.get(relation_id)
        if relation is None:
            continue
        if not relation.is_visible(max_chapter=chapter, max_paragraph=max_paragraph):
            continue
        relation_pool.append(relation)
        selected_entity_ids.add(relation.source_entity_id)
        selected_entity_ids.add(relation.target_entity_id)

    if len(selected_entity_ids) > limit:
        selected_entity_ids = {
            entity.entity_id
            for entity in sorted(
                [graph.entities[entity_id] for entity_id in selected_entity_ids if entity_id in graph.entities],
                key=lambda item: item.mention_count,
                reverse=True,
            )[:limit]
        }
        relation_pool = [
            relation
            for relation in relation_pool
            if relation.source_entity_id in selected_entity_ids and relation.target_entity_id in selected_entity_ids
        ]

    nodes = []
    for entity_id in selected_entity_ids:
        entity = graph.entities.get(entity_id)
        if entity is None:
            continue
        nodes.append(
            {
                "id": entity.entity_id,
                "label": entity.canonical_name,
                "type": entity.entity_type,
                "mention_count": entity.mention_count,
                "first_seen_chapter": entity.first_seen_chapter,
                "first_seen_paragraph": entity.first_seen_paragraph,
                "summary": entity.summary,
            }
        )

    edges = []
    for relation in relation_pool:
        if relation.source_entity_id not in selected_entity_ids or relation.target_entity_id not in selected_entity_ids:
            continue
        edges.append(
            {
                "id": relation.edge_id,
                "source": relation.source_entity_id,
                "target": relation.target_entity_id,
                "label": relation.relation_type,
                "fact": relation.fact,
                "state_family": relation.state_family,
                "status": relation.status,
                "weight": relation.weight,
                "valid_at_chapter": relation.valid_at_chapter,
                "valid_at_paragraph": relation.valid_at_paragraph,
            }
        )

    community_items = []
    community_candidates.sort(key=lambda item: (len(item.entity_ids), len(item.relation_ids)), reverse=True)
    for community in community_candidates[:6]:
        community_items.append(
            {
                "community_id": community.community_id,
                "label": community.label,
                "summary": community.summary,
                "entity_count": len(community.entity_ids),
                "relation_count": len(community.relation_ids),
            }
        )

    return {
        "graph_id": graph.graph_id,
        "book_id": graph.book_id,
        "title": graph.title,
        "scope": normalized_scope,
        "chapter_index": chapter if normalized_scope == "chapter" else None,
        "paragraph_limit": max_paragraph,
        "chapter_title": (timeline_entry.title if timeline_entry else chapter_node.title) if normalized_scope == "chapter" and (timeline_entry or chapter_node) else "",
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "community_count": len(community_items),
        },
        "nodes": sorted(nodes, key=lambda item: item["mention_count"], reverse=True),
        "edges": sorted(edges, key=lambda item: item["weight"], reverse=True),
        "communities": community_items,
    }


@app.post("/api/books/{book_id}/graph/query")
def graph_query(book_id: str, query: GraphQuery):
    graph = get_or_build_graph(book_id)
    effective_query = query
    if not effective_query.query and not effective_query.node_types:
        effective_query = effective_query.model_copy(update={"node_types": ["chapter", "episode"]})
    result = TemporalGraphRetriever().retrieve(graph, effective_query)
    return result.model_dump()


@app.post("/api/upload", response_model=UploadResponse)
async def upload_book(file: UploadFile = File(...)) -> UploadResponse:
    original_name = file.filename or "uploaded.txt"
    suffix = Path(original_name).suffix.lower() or ".txt"
    raw_bytes = await file.read()
    try:
        text = read_uploaded_text(original_name, raw_bytes)
    except UnsupportedUploadFormatError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except UploadTextExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    title = Path(original_name).stem
    safe_name = slugify(title)
    upload_path = UPLOADS_DIR / f"{safe_name}{suffix}"
    if suffix in SUPPORTED_UPLOAD_SUFFIXES - {".txt"}:
        upload_path.write_bytes(raw_bytes)
    else:
        upload_path.write_text(text, encoding="utf-8")

    record = build_book_record_from_upload(
        title=title,
        filename=original_name,
        raw_bytes=raw_bytes if suffix != ".txt" else text.encode("utf-8"),
        source_path=upload_path,
    )
    graph = TemporalGraphBuilder(strict_llm_extraction=True).build(record)
    save_book(record)
    save_graph(graph)
    return UploadResponse(
        book_id=record.book_id,
        title=record.title,
        chapter_count=record.chapter_count,
        chunk_count=len(record.chunks),
    )


@app.post("/api/upload-jobs")
async def create_upload_job(file: UploadFile = File(...)):
    original_name = file.filename or "uploaded.txt"
    suffix = Path(original_name).suffix.lower() or ".txt"
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported upload format '{suffix or 'unknown'}'. Supported formats: txt, pdf, epub.",
        )
    raw_bytes = await file.read()
    job = upload_job_registry.create()
    Thread(
        target=_process_upload_job,
        kwargs={"job_id": job.job_id, "original_name": original_name, "suffix": suffix, "raw_bytes": raw_bytes},
        daemon=True,
    ).start()
    return job.to_dict()


@app.get("/api/upload-jobs/{job_id}")
def upload_job_status(job_id: str):
    job = upload_job_registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="upload_job_not_found")
    return job.to_dict()


@app.post("/api/qa")
def ask_question(request: QuestionRequest):
    try:
        book = get_or_build_book(request.book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return build_answer(request, book.chunks)
    except PersonaAgentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonaAgentInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/orchestrate")
def orchestrate(payload: dict):
    book_id = payload["book_id"]
    book = load_book(book_id)
    graph = get_or_build_graph(book_id)
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
        book = get_or_build_book(request.book_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="book_not_found") from exc
    try:
        return summarize_chapter(book, request.current_chapter, request.persona_id)
    except PersonaAgentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonaAgentInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
