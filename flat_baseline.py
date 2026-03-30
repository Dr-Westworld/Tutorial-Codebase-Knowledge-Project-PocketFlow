"""
flat_baseline.py
────────────────
Implements the same 6 pipeline operations as plain Python functions —
no Node, BatchNode, or Flow wrappers — so the wall-clock time difference
between a flat run and a PocketFlow run isolates pure framework overhead.

Research usage
──────────────
    from utils.flat_baseline import run_flat_baseline, measure_framework_overhead

    # 1. Run PocketFlow pipeline normally and record its node times
    pocketflow_times = {
        "FetchRepo": 3.2, "IdentifyAbstractions": 45.1, ...
    }

    # 2. Compare
    report = measure_framework_overhead(
        shared_template  = shared,
        pocketflow_time  = 180.0,
        pocketflow_step_times = pocketflow_times,
    )
    # report["total_overhead_pct"]  →  e.g.  2.3 %
    # report["steps"]["WriteChapters"]["overhead_sec"]  →  e.g.  0.4 s

Design notes
────────────
• Each flat_* function wraps its body in track_execution so timings still
  land in Prometheus under the "FlatBaseline" node label.
• The flat WriteChapters runs sequentially (same as the sync BatchNode) so
  the comparison is apples-to-apples.
• A separate async flat baseline (flat_write_chapters_async) runs chapters
  in parallel threads, providing the upper-bound speedup reference.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import os
import time
import yaml
from typing import Any, Dict, List, Optional, Tuple

from utils.call_llm import call_llm
from utils.crawl_github_files import crawl_github_files
from utils.crawl_local_files import crawl_local_files
from utils.performance_tracker import track_execution


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_content_for_indices(files_data: list, indices: list) -> dict:
    content_map: Dict[str, str] = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content
    return content_map


def _parse_yaml_block(response: str) -> Any:
    """Extract and parse the first ```yaml ... ``` block from an LLM response."""
    if "```yaml" not in response:
        return yaml.safe_load(response.strip())
    block = response.strip().split("```yaml")[1].split("```")[0].strip()
    return yaml.safe_load(block)


# ──────────────────────────────────────────────────────────────────────────────
# Flat functions — no Node/BatchNode wrappers
# ──────────────────────────────────────────────────────────────────────────────

def flat_fetch_repo(shared: Dict[str, Any]) -> list:
    """FetchRepo equivalent — plain function."""
    with track_execution("flat_fetch_repo", node_name="FlatBaseline"):
        repo_url  = shared.get("repo_url")
        local_dir = shared.get("local_dir")

        project_name = shared.get("project_name")
        if not project_name:
            project_name = (
                repo_url.split("/")[-1].replace(".git", "") if repo_url
                else os.path.basename(os.path.abspath(local_dir))
            )
            shared["project_name"] = project_name

        if repo_url:
            result = crawl_github_files(
                repo_url=repo_url,
                token=shared.get("github_token"),
                include_patterns=shared["include_patterns"],
                exclude_patterns=shared["exclude_patterns"],
                max_file_size=shared["max_file_size"],
                use_relative_paths=True,
            )
        else:
            result = crawl_local_files(
                directory=local_dir,
                include_patterns=shared["include_patterns"],
                exclude_patterns=shared["exclude_patterns"],
                max_file_size=shared["max_file_size"],
                use_relative_paths=True,
            )

        files_list = list(result.get("files", {}).items())
        if not files_list:
            raise ValueError("FlatBaseline: failed to fetch any files")
        print(f"[FlatBaseline] Fetched {len(files_list)} files.")
        return files_list


def flat_identify_abstractions(files_data: list, shared: Dict[str, Any]) -> list:
    """IdentifyAbstractions equivalent — plain function."""
    project_name    = shared["project_name"]
    use_cache       = shared.get("use_cache", True)
    max_abstr       = shared.get("max_abstraction_num", 10)

    context      = ""
    file_listing = []
    for i, (path, content) in enumerate(files_data):
        context += f"--- File Index {i}: {path} ---\n{content}\n\n"
        file_listing.append(f"- {i} # {path}")

    prompt = (
        f"For the project `{project_name}`:\n\n"
        f"Codebase Context:\n{context}\n\n"
        f"Identify the top 5-{max_abstr} core abstractions.\n"
        f"Files:\n" + "\n".join(file_listing) + "\n\n"
        "Format as YAML list with keys: name, description, file_indices.\n"
        "```yaml\n- name: Example\n  description: Desc.\n  file_indices:\n    - 0 # path\n```"
    )

    with track_execution("flat_identify_abstractions", node_name="FlatBaseline"):
        response = call_llm(prompt, use_cache=use_cache)

    abstractions = _parse_yaml_block(response)
    if not isinstance(abstractions, list):
        raise ValueError("FlatBaseline: IdentifyAbstractions LLM output is not a list")

    # Minimal validation — strip to essential keys only
    validated = []
    for item in abstractions:
        if isinstance(item, dict) and "name" in item and "description" in item:
            raw_indices = item.get("file_indices", [])
            indices = []
            for entry in raw_indices:
                try:
                    if isinstance(entry, int):
                        indices.append(entry)
                    elif isinstance(entry, str) and "#" in entry:
                        indices.append(int(entry.split("#")[0].strip()))
                    else:
                        indices.append(int(str(entry).strip()))
                except (ValueError, TypeError):
                    pass
            validated.append({
                "name":        str(item["name"]).strip(),
                "description": str(item["description"]).strip(),
                "files":       sorted(set(indices)),
            })
    print(f"[FlatBaseline] Identified {len(validated)} abstractions.")
    return validated


def flat_analyze_relationships(abstractions: list, files_data: list,
                                shared: Dict[str, Any]) -> dict:
    """AnalyzeRelationships equivalent — plain function."""
    project_name = shared["project_name"]
    use_cache    = shared.get("use_cache", True)

    abstraction_listing = "\n".join(
        f"{i} # {a['name']}" for i, a in enumerate(abstractions)
    )
    context = "Abstractions:\n" + "\n".join(
        f"- {i}: {a['name']} — {a['description'][:80]}"
        for i, a in enumerate(abstractions)
    )

    prompt = (
        f"For project `{project_name}`:\n\n"
        f"{context}\n\nAbstraction list:\n{abstraction_listing}\n\n"
        "Provide summary and relationships.\n"
        "```yaml\nsummary: |\n  Brief summary.\n"
        "relationships:\n  - from_abstraction: 0 # Name\n"
        "    to_abstraction: 1 # Name\n    label: \"Uses\"\n```"
    )

    with track_execution("flat_analyze_relationships", node_name="FlatBaseline"):
        response = call_llm(prompt, use_cache=use_cache)

    data = _parse_yaml_block(response)
    if not isinstance(data, dict):
        return {"summary": "", "details": []}

    validated_rels = []
    for rel in data.get("relationships", []):
        try:
            from_idx = int(str(rel["from_abstraction"]).split("#")[0].strip())
            to_idx   = int(str(rel["to_abstraction"]).split("#")[0].strip())
            validated_rels.append({"from": from_idx, "to": to_idx, "label": str(rel.get("label", ""))})
        except (ValueError, TypeError, KeyError):
            pass

    return {"summary": str(data.get("summary", "")), "details": validated_rels}


def flat_order_chapters(abstractions: list, relationships: dict,
                         shared: Dict[str, Any]) -> list:
    """OrderChapters equivalent — plain function."""
    project_name = shared["project_name"]
    use_cache    = shared.get("use_cache", True)
    num_abstr    = len(abstractions)

    listing = "\n".join(f"- {i} # {a['name']}" for i, a in enumerate(abstractions))
    prompt  = (
        f"Order these abstractions for a tutorial on `{project_name}`:\n{listing}\n\n"
        "Output ordered YAML list of indices:\n"
        "```yaml\n- 0 # First\n- 1 # Second\n```"
    )

    with track_execution("flat_order_chapters", node_name="FlatBaseline"):
        response = call_llm(prompt, use_cache=use_cache)

    raw = _parse_yaml_block(response)
    if not isinstance(raw, list):
        return list(range(num_abstr))

    indices, seen = [], set()
    for entry in raw:
        try:
            idx = entry if isinstance(entry, int) else int(str(entry).split("#")[0].strip())
            if 0 <= idx < num_abstr and idx not in seen:
                indices.append(idx)
                seen.add(idx)
        except (ValueError, TypeError):
            pass

    # Fill any missing indices at the end
    for idx in range(num_abstr):
        if idx not in seen:
            indices.append(idx)

    print(f"[FlatBaseline] Chapter order: {indices}")
    return indices


def flat_write_chapters(chapter_order: list, abstractions: list,
                         files_data: list, shared: Dict[str, Any]) -> list:
    """
    WriteChapters equivalent — plain sequential function.
    Accumulates chapters_so_far exactly as the PocketFlow BatchNode does,
    giving an apples-to-apples sync baseline.
    """
    project_name = shared["project_name"]
    use_cache    = shared.get("use_cache", True)
    chapters: List[str] = []
    chapters_so_far: List[str] = []

    for i, abs_idx in enumerate(chapter_order):
        if not (0 <= abs_idx < len(abstractions)):
            continue

        abstr        = abstractions[abs_idx]
        related      = _get_content_for_indices(files_data, abstr.get("files", []))
        file_ctx     = "\n\n".join(f"--- File: {k} ---\n{v}" for k, v in related.items())
        prev_ctx     = "\n---\n".join(chapters_so_far) if chapters_so_far else "First chapter."

        prompt = (
            f"Write beginner-friendly Markdown tutorial chapter {i+1} "
            f"about \"{abstr['name']}\" for `{project_name}`.\n\n"
            f"Previous chapters summary:\n{prev_ctx[:400]}\n\n"
            f"Relevant code:\n{file_ctx[:800]}\n\n"
            "Output ONLY the Markdown content."
        )

        with track_execution(f"flat_write_chapter_{i+1}", node_name="FlatBaseline"):
            content = call_llm(prompt, use_cache=use_cache)

        content = content.strip()
        chapters.append(content)
        chapters_so_far.append(content)
        print(f"[FlatBaseline] Wrote chapter {i+1}/{len(chapter_order)}")

    return chapters


def flat_write_chapters_async(chapter_order: list, abstractions: list,
                               files_data: list, shared: Dict[str, Any],
                               max_workers: int = 4) -> Tuple[list, float]:
    """
    Async WriteChapters baseline — all chapters generated in parallel threads.

    Key difference from sync: chapters run *independently* (no inter-chapter
    context accumulation), exposing the maximum achievable parallelism.
    Returns (chapters_list, wall_clock_seconds).

    This is the async comparison point for RQ1/RQ3 in the research paper.
    """
    project_name = shared["project_name"]
    use_cache    = shared.get("use_cache", True)

    def _write_one(i: int, abs_idx: int) -> Tuple[int, str]:
        if not (0 <= abs_idx < len(abstractions)):
            return i, ""
        abstr    = abstractions[abs_idx]
        related  = _get_content_for_indices(files_data, abstr.get("files", []))
        file_ctx = "\n\n".join(f"--- File: {k} ---\n{v}" for k, v in related.items())

        prompt = (
            f"Write beginner-friendly Markdown tutorial chapter {i+1} "
            f"about \"{abstr['name']}\" for `{project_name}`.\n\n"
            f"Relevant code:\n{file_ctx[:800]}\n\n"
            "Output ONLY the Markdown content."
        )
        with track_execution(f"async_write_chapter_{i+1}", node_name="AsyncWriteChapters"):
            content = call_llm(prompt, use_cache=use_cache)
        print(f"[FlatBaseline-Async] Chapter {i+1} done")
        return i, content.strip()

    start = time.perf_counter()
    results: Dict[int, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_write_one, i, abs_idx): i
            for i, abs_idx in enumerate(chapter_order)
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                idx, content = fut.result()
                results[idx] = content
            except Exception as exc:
                print(f"[FlatBaseline-Async] Chapter error: {exc}")

    elapsed = time.perf_counter() - start
    chapters = [results.get(i, "") for i in range(len(chapter_order))]
    print(f"[FlatBaseline-Async] All {len(chapters)} chapters in {elapsed:.2f}s")
    return chapters, elapsed


def flat_combine_tutorial(chapter_order: list, abstractions: list,
                           chapters: list, shared: Dict[str, Any]) -> str:
    """CombineTutorial equivalent — plain function."""
    project_name = shared["project_name"]
    output_path  = os.path.join(shared.get("output_dir", "output"),
                                project_name + "_flat")

    with track_execution("flat_combine_tutorial", node_name="FlatBaseline"):
        os.makedirs(output_path, exist_ok=True)
        index_lines = [f"# Tutorial: {project_name}\n\n## Chapters\n"]

        for i, abs_idx in enumerate(chapter_order):
            if 0 <= abs_idx < len(abstractions) and i < len(chapters):
                abstr = abstractions[abs_idx]
                safe  = "".join(c if c.isalnum() else "_" for c in abstr["name"]).lower()
                fname = f"{i+1:02d}_{safe}.md"
                index_lines.append(f"{i+1}. [{abstr['name']}]({fname})")
                with open(os.path.join(output_path, fname), "w", encoding="utf-8") as f:
                    f.write(chapters[i])

        with open(os.path.join(output_path, "index.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(index_lines))

    return output_path


# ──────────────────────────────────────────────────────────────────────────────
# Full flat pipeline runner
# ──────────────────────────────────────────────────────────────────────────────

def run_flat_baseline(shared: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """
    Run all 6 steps as plain functions and return
    (total_wall_time_seconds, {step_name: seconds}).
    """
    step_times: Dict[str, float] = {}
    t_pipeline = time.perf_counter()

    def _timed(label: str, fn, *args):
        t0 = time.perf_counter()
        result = fn(*args)
        step_times[label] = time.perf_counter() - t0
        return result

    files         = _timed("FetchRepo",             flat_fetch_repo,             shared)
    abstractions  = _timed("IdentifyAbstractions",  flat_identify_abstractions,  files, shared)
    relationships = _timed("AnalyzeRelationships",  flat_analyze_relationships,  abstractions, files, shared)
    chapter_order = _timed("OrderChapters",         flat_order_chapters,         abstractions, relationships, shared)
    chapters      = _timed("WriteChapters",         flat_write_chapters,         chapter_order, abstractions, files, shared)
    _             = _timed("CombineTutorial",       flat_combine_tutorial,       chapter_order, abstractions, chapters, shared)

    total = time.perf_counter() - t_pipeline
    print(f"\n[FlatBaseline] Completed in {total:.2f}s")
    for k, v in step_times.items():
        print(f"  {k:<30} {v:>8.3f}s  ({v/total*100:>5.1f}%)")

    return total, step_times


# ──────────────────────────────────────────────────────────────────────────────
# Overhead measurement
# ──────────────────────────────────────────────────────────────────────────────

def measure_framework_overhead(
    shared_template:      Dict[str, Any],
    pocketflow_time:      float,
    pocketflow_step_times: Dict[str, float],
) -> Dict[str, Any]:
    """
    Compare flat-baseline time vs PocketFlow time to isolate framework overhead.

    Parameters
    ──────────
    shared_template       : initial `shared` dict (deep-copied before use)
    pocketflow_time       : total wall-clock time from the PocketFlow run
    pocketflow_step_times : per-node wall-clock times from the PocketFlow run
                            keys must match node class names
                            e.g. {"FetchRepo": 3.2, "WriteChapters": 120.0, ...}

    Returns
    ───────
    Overhead report dict, also saved to profiling_reports/overhead_<ts>.json
    and published to the `framework_overhead_seconds` Prometheus metric.

    Interpretation
    ──────────────
    report["total_overhead_pct"] ≈ 2–5 %  → framework is negligible
    report["total_overhead_pct"] ≈ 15 % + → investigate PocketFlow retry/wait logic
    """
    shared_copy = copy.deepcopy(shared_template)
    flat_total, flat_steps = run_flat_baseline(shared_copy)

    report: Dict[str, Any] = {
        "flat_total_sec":        flat_total,
        "pocketflow_total_sec":  pocketflow_time,
        "total_overhead_sec":    pocketflow_time - flat_total,
        "total_overhead_pct":    ((pocketflow_time - flat_total) / flat_total * 100)
                                 if flat_total > 0 else 0.0,
        "steps": {},
    }

    node_names = [
        "FetchRepo", "IdentifyAbstractions", "AnalyzeRelationships",
        "OrderChapters", "WriteChapters", "CombineTutorial",
    ]
    for node in node_names:
        flat_t  = flat_steps.get(node, 0.0)
        pf_t    = pocketflow_step_times.get(node, 0.0)
        delta   = pf_t - flat_t
        pct     = (delta / flat_t * 100) if flat_t > 0 else 0.0
        report["steps"][node] = {
            "flat_sec":       flat_t,
            "pocketflow_sec": pf_t,
            "overhead_sec":   delta,
            "overhead_pct":   pct,
        }

    # Publish to Prometheus
    try:
        from utils.metrics import framework_overhead_seconds
        framework_overhead_seconds.labels(pipeline="pocketflow").observe(
            max(report["total_overhead_sec"], 0.0)
        )
    except Exception as exc:
        print(f"[FlatBaseline] Prometheus metric error: {exc}")

    # Persist report
    os.makedirs("profiling_reports", exist_ok=True)
    out_path = f"profiling_reports/overhead_{int(time.time())}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n[FlatBaseline] Overhead report → {out_path}")
    print(f"  Total overhead: {report['total_overhead_sec']:.3f}s  "
          f"({report['total_overhead_pct']:.1f}%)")
    for node, s in report["steps"].items():
        print(f"  {node:<28} flat={s['flat_sec']:.3f}s  "
              f"pf={s['pocketflow_sec']:.3f}s  "
              f"Δ={s['overhead_sec']:.3f}s ({s['overhead_pct']:.1f}%)")

    return report
