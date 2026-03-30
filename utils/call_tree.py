"""
utils/call_tree.py
──────────────────
Thread-local call-tree recorder for flame-graph style profiling.
(Moved from project root so `from utils.call_tree import record_call` works.)

Every `with record_call(name, node_name)` block pushes a CallNode onto the
thread-local stack and pops it when the block exits, recording:
  - wall-clock duration
  - psutil RSS delta  (physical memory)
  - tracemalloc peak  (Python heap allocations)
  - CPU %

Completed root trees are stored in CallTreeRecorder._all_trees and can be
exported as:
  - raw JSON             → export_json()
  - speedscope-compatible flamegraph JSON → export_flamegraph()
"""

from __future__ import annotations

import json
import os
import threading
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psutil


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CallNode:
    """One instrumented block on the call tree."""
    name:                   str
    node_name:              str
    start_time:             float
    end_time:               float  = 0.0
    depth:                  int    = 0
    memory_start_bytes:     int    = 0
    memory_end_bytes:       int    = 0
    tracemalloc_peak_bytes: int    = 0
    psutil_peak_bytes:      int    = 0
    cpu_percent:            float  = 0.0
    status:                 str    = "running"
    children:               List["CallNode"] = field(default_factory=list)

    def duration(self) -> float:
        return max(self.end_time - self.start_time, 0.0)

    def memory_delta(self) -> int:
        return self.memory_end_bytes - self.memory_start_bytes

    def max_memory_pressure(self) -> int:
        return max(self.psutil_peak_bytes, self.tracemalloc_peak_bytes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":                      self.name,
            "node_name":                 self.node_name,
            "start_time":                self.start_time,
            "end_time":                  self.end_time,
            "duration_sec":              self.duration(),
            "depth":                     self.depth,
            "memory_start_bytes":        self.memory_start_bytes,
            "memory_end_bytes":          self.memory_end_bytes,
            "memory_delta_bytes":        self.memory_delta(),
            "tracemalloc_peak_bytes":    self.tracemalloc_peak_bytes,
            "psutil_peak_bytes":         self.psutil_peak_bytes,
            "max_memory_pressure_bytes": self.max_memory_pressure(),
            "cpu_percent":               self.cpu_percent,
            "status":                    self.status,
            "children":                  [c.to_dict() for c in self.children],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Recorder
# ─────────────────────────────────────────────────────────────────────────────

class CallTreeRecorder:
    _local     = threading.local()
    _lock      = threading.Lock()
    _all_trees: List[Dict[str, Any]] = []

    @classmethod
    def _stack(cls) -> List[CallNode]:
        if not hasattr(cls._local, "stack"):
            cls._local.stack = []
        return cls._local.stack

    @classmethod
    def push(cls, name: str, node_name: str, memory_start: int = 0) -> CallNode:
        stack = cls._stack()
        node  = CallNode(
            name=name,
            node_name=node_name,
            start_time=time.perf_counter(),
            depth=len(stack),
            memory_start_bytes=memory_start,
        )
        if stack:
            stack[-1].children.append(node)
        else:
            cls._local.root = node
        stack.append(node)
        return node

    @classmethod
    def pop(cls, node: CallNode, *, memory_end: int = 0, tracemalloc_peak: int = 0,
            psutil_peak: int = 0, cpu_percent: float = 0.0, status: str = "success") -> None:
        stack = cls._stack()
        node.end_time               = time.perf_counter()
        node.memory_end_bytes       = memory_end
        node.tracemalloc_peak_bytes = tracemalloc_peak
        node.psutil_peak_bytes      = psutil_peak
        node.cpu_percent            = cpu_percent
        node.status                 = status
        if stack and stack[-1] is node:
            stack.pop()
        if not stack and getattr(cls._local, "root", None) is node:
            with cls._lock:
                cls._all_trees.append(node.to_dict())
            cls._local.root = None

    @classmethod
    def all_trees(cls) -> List[Dict[str, Any]]:
        with cls._lock:
            return list(cls._all_trees)

    @classmethod
    def export_json(cls, path: str = "profiling_reports/call_trees.json") -> List[Dict]:
        trees = cls.all_trees()
        _ensure_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trees, f, indent=2)
        print(f"[CallTree] {len(trees)} trees → {path}")
        return trees

    @classmethod
    def export_flamegraph(cls, path: str = "profiling_reports/flamegraph.json") -> List[Dict]:
        trees  = cls.all_trees()
        frames: List[Dict] = []

        def _flatten(node: Dict) -> None:
            frames.append({
                "name":         f"{node['node_name']}::{node['name']}",
                "start":        node["start_time"],
                "end":          node["end_time"],
                "duration_sec": node["duration_sec"],
                "depth":        node["depth"],
                "memory_delta": node["memory_delta_bytes"],
                "max_memory":   node["max_memory_pressure_bytes"],
                "cpu_percent":  node["cpu_percent"],
                "status":       node["status"],
            })
            for child in node.get("children", []):
                _flatten(child)

        for tree in trees:
            _flatten(tree)
        frames.sort(key=lambda x: x["start"])
        out = {"frames": frames, "total_trees": len(trees)}
        _ensure_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"[CallTree] {len(frames)} frames → {path}")
        return frames

    @classmethod
    def summary(cls) -> List[Dict]:
        rows: List[Dict] = []

        def _collect(node: Dict) -> None:
            rows.append({
                "name":             node["name"],
                "node_name":        node["node_name"],
                "duration_sec":     node["duration_sec"],
                "max_memory_bytes": node["max_memory_pressure_bytes"],
                "cpu_percent":      node["cpu_percent"],
                "depth":            node["depth"],
                "status":           node["status"],
            })
            for child in node.get("children", []):
                _collect(child)

        for tree in cls.all_trees():
            _collect(tree)
        rows.sort(key=lambda r: r["duration_sec"], reverse=True)
        return rows

    @classmethod
    def print_summary(cls, top_n: int = 20) -> None:
        rows = cls.summary()
        print(f"\n{'─'*72}")
        print(f"  Call-Tree Summary — top {top_n} by duration")
        print(f"{'─'*72}")
        for r in rows[:top_n]:
            print(
                f"  {r['name']:<35} {r['node_name']:<22} "
                f"{r['duration_sec']:>7.3f}s  "
                f"{r['max_memory_bytes']/1024/1024:>8.1f}MB  "
                f"{r['cpu_percent']:>5.1f}%"
            )
        print(f"{'─'*72}\n")

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._all_trees.clear()
        cls._local.stack = []
        cls._local.root  = None


# ─────────────────────────────────────────────────────────────────────────────
# Public context manager
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def record_call(name: str, node_name: str = "unknown"):
    """
    Context manager that records one instrumented block into the call tree.
    Nesting is handled automatically — inner calls become children of
    the currently-active outer call on the same thread.
    """
    process   = psutil.Process(os.getpid())
    rss_start = process.memory_info().rss
    process.cpu_percent()

    tm_was_tracing = tracemalloc.is_tracing()
    if not tm_was_tracing:
        tracemalloc.start()

    call_node  = CallTreeRecorder.push(name, node_name, memory_start=rss_start)
    exc_status = "success"

    try:
        yield call_node
    except Exception:
        exc_status = "failed"
        raise
    finally:
        rss_end = process.memory_info().rss
        cpu     = process.cpu_percent()

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

        CallTreeRecorder.pop(
            call_node,
            memory_end=rss_end,
            tracemalloc_peak=tm_peak,
            psutil_peak=max(rss_end - rss_start, 0),
            cpu_percent=cpu,
            status=exc_status,
        )


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
