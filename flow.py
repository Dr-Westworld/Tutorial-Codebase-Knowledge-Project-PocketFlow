# from pocketflow import Flow
# # Import all node classes from nodes.py
# from nodes import (
#     FetchRepo,
#     IdentifyAbstractions,
#     AnalyzeRelationships,
#     OrderChapters,
#     WriteChapters,
#     CombineTutorial
# )

# def create_tutorial_flow():
#     """Creates and returns the codebase tutorial generation flow."""

#     # Instantiate nodes
#     fetch_repo = FetchRepo()
#     identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
#     analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)
#     order_chapters = OrderChapters(max_retries=5, wait=20)
#     write_chapters = WriteChapters(max_retries=5, wait=20) # This is a BatchNode
#     combine_tutorial = CombineTutorial()

#     # Connect nodes in sequence based on the design
#     fetch_repo >> identify_abstractions
#     identify_abstractions >> analyze_relationships
#     analyze_relationships >> order_chapters
#     order_chapters >> write_chapters
#     write_chapters >> combine_tutorial

#     # Create the flow starting with FetchRepo
#     tutorial_flow = Flow(start=fetch_repo)

#     return tutorial_flow


"""
flow.py
───────
Creates PocketFlow pipelines for the tutorial generation system.

Two pipeline variants:
  create_tutorial_flow()       — production sync pipeline (WriteChapters)
  create_async_tutorial_flow() — research/dev async pipeline (AsyncWriteChapters)

Gap 1 comparison:
  run_sync_then_async(shared)  — runs sync first, then re-runs only the
                                  WriteChapters stage async so that a direct
                                  speedup ratio is computed and pushed to
                                  Prometheus by MetricsCollector.record_async_speedup()

Factory:
  get_flow(mode)               — reads mode string ("sync" | "async")
                                  used by app.py which passes os.getenv("APP_MODE","sync")
"""

import time

from pocketflow import Flow

from nodes import (
    FetchRepo,
    IdentifyAbstractions,
    AnalyzeRelationships,
    OrderChapters,
    WriteChapters,
    CombineTutorial,
)

try:
    from nodes import AsyncWriteChapters
    _ASYNC_AVAILABLE = True
except ImportError:
    _ASYNC_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Production (sync) flow
# ──────────────────────────────────────────────────────────────────────────────

def create_tutorial_flow() -> Flow:
    """
    Standard synchronous tutorial generation pipeline.
    Used by the production container (port 5000, APP_MODE=sync or unset).

    WriteChapters is a BatchNode that processes chapters sequentially.
    It stores the total wall-time in shared['_sync_write_chapters_time']
    so that run_sync_then_async() can later compute the speedup ratio.
    """
    fetch_repo            = FetchRepo()
    identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters        = OrderChapters(max_retries=5, wait=20)
    write_chapters        = WriteChapters(max_retries=5, wait=20)
    combine_tutorial      = CombineTutorial()

    fetch_repo >> identify_abstractions
    identify_abstractions >> analyze_relationships
    analyze_relationships >> order_chapters
    order_chapters >> write_chapters
    write_chapters >> combine_tutorial

    return Flow(start=fetch_repo)


# ──────────────────────────────────────────────────────────────────────────────
# Research / development (async) flow  — Gap 1
# ──────────────────────────────────────────────────────────────────────────────

def create_async_tutorial_flow() -> Flow:
    """
    Async tutorial generation pipeline.

    Replaces WriteChapters (sequential BatchNode) with AsyncWriteChapters
    which runs all chapter LLM calls in a ThreadPoolExecutor.

    Used by the v2/development container (port 5001, APP_MODE=async).

    Gap 1 wiring:
      If shared['_sync_write_chapters_time'] is already set (because the
      sync pipeline ran first via run_sync_then_async), AsyncWriteChapters
      automatically calls MetricsCollector.record_async_speedup() and pushes
      the ratio to Prometheus at the end of its post() method.

    Raises RuntimeError if AsyncWriteChapters cannot be imported.
    """
    if not _ASYNC_AVAILABLE:
        raise RuntimeError(
            "AsyncWriteChapters not found in nodes.py. "
            "Ensure you are using the research-enhanced nodes.py."
        )

    fetch_repo            = FetchRepo()
    identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters        = OrderChapters(max_retries=5, wait=20)
    async_write_chapters  = AsyncWriteChapters(max_retries=5, wait=20)
    combine_tutorial      = CombineTutorial()

    fetch_repo >> identify_abstractions
    identify_abstractions >> analyze_relationships
    analyze_relationships >> order_chapters
    order_chapters >> async_write_chapters
    async_write_chapters >> combine_tutorial

    return Flow(start=fetch_repo)


# ──────────────────────────────────────────────────────────────────────────────
# Comparison helper — Gap 1: sync vs async speedup measurement
# ──────────────────────────────────────────────────────────────────────────────

def run_sync_then_async(shared: dict) -> dict:
    """
    Run the full SYNC pipeline first, then re-run ONLY the WriteChapters
    and CombineTutorial stages asynchronously on the same shared state.

    This is the canonical measurement method for Gap 1 of the research paper:
      1. Full sync pipeline runs → shared['_sync_write_chapters_time'] is set
         by WriteChapters.post() automatically.
      2. A sub-flow of just AsyncWriteChapters + CombineTutorial runs on the
         already-computed abstractions / chapter_order / files, so only the
         chapter-writing step is timed — not FetchRepo / LLM analysis.
      3. AsyncWriteChapters.post() reads '_sync_write_chapters_time' and calls
         MetricsCollector.record_async_speedup() pushing three Prometheus metrics:
           • sync_write_chapters_time_seconds
           • async_write_chapters_time_seconds
           • async_vs_sync_speedup_ratio

    Parameters
    ──────────
    shared : fully populated shared dict (same as passed to tutorial_flow.run())

    Returns
    ───────
    Updated shared dict with both timing keys set:
      shared['_sync_write_chapters_time']   — seconds for sync WriteChapters
      shared['_async_write_chapters_time']  — seconds for async WriteChapters

    Usage (from app_v2.py /api/process-comparison endpoint):
        shared = build_shared_from_request(data)
        shared = run_sync_then_async(shared)
    """
    if not _ASYNC_AVAILABLE:
        raise RuntimeError("AsyncWriteChapters not available in nodes.py.")

    # ── Step 1: Full synchronous pipeline ────────────────────────────────────
    # WriteChapters.post() stores wall-time in shared['_sync_write_chapters_time']
    print("[Comparison] ── Step 1: Running full SYNC pipeline …")
    sync_flow = create_tutorial_flow()
    sync_flow.run(shared)
    sync_t = shared.get("_sync_write_chapters_time", 0.0)
    print(f"[Comparison] Sync WriteChapters wall-time: {sync_t:.2f}s")

    # ── Step 2: Re-run only WriteChapters async + CombineTutorial ────────────
    # FetchRepo / IdentifyAbstractions / AnalyzeRelationships / OrderChapters
    # are NOT repeated — we reuse their outputs already in shared.
    print("[Comparison] ── Step 2: Running ASYNC WriteChapters sub-flow …")
    t0 = time.perf_counter()

    async_chapters_node = AsyncWriteChapters(max_retries=3, wait=10)
    combine_node        = CombineTutorial()
    async_chapters_node >> combine_node
    async_sub_flow = Flow(start=async_chapters_node)

    # Write async output to a separate directory to avoid clobbering sync output
    original_output_dir = shared.get("output_dir", "output")
    shared["output_dir"] = original_output_dir + "_async_comparison"
    async_sub_flow.run(shared)
    shared["output_dir"] = original_output_dir   # restore for caller

    async_t = time.perf_counter() - t0
    shared["_async_write_chapters_time"] = async_t

    speedup = (sync_t / async_t) if async_t > 0 else 0.0
    print(
        f"[Comparison] ── Results ──\n"
        f"  Sync  WriteChapters : {sync_t:.2f}s\n"
        f"  Async WriteChapters : {async_t:.2f}s\n"
        f"  Speedup             : {speedup:.2f}x\n"
        f"  Metrics pushed to Prometheus via record_async_speedup()"
    )
    return shared


# ──────────────────────────────────────────────────────────────────────────────
# Factory — used by app.py and app_v2.py
# ──────────────────────────────────────────────────────────────────────────────

def get_flow(mode: str = "sync") -> Flow:
    """
    Return the appropriate flow based on a mode string.

    Called by both app.py and app_v2.py:
        tutorial_flow = get_flow(os.getenv("APP_MODE", "sync"))

    mode: "sync"  → create_tutorial_flow()        (production default)
          "async" → create_async_tutorial_flow()  (research v2)
    """
    if mode.lower() == "async":
        return create_async_tutorial_flow()
    return create_tutorial_flow()