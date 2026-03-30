"""
app_v2.py
─────────
Development / research Flask application for the v2 container.

Differences from app.py (production):
  1. Reads APP_MODE env var ("sync" | "async") and picks the matching flow.
     APP_MODE=async → AsyncWriteChapters (parallel threads, Gap 1 research).
  2. Adds /api/process-comparison endpoint that runs sync THEN async on the
     same repo and records the speedup ratio to Prometheus (Gap 1).
  3. Enables MemoryDivergenceTracker for WriteChapters (Gap 3) by setting
     shared["enable_divergence_tracking"] = True.
  4. Enables per-phase call-tree export (Gap 4/5) by default.
  5. Runs on port 5000 inside the container (mapped to 5001 on the host
     by docker-compose-v2.yml so both containers can run simultaneously).

Environment variables:
  APP_MODE          sync | async  (default: async for v2)
  ASYNC_MAX_WORKERS integer       (default: 4)
  GEMINI_API_KEY    required
  LOG_DIR           optional, default "logs"
"""

import os
import time
import json
import subprocess
import markdown
import re
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import shutil
import tempfile

from prometheus_client import REGISTRY
from utils.metrics import MetricsCollector
from flow import get_flow, run_sync_then_async

# ── Configuration ─────────────────────────────────────────────────────────────

APP_MODE         = os.getenv("APP_MODE", "async")          # v2 defaults to async
ASYNC_MAX_WORKERS = int(os.getenv("ASYNC_MAX_WORKERS", "4"))

APP_FOLDER   = Path(__file__).parent
OUTPUT_DIR   = APP_FOLDER / "output"
UPLOAD_DIR   = APP_FOLDER / "uploads"
TEMPLATE_DIR = APP_FOLDER / "templates"
STATIC_DIR   = APP_FOLDER / "static"

for d in (OUTPUT_DIR, UPLOAD_DIR, TEMPLATE_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True)

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["UPLOAD_FOLDER"]      = str(UPLOAD_DIR)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB

DEFAULT_INCLUDE_PATTERNS = [
    "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.java", "*.pyi", "*.pyx",
    "*.c", "*.cc", "*.cpp", "*.h", "*.md", "*.rst", "*Dockerfile",
    "*Makefile", "*.yaml", "*.yml",
]

DEFAULT_EXCLUDE_PATTERNS = [
    "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*",
    "*docs/*", "*venv/*", "*.venv/*", "*test*", "*tests/*", "*examples/*",
    "v1/*", "*dist/*", "*build/*", "*experimental/*", "*deprecated/*",
    "*misc/*", "*legacy/*", ".git/*", ".github/*", ".next/*", ".vscode/*",
    "*obj/*", "*bin/*", "*node_modules/*", "*.log",
]


# ── Mermaid helpers (identical to app.py) ─────────────────────────────────────

def extract_and_process_mermaid(markdown_content):
    mermaid_blocks      = {}
    placeholder_counter = [0]
    pattern             = r"```mermaid\s*\n(.*?)\n```"

    def extract_block(match):
        code = match.group(1).strip()
        placeholder_counter[0] += 1
        bid                    = placeholder_counter[0]
        mermaid_blocks[bid]    = code
        return f"<!-- MERMAID_BLOCK_{bid} -->"

    modified = re.sub(pattern, extract_block, markdown_content, flags=re.DOTALL)
    return modified, mermaid_blocks


def reinject_mermaid_divs(html_content, mermaid_blocks):
    for bid, code in mermaid_blocks.items():
        placeholder = f"<!-- MERMAID_BLOCK_{bid} -->"
        if placeholder in html_content:
            html_content = html_content.replace(
                placeholder, f'<div class="mermaid">\n{code}\n</div>'
            )
    return html_content


# ── Shared dict builder ────────────────────────────────────────────────────────

def _build_shared(data: dict, pipeline_start: float) -> dict:
    """Build the shared dict from a parsed JSON request body."""
    source_type = data.get("sourceType", "github")
    repo_url    = None
    local_dir   = None

    if source_type == "github":
        repo_url = data.get("source", "")
        if repo_url and not repo_url.startswith("http"):
            repo_url = f"https://{repo_url}"
    else:
        local_dir = data.get("source", "")
        if local_dir and not os.path.exists(local_dir):
            raise ValueError(f"Local path does not exist: {local_dir}")

    include_patterns = set(DEFAULT_INCLUDE_PATTERNS)
    if data.get("include"):
        include_patterns = {p.strip() for p in data["include"].split(",") if p.strip()}

    exclude_patterns = set(DEFAULT_EXCLUDE_PATTERNS)
    if data.get("exclude"):
        exclude_patterns = {p.strip() for p in data["exclude"].split(",") if p.strip()}

    return {
        "repo_url":           repo_url,
        "local_dir":          local_dir,
        "project_name":       None,
        "github_token":       None,
        "output_dir":         "output",
        "include_patterns":   include_patterns,
        "exclude_patterns":   exclude_patterns,
        "max_file_size":      int(data.get("maxSize") or 100000),
        "language":           data.get("language") or "english",
        "use_cache":          not data.get("disableCache", False),
        "max_abstraction_num": 10,
        # Research / Gap settings
        "async_max_workers":          ASYNC_MAX_WORKERS,
        "enable_divergence_tracking": True,   # Gap 3: enables MemoryDivergenceTracker
        # Pipeline timestamps
        "_pipeline_start_time":  pipeline_start,
        # Outputs
        "files":           [],
        "abstractions":    [],
        "relationships":   {},
        "chapter_order":   [],
        "chapters":        [],
        "final_output_dir": None,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    from flask import render_template_string
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Code Tutorial Generator — v2 ({{ mode }} mode)</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }
    h1   { color: #818cf8; }
    .badge { display:inline-block; background:#312e81; color:#a5b4fc;
             padding:.2rem .8rem; border-radius:9999px; font-size:.85rem; margin-left:.5rem; }
    a    { color: #a5b4fc; }
  </style>
</head>
<body>
  <h1>Code Tutorial Generator <span class="badge">v2 · {{ mode }}</span></h1>
  <p>This is the <strong>research/development</strong> container.</p>
  <ul>
    <li><a href="/api/status">/api/status</a> — check mode and worker config</li>
    <li>POST <code>/api/process</code> — generate tutorial ({{ mode }} pipeline)</li>
    <li>POST <code>/api/process-comparison</code> — run sync then async, record speedup</li>
    <li><a href="/metrics">/metrics</a> — Prometheus endpoint</li>
    <li><a href="http://localhost:3000" target="_blank">Grafana dashboards</a></li>
  </ul>
</body>
</html>""", mode=APP_MODE)


@app.route("/api/status")
def api_status():
    return jsonify({
        "version":          "v2",
        "app_mode":         APP_MODE,
        "async_available":  True,
        "async_max_workers": ASYNC_MAX_WORKERS,
        "divergence_tracking": True,
    })


@app.route("/metrics")
def metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/api/tutorials")
def get_tutorials():
    try:
        return jsonify({"tutorials": _list_tutorials()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/process", methods=["POST"])
def process_repository():
    """
    Generate a tutorial using the flow selected by APP_MODE.
    sync  → WriteChapters (sequential, production equivalent)
    async → AsyncWriteChapters (parallel threads, Gap 1 research)
    """
    try:
        data = request.json
        if not data or not data.get("source"):
            return jsonify({"error": "No source provided"}), 400

        shared        = _build_shared(data, time.perf_counter())
        tutorial_flow = get_flow(APP_MODE)
        tutorial_flow.run(shared)

        return jsonify({
            "success":    True,
            "mode":       APP_MODE,
            "message":    f"Processing completed ({APP_MODE} mode)",
            "tutorials":  _list_tutorials(),
            "output":     str(shared.get("final_output_dir")),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/process-comparison", methods=["POST"])
def process_comparison():
    """
    Gap 1 measurement endpoint.

    Runs the FULL SYNC pipeline first, then re-runs ONLY the WriteChapters
    stage asynchronously on the same shared state and records the speedup ratio
    to Prometheus.

    Returns timing data for both runs so the caller can also log/display it.
    """
    try:
        data = request.json
        if not data or not data.get("source"):
            return jsonify({"error": "No source provided"}), 400

        shared = _build_shared(data, time.perf_counter())

        # run_sync_then_async runs sync, then async sub-flow, records ratio
        shared = run_sync_then_async(shared)

        sync_t  = shared.get("_sync_write_chapters_time", 0.0)
        async_t = shared.get("_async_write_chapters_time", 0.0)
        speedup = (sync_t / async_t) if async_t > 0 else 0.0

        return jsonify({
            "success":                      True,
            "mode":                         "comparison",
            "sync_write_chapters_seconds":  round(sync_t, 3),
            "async_write_chapters_seconds": round(async_t, 3),
            "speedup_ratio":                round(speedup, 3),
            "chapters_count":               len(shared.get("chapters", [])),
            "message":                      "Speedup ratio pushed to Prometheus",
            "tutorials":                    _list_tutorials(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tutorial/<tutorial_name>/<file_path>")
def view_tutorial(tutorial_name, file_path):
    try:
        tutorial_dir = OUTPUT_DIR / tutorial_name
        if not tutorial_dir.exists():
            return f"<h1>Tutorial not found: {tutorial_name}</h1>", 404

        file_name = secure_filename(file_path)
        md_file   = tutorial_dir / f"{file_name}.md"
        if not md_file.exists():
            md_file = tutorial_dir / file_path
            if not md_file.exists():
                return f"<h1>File not found: {file_path}</h1>", 404

        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()

        modified_content, mermaid_blocks = extract_and_process_mermaid(content)
        html_content = markdown.markdown(modified_content, extensions=["extra", "codehilite", "toc"])
        html_content = reinject_mermaid_divs(html_content, mermaid_blocks)

        return render_template(
            "viewer.html",
            content=html_content,
            title=md_file.stem.replace("_", " ").title(),
            tutorial_name=tutorial_name,
        )
    except Exception as e:
        return f"<h1>Error loading tutorial</h1><p>{e}</p>", 500


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_tutorials():
    tutorials = []
    if not OUTPUT_DIR.exists():
        return tutorials
    for project_dir in OUTPUT_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        md_files = []
        for md_file in project_dir.rglob("*.md"):
            rel = md_file.relative_to(project_dir)
            md_files.append({
                "name":         md_file.stem,
                "path":         str(rel).replace("\\", "/"),
                "display_name": md_file.stem.replace("_", " ").title(),
            })
        if md_files:
            tutorials.append({
                "name":         project_dir.name,
                "display_name": project_dir.name.replace("_", " ").replace("-", " ").title(),
                "files":        sorted(md_files, key=lambda x: x["name"]),
                "file_count":   len(md_files),
            })
    return sorted(tutorials, key=lambda x: x["name"])


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"╔══════════════════════════════════════════════╗")
    print(f"║   Code Tutorial Generator — v2 Research      ║")
    print(f"║   APP_MODE          : {APP_MODE:<22} ║")
    print(f"║   ASYNC_MAX_WORKERS : {ASYNC_MAX_WORKERS:<22} ║")
    print(f"║   Divergence track  : enabled                ║")
    print(f"║   Call-tree export  : enabled                ║")
    print(f"╚══════════════════════════════════════════════╝")
    app.run(debug=False, host="0.0.0.0", port=5000)
