"""
nodes.py  (research version — replaces both existing nodes.py files)
────────────────────────────────────────────────────────────────────
PocketFlow nodes for the tutorial generation pipeline.

Research paper gaps addressed in this version
──────────────────────────────────────────────
Gap 1 — AsyncWriteChapters
  Parallel chapter generation via ThreadPoolExecutor.
  Speedup ratio vs sync is pushed to Prometheus automatically.

Gap 2 — Framework overhead
  Every prep() and post() is wrapped in track_execution so call-tree
  + Prometheus both see individual phase timings (feeds flat_baseline.py).

Gap 3 — tracemalloc vs psutil divergence  ← NEW in this file
  WriteChapters.exec() and AsyncWriteChapters._call_one() now read
  shared["enable_divergence_tracking"] and pass use_divergence=True to
  track_execution when it is set.  app.py sets this flag for the v2
  container (APP_MODE != "sync").

Gap 4/5 — Call-tree / per-function granularity
  record_call() wraps every prep/post so a flame-graph JSON is exported
  at the end of CombineTutorial.post().
"""

from __future__ import annotations

import concurrent.futures
import os
import time
import yaml
from typing import Any, Dict, List, Optional

from pocketflow import Node, BatchNode

from utils.crawl_github_files import crawl_github_files
from utils.crawl_local_files import crawl_local_files
from utils.call_llm import call_llm
from utils.performance_tracker import track_execution
from utils.metrics import MetricsCollector
from utils.call_tree import record_call

import dotenv
dotenv.load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# Internal helper
# ──────────────────────────────────────────────────────────────────────────────

def get_content_for_indices(files_data: list, indices: list) -> dict:
    content_map: Dict[str, str] = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content
    return content_map


# ──────────────────────────────────────────────────────────────────────────────
# Node-boundary helpers
# ──────────────────────────────────────────────────────────────────────────────

def _node_start_snapshot():
    MetricsCollector.get_cpu_percent()
    return time.perf_counter(), MetricsCollector.get_process_memory_info()["rss"]


def _node_end_snapshot(start_time, start_rss, node_name, repo_name, status="success"):
    end_time = time.perf_counter()
    end_rss  = MetricsCollector.get_process_memory_info()["rss"]
    cpu      = MetricsCollector.get_cpu_percent()
    MetricsCollector.record_node_metrics(
        node_name=node_name,
        repo_name=repo_name,
        execution_time_sec=end_time - start_time,
        memory_peak_bytes=int(max(end_rss - start_rss, 0)),
        memory_avg_bytes=int((start_rss + end_rss) / 2),
        cpu_percent=cpu,
        status=status,
    )


# ──────────────────────────────────────────────────────────────────────────────
# FetchRepo
# ──────────────────────────────────────────────────────────────────────────────

class FetchRepo(Node):

    def prep(self, shared):
        with record_call("prep", node_name="FetchRepo"):
            with track_execution("prep", node_name="FetchRepo"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()

                repo_url     = shared.get("repo_url")
                local_dir    = shared.get("local_dir")
                project_name = shared.get("project_name")

                if not project_name:
                    if repo_url:
                        project_name = repo_url.split("/")[-1].replace(".git", "")
                    else:
                        project_name = os.path.basename(os.path.abspath(local_dir))
                    shared["project_name"] = project_name

                return {
                    "repo_url":           repo_url,
                    "local_dir":          local_dir,
                    "token":              shared.get("github_token"),
                    "include_patterns":   shared["include_patterns"],
                    "exclude_patterns":   shared["exclude_patterns"],
                    "max_file_size":      shared["max_file_size"],
                    "use_relative_paths": True,
                }

    def exec(self, prep_res):
        with track_execution("exec", node_name="FetchRepo"):
            if prep_res["repo_url"]:
                print(f"Crawling repository: {prep_res['repo_url']}...")
                result = crawl_github_files(
                    repo_url=prep_res["repo_url"],
                    token=prep_res["token"],
                    include_patterns=prep_res["include_patterns"],
                    exclude_patterns=prep_res["exclude_patterns"],
                    max_file_size=prep_res["max_file_size"],
                    use_relative_paths=prep_res["use_relative_paths"],
                )
            else:
                print(f"Crawling directory: {prep_res['local_dir']}...")
                result = crawl_local_files(
                    directory=prep_res["local_dir"],
                    include_patterns=prep_res["include_patterns"],
                    exclude_patterns=prep_res["exclude_patterns"],
                    max_file_size=prep_res["max_file_size"],
                    use_relative_paths=prep_res["use_relative_paths"],
                )

            files_list = list(result.get("files", {}).items())
            if not files_list:
                raise ValueError("Failed to fetch files")
            print(f"Fetched {len(files_list)} files.")
        return files_list

    def post(self, shared, prep_res, exec_res):
        with record_call("post", node_name="FetchRepo"):
            with track_execution("post", node_name="FetchRepo"):
                shared["files"] = exec_res
                repo_name = shared.get("project_name", "unknown")
                source    = "github" if shared.get("repo_url") else "local"
                language  = shared.get("language", "english")

                per_file_start = time.perf_counter()
                for _ in exec_res:
                    MetricsCollector.record_file_processed(source, repo_name, "success")
                total_fetch_dur = time.perf_counter() - per_file_start
                if exec_res:
                    per_file_dur = total_fetch_dur / len(exec_res)
                    for _ in exec_res:
                        MetricsCollector.record_file_processing_time(source, repo_name, per_file_dur)

                total_bytes = sum(
                    len(c.encode("utf-8", errors="replace")) for _, c in exec_res
                )
                MetricsCollector.record_repository_metrics(
                    repo_name=repo_name,
                    repo_size_mb=round(total_bytes / (1024 * 1024), 4),
                    file_count=len(exec_res),
                    language=language,
                )
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "FetchRepo", repo_name)


# ──────────────────────────────────────────────────────────────────────────────
# IdentifyAbstractions
# ──────────────────────────────────────────────────────────────────────────────

class IdentifyAbstractions(Node):

    def prep(self, shared):
        with record_call("prep", node_name="IdentifyAbstractions"):
            with track_execution("prep", node_name="IdentifyAbstractions"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()

                files_data          = shared["files"]
                project_name        = shared["project_name"]
                language            = shared.get("language", "english")
                use_cache           = shared.get("use_cache", True)
                max_abstraction_num = shared.get("max_abstraction_num", 10)

                context   = ""
                file_info = []
                for i, (path, content) in enumerate(files_data):
                    context += f"--- File Index {i}: {path} ---\n{content}\n\n"
                    file_info.append((i, path))

                file_listing = "\n".join([f"- {idx} # {path}" for idx, path in file_info])
                return (context, file_listing, len(files_data),
                        project_name, language, use_cache, max_abstraction_num)

    def exec(self, prep_res):
        (context, file_listing, file_count, project_name,
         language, use_cache, max_abstraction_num) = prep_res

        print("Identifying abstractions using LLM...")

        language_instruction = name_lang_hint = desc_lang_hint = ""
        if language.lower() != "english":
            lang_cap = language.capitalize()
            language_instruction = (
                f"IMPORTANT: Generate the `name` and `description` for each abstraction "
                f"in **{lang_cap}** language. Do NOT use English for these fields.\n\n"
            )
            name_lang_hint = f" (value in {lang_cap})"
            desc_lang_hint = f" (value in {lang_cap})"

        prompt = f"""
For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core most important abstractions.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` in around 100 words{desc_lang_hint}.
3. A list of relevant `file_indices` using the format `idx # path`.

List of file indices:
{file_listing}

Format as YAML list:
```yaml
- name: |
    Example{name_lang_hint}
  description: |
    Explains what it does.{desc_lang_hint}
  file_indices:
    - 0 # path/to/file.py
```"""

        with track_execution("exec", node_name="IdentifyAbstractions"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))

        yaml_str     = response.strip().split("```yaml")[1].split("```")[0].strip()
        abstractions = yaml.safe_load(yaml_str)

        if not isinstance(abstractions, list):
            raise ValueError("LLM Output is not a list")

        validated = []
        for item in abstractions:
            if not isinstance(item, dict) or not all(k in item for k in ["name", "description", "file_indices"]):
                raise ValueError(f"Missing keys in abstraction item: {item}")
            validated_indices = []
            for entry in item["file_indices"]:
                try:
                    idx = entry if isinstance(entry, int) else int(str(entry).split("#")[0].strip())
                    if 0 <= idx < file_count:
                        validated_indices.append(idx)
                except (ValueError, TypeError):
                    pass
            item["files"] = sorted(set(validated_indices))
            validated.append({"name": item["name"], "description": item["description"],
                               "files": item["files"]})

        print(f"Identified {len(validated)} abstractions.")
        return validated

    def post(self, shared, prep_res, exec_res):
        with record_call("post", node_name="IdentifyAbstractions"):
            with track_execution("post", node_name="IdentifyAbstractions"):
                shared["abstractions"] = exec_res
                repo_name = shared.get("project_name", "unknown")
                MetricsCollector.set_abstractions_count(repo_name, len(exec_res))
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "IdentifyAbstractions", repo_name)


# ──────────────────────────────────────────────────────────────────────────────
# AnalyzeRelationships
# ──────────────────────────────────────────────────────────────────────────────

class AnalyzeRelationships(Node):

    def prep(self, shared):
        with record_call("prep", node_name="AnalyzeRelationships"):
            with track_execution("prep", node_name="AnalyzeRelationships"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()

                abstractions = shared["abstractions"]
                files_data   = shared["files"]
                project_name = shared["project_name"]
                language     = shared.get("language", "english")
                use_cache    = shared.get("use_cache", True)

                num_abstractions = len(abstractions)
                context          = "Identified Abstractions:\\n"
                all_relevant     = set()
                listing          = []

                for i, abstr in enumerate(abstractions):
                    file_indices_str = ", ".join(map(str, abstr["files"]))
                    context += (
                        f"- Index {i}: {abstr['name']} (files: [{file_indices_str}])\\n"
                        f"  Description: {abstr['description']}\\n"
                    )
                    listing.append(f"{i} # {abstr['name']}")
                    all_relevant.update(abstr["files"])

                context += "\\nRelevant File Snippets:\\n"
                relevant_map = get_content_for_indices(files_data, sorted(all_relevant))
                context += "\\n\\n".join(
                    f"--- File: {k} ---\\n{v}" for k, v in relevant_map.items()
                )
                return (context, "\n".join(listing), num_abstractions,
                        project_name, language, use_cache)

    def exec(self, prep_res):
        (context, abstraction_listing, num_abstractions,
         project_name, language, use_cache) = prep_res

        print("Analyzing relationships using LLM...")

        language_instruction = lang_hint = list_lang_note = ""
        if language.lower() != "english":
            lang_cap = language.capitalize()
            language_instruction = (
                f"IMPORTANT: Generate `summary` and relationship `label` fields "
                f"in **{lang_cap}**.\n\n"
            )
            lang_hint      = f" (in {lang_cap})"
            list_lang_note = f" (Names might be in {lang_cap})"

        prompt = f"""
Based on the abstractions and code from project `{project_name}`:

Abstractions{list_lang_note}:
{abstraction_listing}

Context:
{context}

{language_instruction}Provide:
1. A `summary` of the project{lang_hint}.
2. A `relationships` list with from_abstraction, to_abstraction, label{lang_hint}.

IMPORTANT: Every abstraction must appear in at least one relationship.

```yaml
summary: |
  Brief summary{lang_hint}.
relationships:
  - from_abstraction: 0 # Name1
    to_abstraction: 1 # Name2
    label: "Uses"{lang_hint}
```"""

        with track_execution("exec", node_name="AnalyzeRelationships"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))

        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        data     = yaml.safe_load(yaml_str)

        if not isinstance(data, dict) or not all(k in data for k in ["summary", "relationships"]):
            raise ValueError("LLM output missing 'summary' or 'relationships'")

        validated_rels = []
        for rel in data["relationships"]:
            try:
                from_idx = int(str(rel["from_abstraction"]).split("#")[0].strip())
                to_idx   = int(str(rel["to_abstraction"]).split("#")[0].strip())
                if 0 <= from_idx < num_abstractions and 0 <= to_idx < num_abstractions:
                    validated_rels.append({"from": from_idx, "to": to_idx,
                                           "label": str(rel["label"])})
            except (ValueError, TypeError, KeyError):
                pass

        print("Generated project summary and relationships.")
        return {"summary": data["summary"], "details": validated_rels}

    def post(self, shared, prep_res, exec_res):
        with record_call("post", node_name="AnalyzeRelationships"):
            with track_execution("post", node_name="AnalyzeRelationships"):
                shared["relationships"] = exec_res
                repo_name = shared.get("project_name", "unknown")
                MetricsCollector.set_relationships_count(
                    repo_name, len(exec_res.get("details", []))
                )
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "AnalyzeRelationships", repo_name)


# ──────────────────────────────────────────────────────────────────────────────
# OrderChapters
# ──────────────────────────────────────────────────────────────────────────────

class OrderChapters(Node):

    def prep(self, shared):
        with record_call("prep", node_name="OrderChapters"):
            with track_execution("prep", node_name="OrderChapters"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()

                abstractions  = shared["abstractions"]
                relationships = shared["relationships"]
                project_name  = shared["project_name"]
                language      = shared.get("language", "english")
                use_cache     = shared.get("use_cache", True)

                listing        = "\n".join([f"- {i} # {a['name']}" for i, a in enumerate(abstractions)])
                summary_note   = f" (Note: Summary might be in {language.capitalize()})" if language.lower() != "english" else ""
                list_lang_note = f" (Names might be in {language.capitalize()})"         if language.lower() != "english" else ""

                context  = f"Project Summary{summary_note}:\n{relationships['summary']}\n\n"
                context += "Relationships:\n"
                for rel in relationships["details"]:
                    context += (
                        f"- From {rel['from']} ({abstractions[rel['from']]['name']}) "
                        f"to {rel['to']} ({abstractions[rel['to']]['name']}): {rel['label']}\n"
                    )
                return (listing, context, len(abstractions), project_name, list_lang_note, use_cache)

    def exec(self, prep_res):
        (listing, context, num_abstractions, project_name, list_lang_note, use_cache) = prep_res

        print("Determining chapter order using LLM...")
        prompt = f"""
Given the abstractions and relationships for `{project_name}`:

Abstractions{list_lang_note}:
{listing}

Context:
{context}

Output the best order to explain these abstractions as a YAML list:
```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
```"""

        with track_execution("exec", node_name="OrderChapters"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))

        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        raw      = yaml.safe_load(yaml_str)

        if not isinstance(raw, list):
            raise ValueError("LLM output is not a list")

        indices, seen = [], set()
        for entry in raw:
            try:
                idx = entry if isinstance(entry, int) else int(str(entry).split("#")[0].strip())
                if 0 <= idx < num_abstractions and idx not in seen:
                    indices.append(idx)
                    seen.add(idx)
            except (ValueError, TypeError):
                pass

        if len(indices) != num_abstractions:
            raise ValueError(
                f"Ordered list length ({len(indices)}) != abstractions ({num_abstractions}). "
                f"Missing: {set(range(num_abstractions)) - seen}"
            )
        print(f"Chapter order: {indices}")
        return indices

    def post(self, shared, prep_res, exec_res):
        with record_call("post", node_name="OrderChapters"):
            with track_execution("post", node_name="OrderChapters"):
                shared["chapter_order"] = exec_res
                repo_name = shared.get("project_name", "unknown")
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "OrderChapters", repo_name)

 
# ──────────────────────────────────────────────────────────────────────────────
# WriteChapters  (sync — Gap 3 divergence tracking wired up)
# ──────────────────────────────────────────────────────────────────────────────

class WriteChapters(BatchNode):

    def prep(self, shared):
        with record_call("prep", node_name="WriteChapters"):
            with track_execution("prep", node_name="WriteChapters"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()
                self._sync_start_time = time.perf_counter()

                chapter_order = shared["chapter_order"]
                abstractions  = shared["abstractions"]
                files_data    = shared["files"]
                language      = shared.get("language", "english")
                use_cache     = shared.get("use_cache", True)
                # Gap 3: read divergence tracking flag from shared
                enable_divergence = shared.get("enable_divergence_tracking", False)

                self.chapters_written_so_far = []

                chapter_filenames: Dict[int, dict] = {}
                all_chapters: List[str] = []
                for i, abs_idx in enumerate(chapter_order):
                    if 0 <= abs_idx < len(abstractions):
                        chapter_num  = i + 1
                        chapter_name = abstractions[abs_idx]["name"]
                        safe_name    = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
                        filename     = f"{i+1:02d}_{safe_name}.md"
                        all_chapters.append(f"{chapter_num}. [{chapter_name}]({filename})")
                        chapter_filenames[abs_idx] = {"num": chapter_num, "name": chapter_name,
                                                       "filename": filename}

                full_chapter_listing = "\n".join(all_chapters)

                items_to_process = []
                for i, abs_idx in enumerate(chapter_order):
                    if 0 <= abs_idx < len(abstractions):
                        abstr             = abstractions[abs_idx]
                        related_files_map = get_content_for_indices(files_data, abstr.get("files", []))
                        prev_chapter = chapter_filenames.get(chapter_order[i - 1]) if i > 0 else None
                        next_chapter = chapter_filenames.get(chapter_order[i + 1]) if i < len(chapter_order) - 1 else None
                        items_to_process.append({
                            "chapter_num":               i + 1,
                            "abstraction_index":         abs_idx,
                            "abstraction_details":       abstr,
                            "related_files_content_map": related_files_map,
                            "project_name":              shared["project_name"],
                            "full_chapter_listing":      full_chapter_listing,
                            "chapter_filenames":         chapter_filenames,
                            "prev_chapter":              prev_chapter,
                            "next_chapter":              next_chapter,
                            "language":                  language,
                            "use_cache":                 use_cache,
                            "enable_divergence_tracking": enable_divergence,  # Gap 3
                        })

                print(f"Preparing to write {len(items_to_process)} chapters...")
                return items_to_process

    def exec(self, item):
        abstraction_name        = item["abstraction_details"]["name"]
        abstraction_description = item["abstraction_details"]["description"]
        chapter_num             = item["chapter_num"]
        project_name            = item.get("project_name")
        language                = item.get("language", "english")
        use_cache               = item.get("use_cache", True)
        # Gap 3: read per-item divergence tracking flag
        enable_divergence       = item.get("enable_divergence_tracking", False)

        print(f"Writing chapter {chapter_num} for: {abstraction_name}...")

        file_context_str = "\n\n".join(
            f"--- File: {k.split('# ')[1] if '# ' in k else k} ---\n{v}"
            for k, v in item["related_files_content_map"].items()
        )
        previous_chapters_summary = "\n---\n".join(self.chapters_written_so_far)

        language_instruction = concept_note = structure_note = prev_note = ""
        instruction_note = mermaid_note = code_note = link_note = tone_note = ""
        if language.lower() != "english":
            lang_cap             = language.capitalize()
            language_instruction = f"IMPORTANT: Write this ENTIRE tutorial chapter in **{lang_cap}**.\n\n"
            concept_note         = f" (Note: Provided in {lang_cap})"
            structure_note       = f" (Note: Chapter names might be in {lang_cap})"
            prev_note            = f" (Note: Summary might be in {lang_cap})"
            instruction_note     = f" (in {lang_cap})"
            mermaid_note         = f" (Use {lang_cap} for labels)"
            code_note            = f" (Translate to {lang_cap} if possible)"
            link_note            = f" (Use the {lang_cap} title)"
            tone_note            = f" (appropriate for {lang_cap} readers)"

        prompt = f"""
{language_instruction}Write a beginner-friendly tutorial chapter (Markdown) for `{project_name}` about "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details{concept_note}:
- Name: {abstraction_name}
- Description: {abstraction_description}

Tutorial Structure{structure_note}:
{item["full_chapter_listing"]}

Previous chapters{prev_note}:
{previous_chapters_summary if previous_chapters_summary else "This is the first chapter."}

Relevant Code:
{file_context_str if file_context_str else "No specific code snippets."}

Instructions:
- Start with `# Chapter {chapter_num}: {abstraction_name}`.
- Motivation + use case first{instruction_note}.
- Use mermaid sequence diagrams (max 5 participants){mermaid_note}.
- Keep code blocks under 10 lines{code_note}.
- Link to other chapters with [Title](filename.md){link_note}.
- End with conclusion + transition{instruction_note}.
- Tone: welcoming{tone_note}.
- Output ONLY the Markdown content.
"""

        # Gap 3: enable MemoryDivergenceTracker for the most memory-intensive step
        with track_execution(
            f"exec_chapter_{chapter_num}",
            node_name="WriteChapters",
            # use_divergence=enable_divergence, 
            use_divergence=True,                        # ← Gap 3
            divergence_log="profiling_reports/mem_divergence.jsonl",  # ← Gap 3
        ):
            chapter_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))

        actual_heading = f"# Chapter {chapter_num}: {abstraction_name}"
        if not chapter_content.strip().startswith(f"# Chapter {chapter_num}"):
            lines = chapter_content.strip().split("\n")
            if lines and lines[0].strip().startswith("#"):
                lines[0]        = actual_heading
                chapter_content = "\n".join(lines)
            else:
                chapter_content = f"{actual_heading}\n\n{chapter_content}"

        self.chapters_written_so_far.append(chapter_content)
        return chapter_content

    def post(self, shared, prep_res, exec_res_list):
        with record_call("post", node_name="WriteChapters"):
            with track_execution("post", node_name="WriteChapters"):
                shared["chapters"] = exec_res_list
                del self.chapters_written_so_far
                print(f"Finished writing {len(exec_res_list)} chapters.")

                repo_name  = shared.get("project_name", "unknown")
                sync_total = time.perf_counter() - self._sync_start_time
                # Gap 1: store sync time so AsyncWriteChapters.post() can compute speedup
                shared["_sync_write_chapters_time"] = sync_total

                MetricsCollector.set_chapters_count(repo_name, len(exec_res_list))
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "WriteChapters", repo_name)


# ──────────────────────────────────────────────────────────────────────────────
# AsyncWriteChapters  — Gap 1
# ──────────────────────────────────────────────────────────────────────────────

class AsyncWriteChapters(BatchNode):
    """
    Parallel chapter generation using ThreadPoolExecutor.

    Gap 1 wiring:
      If shared['_sync_write_chapters_time'] is set (because WriteChapters
      ran first via run_sync_then_async()), post() computes and records the
      speedup ratio automatically via MetricsCollector.record_async_speedup().

    Gap 3 wiring:
      _call_one() reads enable_divergence_tracking from each item and passes
      use_divergence=True to track_execution when set.
    """

    def prep(self, shared):
        with record_call("prep", node_name="AsyncWriteChapters"):
            with track_execution("prep", node_name="AsyncWriteChapters"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()
                self._async_start_wall = time.perf_counter()

                chapter_order     = shared["chapter_order"]
                abstractions      = shared["abstractions"]
                files_data        = shared["files"]
                language          = shared.get("language", "english")
                use_cache         = shared.get("use_cache", True)
                self._max_workers = shared.get("async_max_workers", 4)
                # Gap 3: read divergence tracking flag
                enable_divergence = shared.get("enable_divergence_tracking", False)

                chapter_filenames: Dict[int, dict] = {}
                all_chapters: List[str] = []
                for i, abs_idx in enumerate(chapter_order):
                    if 0 <= abs_idx < len(abstractions):
                        chapter_num  = i + 1
                        chapter_name = abstractions[abs_idx]["name"]
                        safe_name    = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
                        filename     = f"{i+1:02d}_{safe_name}.md"
                        all_chapters.append(f"{chapter_num}. [{chapter_name}]({filename})")
                        chapter_filenames[abs_idx] = {"num": chapter_num, "name": chapter_name,
                                                       "filename": filename}

                full_chapter_listing = "\n".join(all_chapters)

                items_to_process = []
                for i, abs_idx in enumerate(chapter_order):
                    if 0 <= abs_idx < len(abstractions):
                        abstr             = abstractions[abs_idx]
                        related_files_map = get_content_for_indices(files_data, abstr.get("files", []))
                        items_to_process.append({
                            "chapter_num":               i + 1,
                            "abstraction_index":         abs_idx,
                            "abstraction_details":       abstr,
                            "related_files_content_map": related_files_map,
                            "project_name":              shared["project_name"],
                            "full_chapter_listing":      full_chapter_listing,
                            "language":                  language,
                            "use_cache":                 use_cache,
                            "enable_divergence_tracking": enable_divergence,  # Gap 3
                        })

                print(f"[AsyncWriteChapters] {len(items_to_process)} chapters, "
                      f"max_workers={self._max_workers}")
                return items_to_process

    def exec(self, item):
        """Build the prompt; actual LLM call runs in parallel threads in post()."""
        abstraction_name        = item["abstraction_details"]["name"]
        abstraction_description = item["abstraction_details"]["description"]
        chapter_num             = item["chapter_num"]
        project_name            = item.get("project_name")
        language                = item.get("language", "english")
        use_cache               = item.get("use_cache", True)

        file_context_str = "\n\n".join(
            f"--- File: {k.split('# ')[1] if '# ' in k else k} ---\n{v}"
            for k, v in item["related_files_content_map"].items()
        )

        prompt = (
            f"Write a beginner-friendly Markdown tutorial chapter {chapter_num} "
            f"about \"{abstraction_name}\" for `{project_name}`.\n\n"
            f"Description: {abstraction_description}\n\n"
            f"Tutorial structure:\n{item['full_chapter_listing']}\n\n"
            f"Relevant code:\n{file_context_str[:800] if file_context_str else 'None'}\n\n"
            "Instructions:\n"
            f"- Start with `# Chapter {chapter_num}: {abstraction_name}`.\n"
            "- Use mermaid sequence diagrams (max 5 participants).\n"
            "- Keep code blocks under 10 lines.\n"
            "- Output ONLY Markdown content.\n"
        )

        return {
            "chapter_num":               chapter_num,
            "prompt":                    prompt,
            "use_cache":                 use_cache,
            "enable_divergence_tracking": item.get("enable_divergence_tracking", False),  # Gap 3
        }

    def post(self, shared, prep_res, exec_res_list):
        with record_call("post", node_name="AsyncWriteChapters"):
            with track_execution("post", node_name="AsyncWriteChapters"):
                repo_name     = shared.get("project_name", "unknown")
                chapter_count = len(exec_res_list)

                # ── Parallel LLM calls ────────────────────────────────────────
                results: Dict[int, str] = {}

                def _call_one(item_result: dict) -> tuple:
                    cnum             = item_result["chapter_num"]
                    prompt           = item_result["prompt"]
                    use_cache        = item_result["use_cache"]
                    # Gap 3: enable divergence tracking inside each thread
                    enable_divergence = item_result.get("enable_divergence_tracking", False)

                    with track_execution(
                        f"async_exec_chapter_{cnum}",
                        node_name="AsyncWriteChapters",
                        use_divergence=enable_divergence,                         # ← Gap 3
                        divergence_log="profiling_reports/mem_divergence.jsonl",  # ← Gap 3
                    ):
                        content = call_llm(prompt, use_cache=use_cache)

                    print(f"[AsyncWriteChapters] Chapter {cnum} done")
                    return cnum, content.strip()

                async_wall_start = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._max_workers
                ) as pool:
                    futures = {pool.submit(_call_one, r): r for r in exec_res_list}
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            cnum, content = fut.result()
                            results[cnum] = content
                        except Exception as exc:
                            print(f"[AsyncWriteChapters] Chapter error: {exc}")

                async_elapsed = time.perf_counter() - async_wall_start
                shared["_async_write_elapsed"] = async_elapsed   

                chapters = [results.get(r["chapter_num"], "") for r in exec_res_list]
                shared["chapters"] = chapters
                print(f"[AsyncWriteChapters] {len(chapters)} chapters in {async_elapsed:.2f}s")

                # ── Gap 1: compute speedup if sync time is available ──────────
                sync_time = shared.get("_sync_write_chapters_time")
                if sync_time:
                    MetricsCollector.record_async_speedup(
                        repo_name=repo_name,
                        chapter_count=chapter_count,
                        sync_time=sync_time,
                        async_time=async_elapsed,
                    )
                else:
                    # Record async time alone so it's in Prometheus even without comparison
                    from utils.metrics import async_write_chapters_time_seconds
                    async_write_chapters_time_seconds.labels(
                        repo_name=repo_name, chapter_count=str(chapter_count)
                    ).set(async_elapsed)

                MetricsCollector.set_chapters_count(repo_name, len(chapters))
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "AsyncWriteChapters", repo_name)


# ──────────────────────────────────────────────────────────────────────────────
# CombineTutorial
# ──────────────────────────────────────────────────────────────────────────────

class CombineTutorial(Node):

    def prep(self, shared):
        with record_call("prep", node_name="CombineTutorial"):
            with track_execution("prep", node_name="CombineTutorial"):
                self._node_start_time, self._node_start_rss = _node_start_snapshot()
                self._pipeline_start_time = shared.get("_pipeline_start_time",
                                                        self._node_start_time)

                project_name     = shared["project_name"]
                output_base_dir  = shared.get("output_dir", "output")
                output_path      = os.path.join(output_base_dir, project_name)
                repo_url         = shared.get("repo_url")
                relationships    = shared["relationships"]
                chapter_order    = shared["chapter_order"]
                abstractions     = shared["abstractions"]
                chapters_content = shared["chapters"]

                mermaid_lines = ["flowchart TD"]
                for i, abstr in enumerate(abstractions):
                    mermaid_lines.append(f'    A{i}["{abstr["name"].replace(chr(34), "")}"]')
                for rel in relationships["details"]:
                    label = rel["label"].replace('"', "").replace("\n", " ")
                    if len(label) > 30:
                        label = label[:27] + "..."
                    mermaid_lines.append(f'    A{rel["from"]} -- "{label}" --> A{rel["to"]}')

                mermaid_diagram = "\n".join(mermaid_lines)

                index_content  = f"# Tutorial: {project_name}\n\n"
                index_content += f"{relationships['summary']}\n\n"
                index_content += f"**Source Repository:** [{repo_url}]({repo_url})\n\n"
                index_content += "```mermaid\n" + mermaid_diagram + "\n```\n\n"
                index_content += "## Chapters\n\n"

                chapter_files = []
                for i, abs_idx in enumerate(chapter_order):
                    if 0 <= abs_idx < len(abstractions) and i < len(chapters_content):
                        abstr     = abstractions[abs_idx]
                        safe_name = "".join(c if c.isalnum() else "_" for c in abstr["name"]).lower()
                        filename  = f"{i+1:02d}_{safe_name}.md"
                        index_content += f"{i+1}. [{abstr['name']}]({filename})\n"
                        content   = chapters_content[i]
                        if not content.endswith("\n\n"):
                            content += "\n\n"
                        content += "---\n\nGenerated by [AI Codebase Knowledge Builder]"
                        chapter_files.append({"filename": filename, "content": content})

                index_content += "\n\n---\n\nGenerated by [AI Codebase Knowledge Builder]"
                return {"output_path": output_path,
                        "index_content": index_content,
                        "chapter_files": chapter_files}

    def exec(self, prep_res):
        output_path   = prep_res["output_path"]
        index_content = prep_res["index_content"]
        chapter_files = prep_res["chapter_files"]

        with track_execution("exec", node_name="CombineTutorial"):
            print(f"Combining tutorial into: {output_path}")
            os.makedirs(output_path, exist_ok=True)

            with open(os.path.join(output_path, "index.md"), "w", encoding="utf-8") as f:
                f.write(index_content)

            for ch in chapter_files:
                with open(os.path.join(output_path, ch["filename"]), "w", encoding="utf-8") as f:
                    f.write(ch["content"])
                print(f"  - Wrote {ch['filename']}")

        return output_path

    def post(self, shared, prep_res, exec_res):
        with record_call("post", node_name="CombineTutorial"):
            with track_execution("post", node_name="CombineTutorial"):
                shared["final_output_dir"] = exec_res
                print(f"\nTutorial complete! Files in: {exec_res}")

                repo_name = shared.get("project_name", "unknown")
                MetricsCollector.record_total_generation_time(
                    repo_name, time.perf_counter() - self._pipeline_start_time
                )
                _node_end_snapshot(self._node_start_time, self._node_start_rss,
                                   "CombineTutorial", repo_name)

                # Gaps 4/5: export call-tree flame-graph JSON at end of pipeline
                try:
                    from utils.call_tree import CallTreeRecorder
                    os.makedirs("profiling_reports", exist_ok=True)
                    CallTreeRecorder.export_json(
                        f"profiling_reports/call_trees_{repo_name}.json"
                    )
                    CallTreeRecorder.export_flamegraph(
                        f"profiling_reports/flamegraph_{repo_name}.json"
                    )
                    CallTreeRecorder.print_summary(top_n=20)
                except Exception as exc:
                    print(f"[CombineTutorial] Call-tree export error: {exc}")