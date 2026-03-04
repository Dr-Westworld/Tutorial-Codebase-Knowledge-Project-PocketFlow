"""
Prometheus metrics module for monitoring PocketFlow tutorial generation system.
Tracks CPU, memory, and execution time metrics for nodes and functions.
"""

from prometheus_client import (
    Counter, Gauge, Histogram, Info, REGISTRY
)
import psutil
import os

# Execution time metrics (in seconds)
function_execution_time_seconds = Histogram(
    'function_execution_time_seconds',
    'Execution time for individual functions',
    labelnames=['function_name', 'node', 'status'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
)

node_execution_time_seconds = Histogram(
    'node_execution_time_seconds',
    'Execution time for each node',
    labelnames=['node_name', 'repo_name', 'status'],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 3600.0]
)

# Memory metrics (in bytes)
function_memory_usage_bytes = Gauge(
    'function_memory_usage_bytes',
    'Peak memory usage for individual functions',
    labelnames=['function_name', 'node']
)

function_memory_average_bytes = Gauge(
    'function_memory_average_bytes',
    'Average memory usage for individual functions',
    labelnames=['function_name', 'node']
)

node_memory_peak_bytes = Gauge(
    'node_memory_peak_bytes',
    'Peak memory usage for each node',
    labelnames=['node_name', 'repo_name']
)

node_memory_average_bytes = Gauge(
    'node_memory_average_bytes',
    'Average memory usage for each node',
    labelnames=['node_name', 'repo_name']
)

# CPU metrics (in percent)
function_cpu_percent = Gauge(
    'function_cpu_percent',
    'Average CPU utilization percentage for functions',
    labelnames=['function_name', 'node']
)

node_cpu_percent = Gauge(
    'node_cpu_percent',
    'Average CPU utilization percentage for nodes',
    labelnames=['node_name', 'repo_name']
)

# Repository metadata
repository_metrics = Info(
    'repository_metrics',
    'Repository metadata and statistics',
    labelnames=['repo_name']
)

# Total execution time
total_tutorial_generation_time_seconds = Gauge(
    'total_tutorial_generation_time_seconds',
    'Total end-to-end time for tutorial generation',
    labelnames=['repo_name']
)

# LLM API metrics
llm_api_call_duration_seconds = Histogram(
    'llm_api_call_duration_seconds',
    'Duration of individual LLM API calls',
    labelnames=['model', 'use_cache', 'cache_hit'],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
)

llm_cache_hits_total = Counter(
    'llm_cache_hits_total',
    'Total number of LLM cache hits',
    labelnames=['model']
)

llm_api_calls_total = Counter(
    'llm_api_calls_total',
    'Total number of LLM API calls',
    labelnames=['model', 'status']
)

# File processing metrics
files_processed_total = Counter(
    'files_processed_total',
    'Total number of files processed',
    labelnames=['source', 'repo_name', 'status']
)

file_processing_duration_seconds = Histogram(
    'file_processing_duration_seconds',
    'Duration to process individual files',
    labelnames=['source', 'repo_name'],
    buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0]
)

# Abstraction metrics
abstractions_identified_total = Gauge(
    'abstractions_identified_total',
    'Total number of abstractions identified',
    labelnames=['repo_name']
)

relationships_found_total = Gauge(
    'relationships_found_total',
    'Total number of relationships found between abstractions',
    labelnames=['repo_name']
)

chapters_written_total = Gauge(
    'chapters_written_total',
    'Total number of chapters written',
    labelnames=['repo_name']
)


class MetricsCollector:
    """Helper class for recording and managing metrics"""

    @staticmethod
    def get_process_memory_info():
        """Get current process memory info in bytes"""
        try:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return {
                'rss': mem_info.rss,  # Resident Set Size (actual physical memory)
                'vms': mem_info.vms,  # Virtual Memory Size
            }
        except Exception:
            return {'rss': 0, 'vms': 0}

    @staticmethod
    def get_cpu_percent(interval=0.1):
        """Get current process CPU percentage"""
        try:
            process = psutil.Process(os.getpid())
            return process.cpu_percent(interval=interval)
        except Exception:
            return 0.0

    @staticmethod
    def record_function_metrics(function_name, node_name, execution_time_sec,
                                memory_peak_bytes, memory_avg_bytes, cpu_percent,
                                status='success'):
        """Record metrics for a function execution"""
        try:
            function_execution_time_seconds.labels(
                function_name=function_name,
                node=node_name,
                status=status
            ).observe(execution_time_sec)

            function_memory_usage_bytes.labels(
                function_name=function_name,
                node=node_name
            ).set(memory_peak_bytes)

            function_memory_average_bytes.labels(
                function_name=function_name,
                node=node_name
            ).set(memory_avg_bytes)

            function_cpu_percent.labels(
                function_name=function_name,
                node=node_name
            ).set(cpu_percent)
        except Exception as e:
            print(f"Error recording function metrics: {e}")

    @staticmethod
    def record_node_metrics(node_name, repo_name, execution_time_sec,
                           memory_peak_bytes, memory_avg_bytes, cpu_percent,
                           status='success'):
        """Record metrics for a node execution"""
        try:
            node_execution_time_seconds.labels(
                node_name=node_name,
                repo_name=repo_name,
                status=status
            ).observe(execution_time_sec)

            node_memory_peak_bytes.labels(
                node_name=node_name,
                repo_name=repo_name
            ).set(memory_peak_bytes)

            node_memory_average_bytes.labels(
                node_name=node_name,
                repo_name=repo_name
            ).set(memory_avg_bytes)

            node_cpu_percent.labels(
                node_name=node_name,
                repo_name=repo_name
            ).set(cpu_percent)
        except Exception as e:
            print(f"Error recording node metrics: {e}")

    @staticmethod
    def record_repository_metrics(repo_name, repo_size_mb, file_count, language):
        """Record repository metadata"""
        try:
            repository_metrics.labels(repo_name=repo_name).info({
                'repo_size_mb': str(repo_size_mb),
                'file_count': str(file_count),
                'language': language
            })
        except Exception as e:
            print(f"Error recording repository metrics: {e}")

    @staticmethod
    def record_total_generation_time(repo_name, total_time_sec):
        """Record total end-to-end generation time"""
        try:
            total_tutorial_generation_time_seconds.labels(
                repo_name=repo_name
            ).set(total_time_sec)
        except Exception as e:
            print(f"Error recording total generation time: {e}")

    @staticmethod
    def record_llm_call(model, use_cache, cache_hit, duration_sec, status='success'):
        """Record LLM API call metrics"""
        try:
            llm_api_call_duration_seconds.labels(
                model=model,
                use_cache=str(use_cache),
                cache_hit=str(cache_hit)
            ).observe(duration_sec)

            if cache_hit:
                llm_cache_hits_total.labels(model=model).inc()

            llm_api_calls_total.labels(
                model=model,
                status=status
            ).inc()
        except Exception as e:
            print(f"Error recording LLM call metrics: {e}")

    @staticmethod
    def record_file_processed(source, repo_name, status='success'):
        """Record a file processing event"""
        try:
            files_processed_total.labels(
                source=source,
                repo_name=repo_name,
                status=status
            ).inc()
        except Exception as e:
            print(f"Error recording file processed: {e}")

    @staticmethod
    def record_file_processing_time(source, repo_name, duration_sec):
        """Record time to process a file"""
        try:
            file_processing_duration_seconds.labels(
                source=source,
                repo_name=repo_name
            ).observe(duration_sec)
        except Exception as e:
            print(f"Error recording file processing time: {e}")

    @staticmethod
    def set_abstractions_count(repo_name, count):
        """Set the count of abstractions identified"""
        try:
            abstractions_identified_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting abstractions count: {e}")

    @staticmethod
    def set_relationships_count(repo_name, count):
        """Set the count of relationships found"""
        try:
            relationships_found_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting relationships count: {e}")

    @staticmethod
    def set_chapters_count(repo_name, count):
        """Set the count of chapters written"""
        try:
            chapters_written_total.labels(repo_name=repo_name).set(count)
        except Exception as e:
            print(f"Error setting chapters count: {e}")
