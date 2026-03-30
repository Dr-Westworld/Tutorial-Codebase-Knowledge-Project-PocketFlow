# Two-Container Deployment Guide + Research Gap Status

## Architecture Overview

```
Host machine
├── Port 5000 → production container (v1)   APP_MODE=sync
├── Port 5001 → research container (v2)     APP_MODE=async
├── Port 9090 → Prometheus   (shared, started by v1 compose)
└── Port 3000 → Grafana      (shared, started by v1 compose)
```

Both containers share the same Docker network (`tutorial-network`) so v2 metrics
flow into the same Prometheus instance and appear in the same Grafana dashboards.

---

## Quick Start

```bash
# 1. Start production stack (v1 + Prometheus + Grafana)
docker-compose up -d

# 2. Start research container (v2, async mode)
docker-compose -f docker-compose-v2.yml up -d

# 3. Verify both are running
curl http://localhost:5000/metrics   # v1 sync metrics
curl http://localhost:5001/api/status  # {"app_mode": "async", ...}

# 4. Open Grafana
open http://localhost:3000
# Login: admin / admin
# Dashboard: "PocketFlow — Research Gaps (Paper Evidence)"
```

---

## Research Gap Status

### Gap 1 — Async vs Sync WriteChapters Speedup ✅

**What's implemented:**
- `AsyncWriteChapters` class in `nodes.py` — runs chapter LLM calls in parallel
  via `ThreadPoolExecutor` (configurable via `ASYNC_MAX_WORKERS` env var)
- `WriteChapters.post()` stores `shared["_sync_write_chapters_time"]`
- `AsyncWriteChapters.post()` reads it and calls `MetricsCollector.record_async_speedup()`
- Three Prometheus metrics produced: `async_vs_sync_speedup_ratio`,
  `sync_write_chapters_time_seconds`, `async_write_chapters_time_seconds`
- `create_async_tutorial_flow()` in `flow.py` for the v2 container
- `run_sync_then_async(shared)` in `flow.py` for the comparison measurement

**How to trigger the comparison measurement:**
```bash
curl -X POST http://localhost:5001/api/process-comparison \
     -H "Content-Type: application/json" \
     -d '{"sourceType":"github","source":"github.com/owner/repo"}'
# Returns: {"speedup_ratio": 3.2, "sync_...": 45.1, "async_...": 14.1, ...}
```

**Grafana:** Dashboard 07 → "GAP 1 — Async vs Sync WriteChapters Speedup"

---

### Gap 2 — PocketFlow Framework Overhead ✅

**What's implemented:**
- `flat_baseline.py` — all 6 pipeline stages as plain functions (no Node/Flow)
- `run_flat_baseline(shared)` — times each stage, publishes to Prometheus
- `measure_framework_overhead(shared, pf_time, pf_step_times)` — computes delta
- `framework_overhead_seconds` Histogram in `metrics.py`
- `profiling_reports/overhead_<timestamp>.json` written per run

**How to trigger:**
```python
from utils.flat_baseline import measure_framework_overhead
report = measure_framework_overhead(
    shared_template=shared,
    pocketflow_time=180.0,
    pocketflow_step_times={"FetchRepo": 3.2, "WriteChapters": 120.0, ...}
)
print(report["total_overhead_pct"])  # e.g. 2.3%
```

**Grafana:** Dashboard 07 → "GAP 2 — PocketFlow Framework Overhead"

---

### Gap 3 — tracemalloc vs psutil Divergence ✅

**What's implemented:**
- `MemoryDivergenceTracker` in `performance_tracker.py` — samples both probes
  at 100 ms intervals, writes JSONL to `profiling_reports/mem_divergence.jsonl`
- `track_execution(..., use_divergence=True)` — activates the tracker for any block
- `WriteChapters.exec()` and `AsyncWriteChapters._call_one()` both pass
  `use_divergence=enable_divergence` where the flag comes from
  `shared["enable_divergence_tracking"]`
- `app.py` sets `enable_divergence_tracking = (APP_MODE != "sync")` so it's
  **automatically enabled for the v2 container** and disabled for v1
- `memory_divergence_peak_bytes` Gauge in `metrics.py`

**Output file:** `profiling_reports/mem_divergence.jsonl`
Each line: `{"ts":..., "psutil_rss_bytes":..., "tm_current_bytes":..., "divergence_bytes":..., "divergence_pct":...}`

**Grafana:** Dashboard 07 → "GAP 3 — tracemalloc vs psutil Memory Divergence"

---

### Gap 4/5 — Call-Tree / Per-Phase Granularity ✅

**What's implemented:**
- `call_tree.py` — thread-local call-tree recorder with `record_call()` context manager
- Every `prep()` and `post()` in `nodes.py` is wrapped in `record_call()`
- Each `exec()` is wrapped in `track_execution()` which also pushes to `CallTreeRecorder`
- `CombineTutorial.post()` exports two JSON files at pipeline end:
  - `profiling_reports/call_trees_<repo>.json` — full nested tree
  - `profiling_reports/flamegraph_<repo>.json` — speedscope-compatible flat frames
- `CallTreeRecorder.print_summary(top_n=20)` printed to console after each run
- `call_tree_function_time_seconds` Histogram + `call_tree_function_memory_bytes` Gauge

**Grafana:** Dashboard 07 → "GAP 4 & 5 — Call-Tree Per-Phase & Per-Function Granularity"

---

## File Changes Summary

| File | Change | Why |
|------|--------|-----|
| `flow.py` | Added `create_async_tutorial_flow()`, `run_sync_then_async()`, `get_flow(mode)` | Gap 1: async pipeline + comparison |
| `app.py` | Reads `APP_MODE` env var, calls `get_flow(APP_MODE)` instead of hardcoding sync | Both containers use same app.py |
| `app_v2.py` | New file — research entrypoint with `/api/process-comparison` endpoint | Gap 1: comparison measurement API |
| `nodes.py` | `WriteChapters.exec()` passes `use_divergence` to `track_execution` | Gap 3: divergence tracking |
| `nodes.py` | `AsyncWriteChapters._call_one()` same Gap 3 change | Gap 3 for async path |
| `nodes.py` | Both prep() methods pass `enable_divergence_tracking` into item dict | Gap 3: flag propagation |
| `docker-compose-v2.yml` | Fixed network, added `command: python app_v2.py`, removed Prometheus/Grafana | Two-container plan |

---

## Environment Variables

| Variable | v1 (production) | v2 (research) |
|----------|----------------|---------------|
| `APP_MODE` | `sync` (default) | `async` |
| `ASYNC_MAX_WORKERS` | N/A | `4` (configurable) |
| Divergence tracking | disabled | enabled automatically |
| Call-tree export | enabled | enabled |
| Port | 5000 | 5001 |

---

## Profiling Output Files

After running at least one tutorial generation in v2:

```
profiling_reports/
├── mem_divergence.jsonl          # Gap 3: 100ms psutil vs tracemalloc samples
├── call_trees_<repo>.json        # Gap 4/5: full call tree per repo
├── flamegraph_<repo>.json        # Gap 4/5: speedscope-compatible flame graph
└── overhead_<timestamp>.json     # Gap 2: framework overhead report
```

Open `flamegraph_<repo>.json` at https://www.speedscope.app for an interactive
flame graph of the entire pipeline execution.
