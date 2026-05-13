from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT_DIR / "workspace_state"
BOOKS_DIR = RUNTIME_DIR / "books"
UPLOADS_DIR = RUNTIME_DIR / "uploads"
GRAPHS_DIR = RUNTIME_DIR / "graphs"

for directory in (RUNTIME_DIR, BOOKS_DIR, UPLOADS_DIR, GRAPHS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
