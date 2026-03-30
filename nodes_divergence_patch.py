"""
nodes_divergence_patch.py
─────────────────────────
Gap 3 patch: enable MemoryDivergenceTracker inside WriteChapters.exec()
and AsyncWriteChapters._call_one() so that the divergence between psutil RSS
and tracemalloc is sampled at 100 ms intervals during chapter generation
(the most memory-intensive phase of the pipeline).

HOW TO APPLY
────────────
In your research-enhanced nodes.py, find the WriteChapters.exec() method
and replace the track_execution call with the version below.

Also update AsyncWriteChapters.post()._call_one() in the same way.

These changes only activate when shared["enable_divergence_tracking"] is True,
which app.py sets automatically for the v2 container (APP_MODE != "sync").

WHY WriteChapters
──────────────────
WriteChapters is the highest-memory node because:
  1. call_llm() loads and caches large responses in llm_cache.json
  2. self.chapters_written_so_far accumulates growing strings
  3. The LLM model's C-extension buffers are not tracked by tracemalloc

The divergence between psutil RSS and tracemalloc current during this phase
is the core result of Gap 3 — it shows how much native memory is invisible
to Python's built-in heap tracer.
"""

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 1 — WriteChapters.exec()
# Replace the existing track_execution context manager with this version.
# The only addition is use_divergence and divergence_log kwargs.
# ──────────────────────────────────────────────────────────────────────────────

PATCH_WRITE_CHAPTERS_EXEC = '''
    def exec(self, item):
        chapter_num = item["chapter_num"]

        # ── Read divergence-tracking flag from item (passed from prep) ───────
        # item["enable_divergence"] is set in prep() from shared["enable_divergence_tracking"]
        enable_divergence = item.get("enable_divergence_tracking", False)

        # ... (build prompt as before, unchanged) ...

        with track_execution(
            f"exec_chapter_{chapter_num}",
            node_name="WriteChapters",
            use_divergence=enable_divergence,              # Gap 3: enable here
            divergence_log="profiling_reports/mem_divergence.jsonl",
        ):
            chapter_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))

        # ... (rest of exec unchanged) ...
'''

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 2 — WriteChapters.prep()
# Add enable_divergence_tracking to each item dict so exec() can read it.
# ──────────────────────────────────────────────────────────────────────────────

PATCH_WRITE_CHAPTERS_PREP_ITEM = '''
        # Inside the items_to_process.append({...}) block, add:
        "enable_divergence_tracking": shared.get("enable_divergence_tracking", False),
'''

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 3 — AsyncWriteChapters.post()._call_one()
# Same change: pass use_divergence flag to track_execution.
# ──────────────────────────────────────────────────────────────────────────────

PATCH_ASYNC_CALL_ONE = '''
        def _call_one(item_result: dict) -> tuple:
            cnum             = item_result["chapter_num"]
            prompt           = item_result["prompt"]
            use_cache        = item_result["use_cache"]
            enable_divergence = item_result.get("enable_divergence_tracking", False)

            with track_execution(
                f"async_exec_chapter_{cnum}",
                node_name="AsyncWriteChapters",
                use_divergence=enable_divergence,          # Gap 3: enable here
                divergence_log="profiling_reports/mem_divergence.jsonl",
            ):
                content = call_llm(prompt, use_cache=use_cache)

            print(f"[AsyncWriteChapters] Chapter {cnum} done")
            return cnum, content.strip()
'''

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 4 — AsyncWriteChapters.exec()
# Pass enable_divergence_tracking through in the returned dict.
# ──────────────────────────────────────────────────────────────────────────────

PATCH_ASYNC_EXEC_RETURN = '''
        # At the end of AsyncWriteChapters.exec(), add to the return dict:
        return {
            "chapter_num":              chapter_num,
            "prompt":                   prompt,
            "use_cache":                use_cache,
            "enable_divergence_tracking": item.get("enable_divergence_tracking", False),  # Gap 3
        }
'''

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 5 — AsyncWriteChapters.prep()
# Pass the flag into each item dict (same as WriteChapters.prep() patch).
# ──────────────────────────────────────────────────────────────────────────────

PATCH_ASYNC_PREP_ITEM = '''
        # Inside items_to_process.append({...}) in AsyncWriteChapters.prep():
        "enable_divergence_tracking": shared.get("enable_divergence_tracking", False),
'''

if __name__ == "__main__":
    print("This file documents the Gap 3 patch to apply to nodes.py.")
    print("It is not meant to be run directly.")
    print()
    print("Patches to apply:")
    print("  1. WriteChapters.exec()       — add use_divergence kwarg to track_execution")
    print("  2. WriteChapters.prep()       — add enable_divergence_tracking to item dict")
    print("  3. AsyncWriteChapters._call_one() — same as #1 for async path")
    print("  4. AsyncWriteChapters.exec()  — pass flag through return dict")
    print("  5. AsyncWriteChapters.prep()  — add flag to item dict")
