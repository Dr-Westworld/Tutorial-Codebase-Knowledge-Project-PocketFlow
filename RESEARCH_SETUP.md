# PocketFlow Research Mode — Setup Guide

## Why the research code didn't work

Five concrete bugs, all fixable:

### 1. `call_tree.py` import path mismatch
The research `nodes.py` imports:
```python
from utils.call_tree import record_call
```
But `call_tree.py` lives at the **project root**, not inside `utils/`.
Result: `ModuleNotFoundError` on every import of `nodes.py`.

**Fix**: `Dockerfile.research` copies `call_tree.py` into `utils/` during build:
```dockerfile
COPY call_tree.py ./utils/call_tree.py
```
Also keep the original at root so `import call_tree` still works if anything uses it directly.

---

### 2. `flow.py` never imports `AsyncWriteChapters`
```python
# flow.py (unchanged) — always uses sync WriteChapters
from nodes import FetchRepo, ..., WriteChapters, CombineTutorial
```
`AsyncWriteChapters` is **defined** in the research `nodes.py` but **never wired into any flow**.

**Fix**: `research_flow.py` adds:
```python
from nodes import ..., AsyncWriteChapters, ...

def create_async_tutorial_flow():
    ...
    order_chapters >> async_write_chapters >> combine_tutorial
    return Flow(start=fetch_repo)
```

---

### 3. `docker-compose-v2.yml` never runs `research_app.py`
The old v2 compose set `APP_MODE: async` as an env var but the Dockerfile
`CMD` was `["python", "app.py"]` — nothing reads `APP_MODE`, so it ran the
**production app** on port 5001, doing nothing different.

**Fix**: `docker-compose-v2.yml` now has an explicit `command:` override:
```yaml
command: ["python", "research_app.py"]
```
And uses `Dockerfile.research` which has the correct `CMD`.

---

### 4. No `research_app.py` existed
The production `app.py` has no `/api/research/*` endpoints, runs only the
sync flow, and never calls `AsyncWriteChapters` or `flat_baseline.py`.

**Fix**: New `research_app.py` on port 5001 that:
- Runs the sync flow first → captures `_sync_write_chapters_time`
- Re-runs the async flow on the same repo (LLM cache makes upstream nodes instant)
- Captures `_async_write_elapsed` and computes speedup ratio
- Optionally runs `flat_baseline.py` for framework overhead
- Persists results as JSON in `research_results/`
- Serves a comparison dashboard UI

---

### 5. `AsyncWriteChapters.post()` doesn't write elapsed time into `shared`
`research_app.py` reads `shared_async.get("_async_write_elapsed")` to get
the async chapter-writing time, but the research `nodes.py` never sets that key.

**Fix**: Add ONE line inside `AsyncWriteChapters.post()`, right after:
```python
async_elapsed = time.perf_counter() - async_wall_start
```
add:
```python
shared["_async_write_elapsed"] = async_elapsed   # ← ADD THIS LINE
```

---

## Files to add / replace

| File | Action | Why |
|------|---------|-----|
| `utils/call_tree.py` | **ADD** (copy from root) | Fix import path |
| `research_flow.py` | **ADD** | Wire AsyncWriteChapters into a flow |
| `research_app.py` | **ADD** | Research entry point on port 5001 |
| `templates/research_index.html` | **ADD** | Research UI |
| `docker-compose-v2.yml` | **REPLACE** | Point to research_app.py and Dockerfile.research |
| `Dockerfile.research` | **ADD** | Build image that copies call_tree into utils/ |
| `nodes.py` | **PATCH** | Add `shared["_async_write_elapsed"] = async_elapsed` in AsyncWriteChapters.post() |

---

## Exact patch for `nodes.py`

Find this block in `AsyncWriteChapters.post()` (around line 380 in the research version):

```python
async_elapsed = time.perf_counter() - async_wall_start

# Reconstruct ordered list
chapters = [results.get(r["chapter_num"], "") for r in exec_res_list]
```

Change it to:

```python
async_elapsed = time.perf_counter() - async_wall_start
shared["_async_write_elapsed"] = async_elapsed      # ← ADD THIS LINE

# Reconstruct ordered list
chapters = [results.get(r["chapter_num"], "") for r in exec_res_list]
```

---

## Which `nodes.py` / `metrics.py` / `performance_tracker.py` to use

You have two versions of each — production (shorter) and research (longer, with
`AsyncWriteChapters`, `MemoryDivergenceTracker`, etc.).

The research app **requires** the research versions because it imports
`AsyncWriteChapters` from `nodes.py`.

Make sure your project uses the **research versions** (the longer ones that include
`AsyncWriteChapters`, `framework_overhead_seconds`, `MemoryDivergenceTracker`, etc.)
before building the research Docker image.

---

## How to run

```bash
# 1. Start the production stack (creates tutorial-network)
docker-compose up -d

# 2. Start the research stack  
docker-compose -f docker-compose-v2.yml up -d

# 3. Open production app (sync only)
open http://localhost:5000

# 4. Open research app (sync + async comparison)
open http://localhost:5001
```

The research UI at port 5001 has a "Run Comparison" button that:
1. Runs the full pipeline with sync `WriteChapters`
2. Immediately re-runs with `AsyncWriteChapters` (cache makes upstream instant)
3. Shows sync time, async time, and speedup ratio
4. Optionally runs the flat baseline for framework overhead %

Results are persisted in `research_results/` and visible in "Run History".

---

## Prometheus data flow

Both apps (5000 and 5001) expose `/metrics` to Prometheus.
Add a second scrape target in `monitoring/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'pocketflow-app'
    static_configs:
      - targets: ['pocketflow-app:5000']

  - job_name: 'pocketflow-research'     # ← ADD THIS
    static_configs:
      - targets: ['pocketflow-research:5001']
    scrape_interval: 10s
```

After this, the Grafana dashboard `07-research-gaps.json` will show:
- `async_vs_sync_speedup_ratio` (Gap 1)
- `framework_overhead_seconds` (Gap 2)  
- `memory_divergence_peak_bytes` (Gap 3)
- `call_tree_function_time_seconds` (Gaps 4 & 5)
