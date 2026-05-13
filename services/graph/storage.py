from __future__ import annotations

import json

from backend.config import GRAPHS_DIR
from services.graph.models import TemporalContextGraph


def graph_path(book_id: str):
    return GRAPHS_DIR / f"{book_id}.graph.json"


def save_graph(graph: TemporalContextGraph) -> None:
    graph_path(graph.book_id).write_text(
        json.dumps(graph.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_graph(book_id: str) -> TemporalContextGraph:
    payload = json.loads(graph_path(book_id).read_text(encoding="utf-8"))
    return TemporalContextGraph.model_validate(payload)
