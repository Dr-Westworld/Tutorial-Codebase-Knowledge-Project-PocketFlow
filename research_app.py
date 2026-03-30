"""
research_app.py
───────────────
Flask application for the research paper comparison experiment.

Port : 5001  (production app.py stays on 5000)

What this app does that app.py does NOT
────────────────────────────────────────
1.  Runs the FULL pipeline with sync WriteChapters  →  records timing
2.  Immediately re-runs the SAME repo with AsyncWriteChapters
    (LLM cache makes upstream nodes instant, so timing difference is
    WriteChapters sync vs async only)
3.  Optionally runs the flat baseline (no Node/Flow wrappers) for the
    framework-overhead calculation
4.  Exposes /api/research/results with the comparison JSON
5.  Exposes /api/research/process to trigger a comparison run

Everything else (tutorial viewer, Prometheus /metrics endpoint) is
inherited from the same Flask setup.
"""

import copy
import json
import os
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
import markdown
import re

from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST
from utils.metrics import MetricsCollector
from research_flow import create_tutorial_flow, create_async_tutorial_flow

# ─────────────────────────────────────────────────────────────────────────────
# Configuration  (same as app.py so output dirs are shared)
# ─────────────────────────────────────────────────────────────────────────────

APP_FOLDER   = Path(__file__).parent
OUTPUT_DIR   = APP_FOLDER / "output"
UPLOAD_DIR   = APP_FOLDER / "uploads"
TEMPLATE_DIR = APP_FOLDER / "templates"
STATIC_DIR   = APP_FOLDER / "static"

for d in (OUTPUT_DIR, UPLOAD_DIR, TEMPLATE_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True)

# Where we persist comparison results between requests
RESULTS_DIR = APP_FOLDER / "research_results"
RESULTS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["UPLOAD_FOLDER"]      = str(UPLOAD_DIR)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

DEFAULT_INCLUDE_PATTERNS = [
    "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.java",
    "*.c", "*.cpp", "*.h", "*.md", "*.rst", "*Dockerfile", "*Makefile",
    "*.yaml", "*.yml",
]

DEFAULT_EXCLUDE_PATTERNS = [
    "assets/*", "data/*", "images/*", "public/*", "static/*",
    "*docs/*", "*venv/*", "*.venv/*", "*test*", "*tests/*",
    "*examples/*", "v1/*", "*dist/*", "*build/*", ".git/*",
    ".github/*", ".next/*", "*node_modules/*", "*.log",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_shared(data: dict) -> dict:
    source_type = data.get("sourceType", "github")
    repo_url    = None
    local_dir   = None

    if source_type == "github":
        repo_url = data.get("source", "")
        if not repo_url.startswith("http"):
            repo_url = f"https://{repo_url}"
    else:
        local_dir = data.get("source", "")

    include = set(DEFAULT_INCLUDE_PATTERNS)
    if data.get("include"):
        include = {p.strip() for p in data["include"].split(",") if p.strip()}

    exclude = set(DEFAULT_EXCLUDE_PATTERNS)
    if data.get("exclude"):
        exclude = {p.strip() for p in data["exclude"].split(",") if p.strip()}

    return {
        "repo_url":           repo_url,
        "local_dir":          local_dir,
        "project_name":       None,
        "github_token":       None,
        "output_dir":         "output",
        "include_patterns":   include,
        "exclude_patterns":   exclude,
        "max_file_size":      int(data.get("maxSize") or 100_000),
        "language":           data.get("language") or "english",
        "use_cache":          not data.get("disableCache", False),
        "max_abstraction_num": 10,
        # pipeline outputs
        "files": [], "abstractions": [], "relationships": {},
        "chapter_order": [], "chapters": [], "final_output_dir": None,
    }


def _run_flat_baseline(shared: dict, pocketflow_time: float,
                        pocketflow_step_times: dict) -> dict:
    """Runs flat_baseline.py comparison and returns the overhead report."""
    try:
        from flat_baseline import measure_framework_overhead
        report = measure_framework_overhead(
            shared_template=shared,
            pocketflow_time=pocketflow_time,
            pocketflow_step_times=pocketflow_step_times,
        )
        return report
    except Exception as exc:
        print(f"[research_app] flat_baseline error: {exc}")
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "research_index.html",
        default_include=DEFAULT_INCLUDE_PATTERNS,
        default_exclude=DEFAULT_EXCLUDE_PATTERNS,
    )


@app.route("/metrics")
def metrics():
    return generate_latest(REGISTRY), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/api/research/process", methods=["POST"])
def research_process():
    """
    Main research endpoint.

    Steps:
    1. Run full pipeline with sync WriteChapters.
    2. Re-run same repo with AsyncWriteChapters (LLM cache makes upstream fast).
    3. Optionally run flat baseline for framework-overhead measurement.
    4. Return comparison JSON.
    """
    data = request.json or {}

    if not data.get("source"):
        return jsonify({"error": "No source provided"}), 400

    run_flat  = data.get("runFlatBaseline", False)
    max_workers = int(data.get("asyncMaxWorkers", 4))

    # ── 1. Sync flow ──────────────────────────────────────────────────────────
    shared_sync = _build_shared(data)
    shared_sync["_pipeline_start_time"] = time.perf_counter()

    print("\n" + "═"*60)
    print("  RESEARCH: running SYNC pipeline")
    print("═"*60)

    sync_wall_start = time.perf_counter()
    try:
        sync_flow = create_tutorial_flow()
        sync_flow.run(shared_sync)
    except Exception as exc:
        return jsonify({"error": f"Sync pipeline failed: {exc}"}), 500

    sync_total_time = time.perf_counter() - sync_wall_start
    sync_chapter_time = shared_sync.get("_sync_write_chapters_time", 0.0)
    repo_name         = shared_sync.get("project_name", "unknown")

    print(f"\n[research_app] SYNC done in {sync_total_time:.2f}s  "
          f"(WriteChapters={sync_chapter_time:.2f}s)")

    # ── 2. Async flow ─────────────────────────────────────────────────────────
    # Deep-copy shared so upstream results survive; enable LLM cache so only
    # WriteChapters bears the true cost.
    shared_async = copy.deepcopy(shared_sync)
    shared_async["use_cache"]        = True      # always cache for fair comparison
    shared_async["async_max_workers"] = max_workers
    shared_async["output_dir"]       = "output"  # writes to same output dir
    shared_async["_pipeline_start_time"] = time.perf_counter()

    print("\n" + "═"*60)
    print(f"  RESEARCH: running ASYNC pipeline (max_workers={max_workers})")
    print("═"*60)

    async_wall_start = time.perf_counter()
    try:
        async_flow = create_async_tutorial_flow()
        async_flow.run(shared_async)
    except Exception as exc:
        print(f"[research_app] Async pipeline error: {exc}")
        async_total_time = 0.0
        async_chapter_time = 0.0
    else:
        async_total_time   = time.perf_counter() - async_wall_start
        # AsyncWriteChapters.post() records _async_write_elapsed in shared
        async_chapter_time = shared_async.get("_async_write_elapsed", 0.0)
        print(f"\n[research_app] ASYNC done in {async_total_time:.2f}s  "
              f"(WriteChapters={async_chapter_time:.2f}s)")

    # ── 3. Speedup ratio ──────────────────────────────────────────────────────
    chapter_count = len(shared_sync.get("chapter_order", []))
    speedup       = (sync_chapter_time / async_chapter_time
                     if async_chapter_time > 0 else None)

    if speedup is not None:
        print(f"\n[research_app] Speedup: {speedup:.2f}x  "
              f"(sync={sync_chapter_time:.1f}s  async={async_chapter_time:.1f}s)")
        

    # ── Wait for quota reset before flat baseline ──
    print("\n[research_app] Waiting 120s for API quota reset before flat baseline...")
    time.sleep(120)

    # ── 4. Flat baseline (optional) ───────────────────────────────────────────
    flat_report: dict = {}
    if run_flat:
        print("\n" + "═"*60)
        print("  RESEARCH: running flat baseline")
        print("═"*60)
        flat_report = _run_flat_baseline(
            shared=shared_sync,
            pocketflow_time=sync_total_time,
            pocketflow_step_times={},   # node-level times not separately tracked here
        )

    # ── 5. Persist & return ───────────────────────────────────────────────────
    result = {
        "repo_name":          repo_name,
        "chapter_count":      chapter_count,
        "async_max_workers":  max_workers,
        "sync": {
            "total_pipeline_sec":    round(sync_total_time,   3),
            "write_chapters_sec":    round(sync_chapter_time, 3),
            "output_dir":            shared_sync.get("final_output_dir"),
        },
        "async": {
            "total_pipeline_sec":    round(async_total_time,   3),
            "write_chapters_sec":    round(async_chapter_time, 3),
            "output_dir":            shared_async.get("final_output_dir"),
        },
        "speedup_ratio":          round(speedup, 3) if speedup else None,
        "speedup_pct_faster":     round((speedup - 1) * 100, 1) if speedup else None,
        "flat_baseline":          flat_report,
        "timestamp":              time.time(),
    }

    # Save to disk so /api/research/results can serve history
    result_file = RESULTS_DIR / f"{repo_name}_{int(time.time())}.json"
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    return jsonify({"success": True, "comparison": result})


@app.route("/api/research/results")
def research_results():
    """Return list of all past comparison runs."""
    results = []
    for p in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            with open(p) as f:
                results.append(json.load(f))
        except Exception:
            pass
    return jsonify({"results": results[:50]})   # last 50


@app.route("/api/tutorials")
def get_tutorials():
    try:
        return jsonify({"tutorials": _list_tutorials()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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


def _extract_mermaid(content: str):
    blocks: dict = {}
    counter = [0]
    pattern = r"```mermaid\s*\n(.*?)\n```"

    def _replace(m):
        code = m.group(1).strip()
        counter[0] += 1
        bid = counter[0]
        blocks[bid] = code
        return f"<!-- MERMAID_BLOCK_{bid} -->"

    modified = re.sub(pattern, _replace, content, flags=re.DOTALL)
    return modified, blocks


def _reinject_mermaid(html: str, blocks: dict) -> str:
    for bid, code in blocks.items():
        ph = f"<!-- MERMAID_BLOCK_{bid} -->"
        if ph in html:
            html = html.replace(ph, f'<div class="mermaid">\n{code}\n</div>')
    return html


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
            if not md_file.exists() or not md_file.name.endswith(".md"):
                return f"<h1>File not found: {file_path}</h1>", 404
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()
        modified, blocks = _extract_mermaid(content)
        html = markdown.markdown(modified, extensions=["extra", "codehilite", "toc"])
        html = _reinject_mermaid(html, blocks)
        return render_template("viewer.html", content=html,
                               title=md_file.stem.replace("_", " ").title(),
                               tutorial_name=tutorial_name)
    except Exception as exc:
        return f"<h1>Error loading tutorial</h1><p>{exc}</p>", 500


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Research app starting on http://0.0.0.0:5001")
    print("  Production app is on port 5000")
    print("  POST /api/research/process  — run sync+async+baseline comparison")
    print("  GET  /api/research/results  — list past comparisons")
    app.run(debug=False, host="0.0.0.0", port=5001)
