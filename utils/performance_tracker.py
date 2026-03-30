"""
performance_tracker.py
───────────────────────
Performance tracking utilities for PocketFlow tutorial generation.

New in this version (research gaps addressed)
─────────────────────────────────────────────
1. MemoryDivergenceTracker  (gap: tracemalloc vs psutil divergence log)
   Samples both memory probes at 100 ms intervals, writes a JSONL file
   containing (timestamp, psutil_rss, tracemalloc_current, tracemalloc_peak,
   divergence_bytes, divergence_pct) for every sampled moment.

2. track_execution  (unchanged API, enhanced internals)
   Now optionally integrates with CallTreeRecorder (utils/call_tree.py)
   when use_call_tree=True. Falls back silently if call_tree is not available.

3. track_performance decorator  (unchanged API)
   Wraps sync functions — used on prep/exec/post to get per-phase granularity.

4. Async variants
   track_execution_async  — async context manager for use in AsyncWriteChapters.
   track_performance_async — decorator for async functions.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import threading
import time
import tracemalloc
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Dict, List, Optional

import psutil

from utils.metrics import (
    MetricsCollector,
    function_execution_time_seconds,
    function_memory_average_bytes,
    function_memory_usage_bytes,
    function_cpu_percent,
)


# ──────────────────────────────────────────────────────────────────────────────
# 1.  MemoryDivergenceTracker
# ──────────────────────────────────────────────────────────────────────────────

class MemoryDivergenceTracker:
    """
    Background thread that samples psutil RSS and tracemalloc at a fixed
    interval and writes every sample to a JSONL log file.

    The divergence between the two probes is the key research metric:

        divergence_bytes = psutil_rss - tracemalloc_current

    A large, growing divergence indicates that the Python heap (measured by
    tracemalloc) underestimates real memory growth — typically due to native
    C extensions, torch tensors, or OS-level allocator fragmentation.

    Usage
    ─────
        tracker = MemoryDivergenceTracker(
            log_path="profiling_reports/mem_divergence.jsonl",
            interval_ms=100,
            label="WriteChapters",
        )
        tracker.start()
        ... heavy work ...
        tracker.stop()
        summary = tracker.summary()   # dict with mean/max divergence

    Context manager form
    ────────────────────
        with MemoryDivergenceTracker.context("WriteChapters") as t:
            ... heavy work ...
        summary = t.summary()
    """

    def __init__(
        self,
        log_path:    str   = "profiling_reports/mem_divergence.jsonl",
        interval_ms: int   = 100,
        label:       str   = "unnamed",
    ) -> None:
        self.log_path    = log_path
        self.interval_s  = interval_ms / 1000.0
        self.label       = label
        self._samples:   List[Dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread:    Optional[threading.Thread] = None
        self._process    = psutil.Process(os.getpid())

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> "MemoryDivergenceTracker":
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s * 5)
        self._flush()

    # ── internal ─────────────────────────────────────────────────────────────

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            t_start = time.perf_counter()
            self._take_sample()
            elapsed = time.perf_counter() - t_start
            sleep_for = max(0.0, self.interval_s - elapsed)
            self._stop_event.wait(timeout=sleep_for)

    def _take_sample(self) -> None:
        ts = time.time()
        try:
            rss = self._process.memory_info().rss
        except Exception:
            rss = 0

        try:
            tm_cur, tm_peak = tracemalloc.get_traced_memory()
        except Exception:
            tm_cur, tm_peak = 0, 0

        divergence     = rss - tm_cur
        divergence_pct = (divergence / rss * 100) if rss > 0 else 0.0

        self._samples.append({
            "ts":                ts,
            "label":             self.label,
            "psutil_rss_bytes":  rss,
            "tm_current_bytes":  tm_cur,
            "tm_peak_bytes":     tm_peak,
            "divergence_bytes":  divergence,
            "divergence_pct":    divergence_pct,
        })

    def _flush(self) -> None:
        if not self._samples:
            return
        os.makedirs(os.path.dirname(self.log_path) if os.path.dirname(self.log_path) else ".", exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            for s in self._samples:
                f.write(json.dumps(s) + "\n")

    # ── analysis ─────────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        if not self._samples:
            return {"label": self.label, "n_samples": 0}
        divs = [s["divergence_bytes"] for s in self._samples]
        rss  = [s["psutil_rss_bytes"]  for s in self._samples]
        return {
            "label":                 self.label,
            "n_samples":             len(self._samples),
            "interval_ms":           int(self.interval_s * 1000),
            "max_divergence_bytes":  max(divs),
            "mean_divergence_bytes": int(sum(divs) / len(divs)),
            "max_rss_bytes":         max(rss),
            "peak_divergence_pct":   max(s["divergence_pct"] for s in self._samples),
        }

    # ── context manager ──────────────────────────────────────────────────────

    @classmethod
    @contextmanager
    def context(
        cls,
        label:       str = "unnamed",
        log_path:    str = "profiling_reports/mem_divergence.jsonl",
        interval_ms: int = 100,
    ):
        tracker = cls(log_path=log_path, interval_ms=interval_ms, label=label)
        tracker.start()
        try:
            yield tracker
        finally:
            tracker.stop()


# ──────────────────────────────────────────────────────────────────────────────
# 2.  Sync track_execution context manager (enhanced)
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def track_execution(
    section_name:   str,
    node_name:      str  = "unknown",
    use_call_tree:  bool = True,
    use_divergence: bool = False,
    divergence_log: str  = "profiling_reports/mem_divergence.jsonl",
):
    """
    Context manager to track wall-clock time, memory, and CPU for any block.

    Parameters
    ──────────
    section_name   : label for Prometheus (function_name label)
    node_name      : label for Prometheus (node label)
    use_call_tree  : if True, also records into the thread-local CallTree
                     (requires utils/call_tree.py to be importable)
    use_divergence : if True, starts a MemoryDivergenceTracker at 100 ms
                     intervals for this block (adds ~2 MB overhead)
    divergence_log : path for the divergence JSONL log
    """
    process      = psutil.Process(os.getpid())
    start_time   = time.perf_counter()
    start_memory = process.memory_info().rss

    process.cpu_percent()   # prime rolling counter
    time.sleep(0.01)        # stabilise CPU reading

    tm_was_tracing = tracemalloc.is_tracing()
    if not tm_was_tracing:
        tracemalloc.start()

    # Optional: divergence tracker
    div_tracker: Optional[MemoryDivergenceTracker] = None
    if use_divergence:
        div_tracker = MemoryDivergenceTracker(
            log_path=divergence_log,
            interval_ms=100,
            label=f"{node_name}::{section_name}",
        )
        div_tracker.start()

    # Optional: call-tree push
    call_node_ref = None
    if use_call_tree:
        try:
            from utils.call_tree import CallTreeRecorder
            call_node_ref = CallTreeRecorder.push(section_name, node_name,
                                                   memory_start=start_memory)
        except ImportError:
            pass

    status = "success"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        end_time   = time.perf_counter()
        end_memory = process.memory_info().rss
        exec_time  = end_time - start_time
        cpu        = process.cpu_percent()

        # --- memory measurements ---
        if not tm_was_tracing:
            try:
                tm_cur, tm_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            except Exception:
                tm_cur, tm_peak = 0, 0
                try:
                    tracemalloc.stop()
                except Exception:
                    pass
        else:
            try:
                tm_cur, tm_peak = tracemalloc.get_traced_memory()
            except Exception:
                tm_cur, tm_peak = 0, 0

        rss_delta   = end_memory - start_memory
        peak_memory = max(rss_delta, tm_peak, 0)
        avg_memory  = (start_memory + end_memory) / 2

        # --- stop divergence tracker ---
        if div_tracker is not None:
            div_tracker.stop()
            _div_sum = div_tracker.summary()
            try:
                from utils.metrics import memory_divergence_peak_bytes
                memory_divergence_peak_bytes.labels(
                    function_name=section_name, node=node_name
                ).set(_div_sum.get("max_divergence_bytes", 0))
            except Exception:
                pass

        # --- pop call tree ---
        if call_node_ref is not None:
            try:
                from utils.call_tree import CallTreeRecorder
                CallTreeRecorder.pop(
                    call_node_ref,
                    memory_end=end_memory,
                    tracemalloc_peak=tm_peak,
                    psutil_peak=max(rss_delta, 0),
                    cpu_percent=cpu,
                    status=status,
                )
            except Exception:
                pass

        # --- Prometheus ---
        try:
            MetricsCollector.record_function_metrics(
                function_name=section_name,
                node_name=node_name,
                execution_time_sec=exec_time,
                memory_peak_bytes=int(peak_memory),
                memory_avg_bytes=int(avg_memory),
                cpu_percent=cpu,
                status=status,
            )
        except Exception as exc:
            print(f"[track_execution] Prometheus error for {section_name}: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# 3.  Async track_execution (for AsyncWriteChapters)
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def track_execution_async(
    section_name: str,
    node_name:    str = "unknown",
):
    """
    Async context manager equivalent of track_execution.
    Uses the same Prometheus metrics so async results are directly comparable.

    Usage
    ─────
        async with track_execution_async("exec_chapter_1", node_name="AsyncWriteChapters"):
            content = await some_async_llm_call()
    """
    process      = psutil.Process(os.getpid())
    start_time   = time.perf_counter()
    start_memory = process.memory_info().rss
    process.cpu_percent()

    tm_was_tracing = tracemalloc.is_tracing()
    if not tm_was_tracing:
        tracemalloc.start()

    status = "success"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        end_time   = time.perf_counter()
        end_memory = process.memory_info().rss
        exec_time  = end_time - start_time
        cpu        = process.cpu_percent()

        if not tm_was_tracing:
            try:
                _cur, tm_peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            except Exception:
                tm_peak = 0
                try:
                    tracemalloc.stop()
                except Exception:
                    pass
        else:
            try:
                _cur, tm_peak = tracemalloc.get_traced_memory()
            except Exception:
                tm_peak = 0

        peak_memory = max(end_memory - start_memory, tm_peak, 0)
        avg_memory  = (start_memory + end_memory) / 2

        try:
            MetricsCollector.record_function_metrics(
                function_name=section_name,
                node_name=node_name,
                execution_time_sec=exec_time,
                memory_peak_bytes=int(peak_memory),
                memory_avg_bytes=int(avg_memory),
                cpu_percent=cpu,
                status=status,
            )
        except Exception as exc:
            print(f"[track_execution_async] Prometheus error for {section_name}: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# 4.  Sync decorator (unchanged API + call-tree awareness)
# ──────────────────────────────────────────────────────────────────────────────

def track_performance(
    function_name: Optional[str] = None,
    node_name:     str           = "unknown",
    custom_labels: Optional[Dict] = None,
    use_call_tree: bool           = True,
):
    """
    Decorator to track performance of a synchronous function.

    Wraps the decorated function with the same measurement logic as
    track_execution but registers at the decorator-application site.

    Usage
    ─────
        @track_performance(node_name="FetchRepo")
        def my_function():
            pass

        @track_performance(function_name="prep_phase", node_name="WriteChapters")
        def prep(self, shared):
            ...
    """
    def decorator(func: Callable) -> Callable:
        fname = function_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with track_execution(fname, node_name=node_name,
                                 use_call_tree=use_call_tree):
                return func(*args, **kwargs)

        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# 5.  Async decorator
# ──────────────────────────────────────────────────────────────────────────────

def track_performance_async(
    function_name: Optional[str] = None,
    node_name:     str           = "unknown",
):
    """
    Decorator to track performance of an async function.

    Usage
    ─────
        @track_performance_async(node_name="AsyncWriteChapters")
        async def generate_chapter(prompt: str) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        fname = function_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async with track_execution_async(fname, node_name=node_name):
                return await func(*args, **kwargs)

        return wrapper
    return decorator
