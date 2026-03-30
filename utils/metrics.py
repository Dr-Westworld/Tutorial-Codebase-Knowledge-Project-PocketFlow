"""
metrics.py
──────────
Prometheus metrics module for PocketFlow tutorial generation system.

New metrics added for research paper gaps
─────────────────────────────────────────
• framework_overhead_seconds     — PocketFlow Node/Flow wrapper overhead
• memory_divergence_peak_bytes   — psutil-RSS vs tracemalloc peak gap per function
• async_vs_sync_speedup_ratio    — AsyncWriteChapters / SyncWriteChapters time ratio
• call_tree_function_time_seconds — per-function histogram from call-tree recorder
"""

from prometheus_client import Counter, Gauge, Histogram, Info, REGISTRY
import psutil
import os


# ──────────────────────────────────────────────────────────────────────────────
# Existing metrics (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

function_execution_time_seconds = Histogram(
    'function_execution_time_seconds',
    'Execution time for individual functions',
    labelnames=['function_name', 'node', 'status'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

node_execution_time_seconds = Histogram(
    'node_execution_time_seconds',
    'Execution time for each node',
    labelnames=['node_name', 'repo_name', 'status'],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 3600.0],
)

function_memory_usage_bytes = Gauge(
    'function_memory_usage_bytes',
    'Peak memory usage for individual functions',
    labelnames=['function_name', 'node'],
)

function_memory_average_bytes = Gauge(
    'function_memory_average_bytes',
    'Average memory usage for individual functions',
    labelnames=['function_name', 'node'],
)

node_memory_peak_bytes = Gauge(
    'node_memory_peak_bytes',
    'Peak memory usage for each node',
    labelnames=['node_name', 'repo_name'],
)

node_memory_average_bytes = Gauge(
    'node_memory_average_bytes',
    'Average memory usage for each node',
    labelnames=['node_name', 'repo_name'],
)

function_cpu_percent = Gauge(
    'function_cpu_percent',
    'Average CPU utilization percentage for functions',
    labelnames=['function_name', 'node'],
)

node_cpu_percent = Gauge(
    'node_cpu_percent',
    'Average CPU utilization percentage for nodes',
    labelnames=['node_name', 'repo_name'],
)

repository_metrics = Info(
    'repository_metrics',
    'Repository metadata and statistics',
    labelnames=['repo_name'],
)

total_tutorial_generation_time_seconds = Gauge(
    'total_tutorial_generation_time_seconds',
    'Total end-to-end time for tutorial generation',
    labelnames=['repo_name'],
)

llm_api_call_duration_seconds = Histogram(
    'llm_api_call_duration_seconds',
    'Duration of individual LLM API calls',
    labelnames=['model', 'use_cache', 'cache_hit'],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

llm_cache_hits_total = Counter(
    'llm_cache_hits_total',
    'Total number of LLM cache hits',
    labelnames=['model'],
)

llm_api_calls_total = Counter(
    'llm_api_calls_total',
    'Total number of LLM API calls',
    labelnames=['model', 'status'],
)

files_processed_total = Counter(
    'files_processed_total',
    'Total number of files processed',
    labelnames=['source', 'repo_name', 'status'],
)

file_processing_duration_seconds = Histogram(
    'file_processing_duration_seconds',
    'Duration to process individual files',
    labelnames=['source', 'repo_name'],
    buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
)

abstractions_identified_total = Gauge(
    'abstractions_identified_total',
    'Total number of abstractions identified',
    labelnames=['repo_name'],
)

relationships_found_total = Gauge(
    'relationships_found_total',
    'Total number of relationships found between abstractions',
    labelnames=['repo_name'],
)

chapters_written_total = Gauge(
    'chapters_written_total',
    'Total number of chapters written',
    labelnames=['repo_name'],
)


# ──────────────────────────────────────────────────────────────────────────────
# NEW METRICS  (research paper gaps)
# ──────────────────────────────────────────────────────────────────────────────

# Gap 2 — PocketFlow framework overhead
framework_overhead_seconds = Histogram(
    'framework_overhead_seconds',
    'Wall-clock overhead of PocketFlow Node/Flow wrappers vs flat baseline. '
    'Observe with (pocketflow_total - flat_total) for each repo run.',
    labelnames=['pipeline'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# Gap 3 — tracemalloc vs psutil divergence
memory_divergence_peak_bytes = Gauge(
    'memory_divergence_peak_bytes',
    'Peak divergence between psutil RSS and tracemalloc current for a '
    'function. Positive value = native/C-extension memory not tracked by '
    'tracemalloc. Keyed per function to identify which call sites have the '
    'largest measurement gap.',
    labelnames=['function_name', 'node'],
)

# Gap 1 — async vs sync WriteChapters
async_vs_sync_speedup_ratio = Gauge(
    'async_vs_sync_speedup_ratio',
    'Speedup ratio of AsyncWriteChapters over sync BatchNode: '
    'sync_time / async_time. Values >1 indicate parallelism benefit. '
    'Labeled by repo_name and chapter_count to track how speedup scales.',
    labelnames=['repo_name', 'chapter_count'],
)

async_write_chapters_time_seconds = Gauge(
    'async_write_chapters_time_seconds',
    'Total wall-clock time for AsyncWriteChapters (parallel) run.',
    labelnames=['repo_name', 'chapter_count'],
)

sync_write_chapters_time_seconds = Gauge(
    'sync_write_chapters_time_seconds',
    'Total wall-clock time for sync WriteChapters (sequential) run.',
    labelnames=['repo_name', 'chapter_count'],
)

# Gap 5 — call-tree / per-function granularity
call_tree_function_time_seconds = Histogram(
    'call_tree_function_time_seconds',
    'Per-function execution time captured by the call-tree recorder '
    '(prep / exec / post phases of every node). Finer-grained than '
    'node_execution_time_seconds. Use this to build flame-graph style '
    'visualisations and identify the single most expensive call site.',
    labelnames=['function_name', 'node_name', 'phase', 'status'],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
)

call_tree_function_memory_bytes = Gauge(
    'call_tree_function_memory_bytes',
    'Peak memory (max of psutil_rss_delta and tracemalloc_peak) '
    'for each call-tree node. Labeled by function and phase.',
    labelnames=['function_name', 'node_name', 'phase'],
)


# ──────────────────────────────────────────────────────────────────────────────
# MetricsCollector  (extended with new static methods)
# ──────────────────────────────────────────────────────────────────────────────

class MetricsCollector:
    """Helper class for recording and managing metrics."""

    # ── existing methods (unchanged) ─────────────────────────────────────────

    @staticmethod
    def get_process_memory_info():
        try:
            process  = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return {'rss': mem_info.rss, 'vms': mem_info.vms}
        except Exception:
            return {'rss': 0, 'vms': 0}

    @staticmethod
    def get_cpu_percent(interval: float = 0.1) -> float:
        try:
            return psutil.Process(os.getpid()).cpu_percent(interval=interval)
        except Exception:
            return 0.0

    @staticmethod
    def record_function_metrics(function_name, node_name, execution_time_sec,
                                memory_peak_bytes, memory_avg_bytes, cpu_percent,
                                status='success'):
        try:
            function_execution_time_seconds.labels(
                function_name=function_name, node=node_name, status=status,
            ).observe(execution_time_sec)
            function_memory_usage_bytes.labels(
                function_name=function_name, node=node_name,
            ).set(memory_peak_bytes)
            function_memory_average_bytes.labels(
                function_name=function_name, node=node_name,
            ).set(memory_avg_bytes)
            function_cpu_percent.labels(
                function_name=function_name, node=node_name,
            ).set(cpu_percent)
        except Exception as e:
            print(f"Error recording function metrics: {e}")

    @staticmethod
    def record_node_metrics(node_name, repo_name, execution_time_sec,
                            memory_peak_bytes, memory_avg_bytes, cpu_percent,
                            status='success'):
        try:
            node_execution_time_seconds.labels(
                node_name=node_name, repo_name=repo_name, status=status,
            ).observe(execution_time_sec)
            node_memory_peak_bytes.labels(
                node_name=node_name, repo_name=repo_name,
            ).set(memory_peak_bytes)
            node_memory_average_bytes.labels(
                node_name=node_name, repo_name=repo_name,
            ).set(memory_avg_bytes)
            node_cpu_percent.labels(
                node_name=node_name, repo_name=repo_name,
            ).set(cpu_percent)
        except Exception as e:
            print(f"Error recording node metrics: {e}")

    @staticmethod
    def record_repository_metrics(repo_name, repo_size_mb, file_count, language):
        try:
            repository_metrics.labels(repo_name=repo_name).info({
                'repo_size_mb': str(repo_size_mb),
                'file_count':   str(file_count),
                'language':     language,
            })
        except Exception as e:
            print(f"Error recording repository metrics: {e}")

    @staticmethod
    def record_total_generation_time(repo_name, total_time_sec):
        try:
            total_tutorial_generation_time_seconds.labels(
                repo_name=repo_name,
            ).set(total_time_sec)
        except Exception as e:
            print(f"Error recording total generation time: {e}")

    @staticmethod
    def record_llm_call(model, use_cache, cache_hit, duration_sec, status='success'):
        try:
            llm_api_call_duration_seconds.labels(
                model=model, use_cache=str(use_cache), cache_hit=str(cache_hit),
            ).observe(duration_sec)
            if cache_hit:
                llm_cache_hits_total.labels(model=model).inc()
            llm_api_calls_total.labels(model=model, status=status).inc()
        except Exception as e:
            print(f"Error recording LLM call metrics: {e}")

    @staticmethod
    def record_file_processed(source, repo_name, status='success'):
        try:
            files_processed_total.labels(
                source=source, repo_name=repo_name, status=status,
            ).inc()
        except Exception as e:
            print(f"Error recording file processed: {e}")

    @staticmethod
    def record_file_processing_time(source, repo_name, duration_sec):
        try:
            file_processing_duration_seconds.labels(
                source=source, repo_name=repo_name,
            ).observe(duration_sec)
        except Exception as e:
            print(f"Error recording file processing time: {e}")

    @staticmethod
    def set_abstractions_count(repo_name, count):
        try:
            abstractions_identified_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting abstractions count: {e}")

    @staticmethod
    def set_relationships_count(repo_name, count):
        try:
            relationships_found_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting relationships count: {e}")

    @staticmethod
    def set_chapters_count(repo_name, count):
        try:
            chapters_written_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting chapters count: {e}")

    # ── NEW: framework overhead ───────────────────────────────────────────────

    @staticmethod
    def record_framework_overhead(pipeline: str, overhead_sec: float) -> None:
        """
        Record the wall-clock overhead of PocketFlow wrappers for one run.

        Call after measure_framework_overhead() returns:
            MetricsCollector.record_framework_overhead("pocketflow", report["total_overhead_sec"])
        """
        try:
            framework_overhead_seconds.labels(pipeline=pipeline).observe(
                max(overhead_sec, 0.0)
            )
        except Exception as e:
            print(f"Error recording framework overhead: {e}")

    # ── NEW: memory divergence ────────────────────────────────────────────────

    @staticmethod
    def record_memory_divergence(function_name: str, node: str,
                                 divergence_bytes: int) -> None:
        """
        Record the peak divergence between psutil RSS and tracemalloc for a
        single function invocation.
        """
        try:
            memory_divergence_peak_bytes.labels(
                function_name=function_name, node=node,
            ).set(divergence_bytes)
        except Exception as e:
            print(f"Error recording memory divergence: {e}")

    # ── NEW: async vs sync speedup ────────────────────────────────────────────

    @staticmethod
    def record_async_speedup(repo_name: str, chapter_count: int,
                              sync_time: float, async_time: float) -> None:
        """
        Record async vs sync WriteChapters comparison metrics.

        Computes speedup = sync_time / async_time and records all three
        values to Prometheus.
        """
        try:
            label = str(chapter_count)
            sync_write_chapters_time_seconds.labels(
                repo_name=repo_name, chapter_count=label,
            ).set(sync_time)
            async_write_chapters_time_seconds.labels(
                repo_name=repo_name, chapter_count=label,
            ).set(async_time)
            if async_time > 0:
                speedup = sync_time / async_time
                async_vs_sync_speedup_ratio.labels(
                    repo_name=repo_name, chapter_count=label,
                ).set(speedup)
                print(f"[Metrics] Async speedup for {repo_name}: "
                      f"{speedup:.2f}x  (sync={sync_time:.1f}s, async={async_time:.1f}s)")
        except Exception as e:
            print(f"Error recording async speedup: {e}")

    # ── NEW: call-tree function granularity ───────────────────────────────────

    @staticmethod
    def record_call_tree_function(function_name: str, node_name: str,
                                   phase: str, execution_time_sec: float,
                                   memory_peak_bytes: int,
                                   status: str = "success") -> None:
        """
        Record per-function call-tree timing (prep / exec / post phases).
        This complements function_execution_time_seconds with a phase label.

        Call from within prep/post wrappers in nodes.py:
            MetricsCollector.record_call_tree_function(
                "prep", "FetchRepo", "prep", elapsed, peak_mem
            )
        """
        try:
            call_tree_function_time_seconds.labels(
                function_name=function_name,
                node_name=node_name,
                phase=phase,
                status=status,
            ).observe(execution_time_sec)
            call_tree_function_memory_bytes.labels(
                function_name=function_name,
                node_name=node_name,
                phase=phase,
            ).set(memory_peak_bytes)
        except Exception as e:
            print(f"Error recording call-tree function: {e}")
