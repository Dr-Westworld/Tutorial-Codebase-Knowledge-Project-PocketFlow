"""
Performance tracking decorators and context managers for monitoring function execution.
Automatically captures execution time, memory usage, and CPU utilization.
"""

import functools
import time
import tracemalloc
import os
from contextlib import contextmanager
from utils.metrics import (
    MetricsCollector, function_execution_time_seconds,
    function_memory_usage_bytes, function_memory_average_bytes,
    function_cpu_percent
)
import psutil


def track_performance(function_name=None, node_name="unknown", custom_labels=None):
    """
    Decorator to track performance metrics (time, memory, CPU) of a function.

    Args:
        function_name: Name for the metric label (defaults to function's __name__)
        node_name: Node name for the metric label
        custom_labels: Dict of additional labels to include

    Usage:
        @track_performance(node_name="FetchRepo")
        def my_function():
            pass
    """
    def decorator(func):
        func_name = function_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get initial state
            process = psutil.Process(os.getpid())
            start_time = time.perf_counter()
            start_memory = process.memory_info().rss

            # Start CPU measurement
            process.cpu_percent()  # Prime the counter
            time.sleep(0.01)  # Small delay for accurate CPU measurement

            # Start memory tracing
            tracemalloc.start()

            try:
                # Execute function
                result = func(*args, **kwargs)
                status = 'success'
            except Exception as e:
                status = 'failed'
                # Still record metrics even on failure
                tracemalloc.stop()
                raise
            finally:
                # Collect metrics
                end_time = time.perf_counter()
                end_memory = process.memory_info().rss

                execution_time = end_time - start_time
                memory_delta = end_memory - start_memory
                peak_memory = end_memory - start_memory

                try:
                    # Get peak memory from tracemalloc
                    current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    peak_memory = max(peak_memory, peak)
                except Exception:
                    tracemalloc.stop()

                # Calculate average memory
                avg_memory = (start_memory + end_memory) / 2

                # Get CPU usage (already measured during execution)
                cpu_percent = process.cpu_percent()

                # Record metrics
                try:
                    MetricsCollector.record_function_metrics(
                        function_name=func_name,
                        node_name=node_name,
                        execution_time_sec=execution_time,
                        memory_peak_bytes=int(peak_memory),
                        memory_avg_bytes=int(avg_memory),
                        cpu_percent=cpu_percent,
                        status=status
                    )
                except Exception as e:
                    print(f"Error recording metrics for {func_name}: {e}")

            return result

        return wrapper

    return decorator


@contextmanager
def track_execution(section_name, node_name="unknown"):
    """
    Context manager to track execution of a code block.

    Usage:
        with track_execution("data_processing", node_name="FetchRepo"):
            # code here will be tracked
            pass
    """
    process = psutil.Process(os.getpid())
    start_time = time.perf_counter()
    start_memory = process.memory_info().rss

    # Start CPU measurement
    process.cpu_percent()
    time.sleep(0.01)

    tracemalloc.start()

    try:
        yield
        status = 'success'
    except Exception as e:
        status = 'failed'
        tracemalloc.stop()
        raise
    finally:
        # Collect metrics
        end_time = time.perf_counter()
        end_memory = process.memory_info().rss

        execution_time = end_time - start_time

        try:
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_memory = end_memory - start_memory
            peak_memory = max(peak_memory, peak)
        except Exception:
            tracemalloc.stop()
            peak_memory = end_memory - start_memory

        avg_memory = (start_memory + end_memory) / 2
        cpu_percent = process.cpu_percent()

        # Record metrics
        try:
            MetricsCollector.record_function_metrics(
                function_name=section_name,
                node_name=node_name,
                execution_time_sec=execution_time,
                memory_peak_bytes=int(peak_memory),
                memory_avg_bytes=int(avg_memory),
                cpu_percent=cpu_percent,
                status=status
            )
        except Exception as e:
            print(f"Error recording metrics for {section_name}: {e}")
