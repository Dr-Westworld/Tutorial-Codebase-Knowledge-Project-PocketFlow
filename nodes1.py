
import os
import time  # changed – used only for node-level boundary timestamps
import yaml
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.crawl_local_files import crawl_local_files
from utils.call_llm import call_llm
from utils.performance_tracker import track_execution   # changed – replaces all custom _start_trace / _get_rss helpers
from utils.metrics import MetricsCollector              # changed – domain-specific metric recording
import dotenv
dotenv.load_dotenv()


# Helper to get content for specific file indices
def get_content_for_indices(files_data, indices):
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content
    return content_map


# region Node-boundary helpers
# ─────────────────────────────────────────────────────────────────────────────
# track_execution (from performance_tracker.py) already handles tracemalloc,
# psutil RSS, and CPU sampling inside a single context-manager block — there
# is no reason to duplicate that logic here.
#
# For *node-level* metrics (spanning prep → exec → post) we only need two
# thin wrappers that delegate to the MetricsCollector static methods that
# already wrap psutil safely.
# ─────────────────────────────────────────────────────────────────────────────
def _node_start_snapshot():
    """
    Prime the psutil CPU rolling counter and snapshot current RSS.
    Returns (start_time_sec, start_rss_bytes) to be stored on self.
    """
    MetricsCollector.get_cpu_percent()          # prime so the next read is meaningful
    return time.perf_counter(), MetricsCollector.get_process_memory_info()["rss"]


def _node_end_snapshot(start_time, start_rss, node_name, repo_name, status="success"):
    """
    Compute wall-time, memory delta, and CPU since _node_start_snapshot and
    push everything to Prometheus via MetricsCollector.record_node_metrics.
    """
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
# endregion


class FetchRepo(Node):
    def prep(self, shared):
        # region FetchRepo
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # endregion

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
        # region track_execution handles tracemalloc + psutil + CPU internally
        # and calls MetricsCollector.record_function_metrics on exit; no custom helpers needed
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
        # endregion

        return files_list

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res

        # region file-level, repository, and node-level metrics
        repo_name = shared.get("project_name", "unknown")
        source    = "github" if shared.get("repo_url") else "local"
        language  = shared.get("language", "english")

        # Per-file counters and average processing time
        per_file_start = time.perf_counter()
        for _ in exec_res:
            MetricsCollector.record_file_processed(source, repo_name, "success")
        total_fetch_dur = time.perf_counter() - per_file_start
        if exec_res:
            per_file_dur = total_fetch_dur / len(exec_res)
            for _ in exec_res:
                MetricsCollector.record_file_processing_time(source, repo_name, per_file_dur)

        # Repository metadata gauge
        total_bytes = sum(
            len(content.encode("utf-8", errors="replace")) for _, content in exec_res
        )
        MetricsCollector.record_repository_metrics(
            repo_name=repo_name,
            repo_size_mb=round(total_bytes / (1024 * 1024), 4),
            file_count=len(exec_res),
            language=language,
        )

        _node_end_snapshot(self._node_start_time, self._node_start_rss, "FetchRepo", repo_name)
        # endregion


class IdentifyAbstractions(Node):
    def prep(self, shared):
        # region IdentifyAbstractions
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # endregion

        files_data          = shared["files"]
        project_name        = shared["project_name"]
        language            = shared.get("language", "english")
        use_cache           = shared.get("use_cache", True)
        max_abstraction_num = shared.get("max_abstraction_num", 10)

        def create_llm_context(files_data):
            context   = ""
            file_info = []
            for i, (path, content) in enumerate(files_data):
                context += f"--- File Index {i}: {path} ---\n{content}\n\n"
                file_info.append((i, path))
            return context, file_info

        context, file_info      = create_llm_context(files_data)
        file_listing_for_prompt = "\n".join([f"- {idx} # {path}" for idx, path in file_info])
        return (context, file_listing_for_prompt, len(files_data), project_name, language, use_cache, max_abstraction_num)

    def exec(self, prep_res):
        (context, file_listing_for_prompt, file_count, project_name, language, use_cache, max_abstraction_num) = prep_res

        print("Identifying abstractions using LLM...")

        language_instruction = ""
        name_lang_hint       = ""
        desc_lang_hint       = ""
        if language.lower() != "english":
            language_instruction = (
                f"IMPORTANT: Generate the `name` and `description` for each abstraction "
                f"in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
            )
            name_lang_hint = f" (value in {language.capitalize()})"
            desc_lang_hint = f" (value in {language.capitalize()})"

        prompt = f"""
For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core most important abstractions to help those new to the codebase.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` explaining what it is with a simple analogy, in around 100 words{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Query Processing{name_lang_hint}
  description: |
    Explains what the abstraction does.
    It's like a central dispatcher routing requests.{desc_lang_hint}
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
- name: |
    Query Optimization{name_lang_hint}
  description: |
    Another core concept, similar to a blueprint for objects.{desc_lang_hint}
  file_indices:
    - 5 # path/to/another.js
# ... up to {max_abstraction_num} abstractions
```"""

        # region track_execution handles all function-level instrumentation
        with track_execution("exec", node_name="IdentifyAbstractions"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        # endregion

        yaml_str     = response.strip().split("```yaml")[1].split("```")[0].strip()
        abstractions = yaml.safe_load(yaml_str)

        if not isinstance(abstractions, list):
            raise ValueError("LLM Output is not a list")

        validated_abstractions = []
        for item in abstractions:
            if not isinstance(item, dict) or not all(k in item for k in ["name", "description", "file_indices"]):
                raise ValueError(f"Missing keys in abstraction item: {item}")
            if not isinstance(item["name"], str):
                raise ValueError(f"Name is not a string in item: {item}")
            if not isinstance(item["description"], str):
                raise ValueError(f"Description is not a string in item: {item}")
            if not isinstance(item["file_indices"], list):
                raise ValueError(f"file_indices is not a list in item: {item}")

            validated_indices = []
            for idx_entry in item["file_indices"]:
                try:
                    if isinstance(idx_entry, int):
                        idx = idx_entry
                    elif isinstance(idx_entry, str) and "#" in idx_entry:
                        idx = int(idx_entry.split("#")[0].strip())
                    else:
                        idx = int(str(idx_entry).strip())
                    if not (0 <= idx < file_count):
                        raise ValueError(f"Invalid file index {idx} found in item {item['name']}. Max index is {file_count - 1}.")
                    validated_indices.append(idx)
                except (ValueError, TypeError):
                    raise ValueError(f"Could not parse index from entry: {idx_entry} in item {item['name']}")

            item["files"] = sorted(list(set(validated_indices)))
            validated_abstractions.append({"name": item["name"], "description": item["description"], "files": item["files"]})

        print(f"Identified {len(validated_abstractions)} abstractions.")
        return validated_abstractions

    def post(self, shared, prep_res, exec_res):
        shared["abstractions"] = exec_res

        # region abstraction count + node boundary metrics
        repo_name = shared.get("project_name", "unknown")
        MetricsCollector.set_abstractions_count(repo_name, len(exec_res))
        _node_end_snapshot(self._node_start_time, self._node_start_rss, "IdentifyAbstractions", repo_name)
        # endregion


class AnalyzeRelationships(Node):
    def prep(self, shared):
        # region AnalyzeRelationships
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # endregion

        abstractions = shared["abstractions"]
        files_data   = shared["files"]
        project_name = shared["project_name"]
        language     = shared.get("language", "english")
        use_cache    = shared.get("use_cache", True)

        num_abstractions            = len(abstractions)
        context                     = "Identified Abstractions:\\n"
        all_relevant_indices        = set()
        abstraction_info_for_prompt = []

        for i, abstr in enumerate(abstractions):
            file_indices_str = ", ".join(map(str, abstr["files"]))
            context += (
                f"- Index {i}: {abstr['name']} (Relevant file indices: [{file_indices_str}])\\n"
                f"  Description: {abstr['description']}\\n"
            )
            abstraction_info_for_prompt.append(f"{i} # {abstr['name']}")
            all_relevant_indices.update(abstr["files"])

        context += "\\nRelevant File Snippets (Referenced by Index and Path):\\n"
        relevant_files_content_map = get_content_for_indices(files_data, sorted(list(all_relevant_indices)))
        context += "\\n\\n".join(
            f"--- File: {idx_path} ---\\n{content}"
            for idx_path, content in relevant_files_content_map.items()
        )

        return (context, "\n".join(abstraction_info_for_prompt), num_abstractions, project_name, language, use_cache)

    def exec(self, prep_res):
        (context, abstraction_listing, num_abstractions, project_name, language, use_cache) = prep_res

        print("Analyzing relationships using LLM...")

        language_instruction = ""
        lang_hint            = ""
        list_lang_note       = ""
        if language.lower() != "english":
            lang_cap             = language.capitalize()
            language_instruction = (
                f"IMPORTANT: Generate the `summary` and relationship `label` fields "
                f"in **{lang_cap}** language. Do NOT use English for these fields.\n\n"
            )
            lang_hint      = f" (in {lang_cap})"
            list_lang_note = f" (Names might be in {lang_cap})"

        prompt = f"""
Based on the following abstractions and relevant code snippets from the project `{project_name}`:

List of Abstraction Indices and Names{list_lang_note}:
{abstraction_listing}

Context (Abstractions, Descriptions, Code):
{context}

{language_instruction}Please provide:
1. A high-level `summary` of the project's main purpose and functionality in a few beginner-friendly sentences{lang_hint}. Use markdown formatting with **bold** and *italic* text to highlight important concepts.
2. A list (`relationships`) describing the key interactions between these abstractions. For each relationship, specify:
    - `from_abstraction`: Index of the source abstraction (e.g., `0 # AbstractionName1`)
    - `to_abstraction`: Index of the target abstraction (e.g., `1 # AbstractionName2`)
    - `label`: A brief label for the interaction **in just a few words**{lang_hint} (e.g., "Manages", "Inherits", "Uses").
    Ideally the relationship should be backed by one abstraction calling or passing parameters to another.
    Simplify the relationship and exclude those non-important ones.

IMPORTANT: Make sure EVERY abstraction is involved in at least ONE relationship (either as source or target). Each abstraction index must appear at least once across all relationships.

Format the output as YAML:

```yaml
summary: |
  A brief, simple explanation of the project{lang_hint}.
  Can span multiple lines with **bold** and *italic* for emphasis.
relationships:
  - from_abstraction: 0 # AbstractionName1
    to_abstraction: 1 # AbstractionName2
    label: "Manages"{lang_hint}
  - from_abstraction: 2 # AbstractionName3
    to_abstraction: 0 # AbstractionName1
    label: "Provides config"{lang_hint}
  # ... other relationships
```

Now, provide the YAML output:
"""
        # region track_execution handles all function-level instrumentation
        with track_execution("exec", node_name="AnalyzeRelationships"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        # endregion

        yaml_str           = response.strip().split("```yaml")[1].split("```")[0].strip()
        relationships_data = yaml.safe_load(yaml_str)

        if not isinstance(relationships_data, dict) or not all(k in relationships_data for k in ["summary", "relationships"]):
            raise ValueError("LLM output is not a dict or missing keys ('summary', 'relationships')")
        if not isinstance(relationships_data["summary"], str):
            raise ValueError("summary is not a string")
        if not isinstance(relationships_data["relationships"], list):
            raise ValueError("relationships is not a list")

        validated_relationships = []
        for rel in relationships_data["relationships"]:
            if not isinstance(rel, dict) or not all(k in rel for k in ["from_abstraction", "to_abstraction", "label"]):
                raise ValueError(f"Missing keys (expected from_abstraction, to_abstraction, label) in relationship item: {rel}")
            if not isinstance(rel["label"], str):
                raise ValueError(f"Relationship label is not a string: {rel}")
            try:
                from_idx = int(str(rel["from_abstraction"]).split("#")[0].strip())
                to_idx   = int(str(rel["to_abstraction"]).split("#")[0].strip())
                if not (0 <= from_idx < num_abstractions and 0 <= to_idx < num_abstractions):
                    raise ValueError(f"Invalid index in relationship: from={from_idx}, to={to_idx}. Max index is {num_abstractions - 1}.")
                validated_relationships.append({"from": from_idx, "to": to_idx, "label": rel["label"]})
            except (ValueError, TypeError):
                raise ValueError(f"Could not parse indices from relationship: {rel}")

        print("Generated project summary and relationship details.")
        return {"summary": relationships_data["summary"], "details": validated_relationships}

    def post(self, shared, prep_res, exec_res):
        shared["relationships"] = exec_res

        # region relationship count + node boundary metrics
        repo_name = shared.get("project_name", "unknown")
        MetricsCollector.set_relationships_count(repo_name, len(exec_res.get("details", [])))
        _node_end_snapshot(self._node_start_time, self._node_start_rss, "AnalyzeRelationships", repo_name)
        # endregion


class OrderChapters(Node):
    def prep(self, shared):
        # region OrderChapters
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # endregion

        abstractions  = shared["abstractions"]
        relationships = shared["relationships"]
        project_name  = shared["project_name"]
        language      = shared.get("language", "english")
        use_cache     = shared.get("use_cache", True)

        abstraction_listing = "\n".join([f"- {i} # {a['name']}" for i, a in enumerate(abstractions)])

        summary_note   = f" (Note: Project Summary might be in {language.capitalize()})" if language.lower() != "english" else ""
        list_lang_note = f" (Names might be in {language.capitalize()})"                 if language.lower() != "english" else ""

        context  = f"Project Summary{summary_note}:\n{relationships['summary']}\n\n"
        context += "Relationships (Indices refer to abstractions above):\n"
        for rel in relationships["details"]:
            context += f"- From {rel['from']} ({abstractions[rel['from']]['name']}) to {rel['to']} ({abstractions[rel['to']]['name']}): {rel['label']}\n"

        return (abstraction_listing, context, len(abstractions), project_name, list_lang_note, use_cache)

    def exec(self, prep_res):
        (abstraction_listing, context, num_abstractions, project_name, list_lang_note, use_cache) = prep_res

        print("Determining chapter order using LLM...")

        prompt = f"""
Given the following project abstractions and their relationships for the project ```` {project_name} ````:

Abstractions (Index # Name){list_lang_note}:
{abstraction_listing}

Context about relationships and project summary:
{context}

If you are going to make a tutorial for ```` {project_name} ````, what is the best order to explain these abstractions, from first to last?
Ideally, first explain those that are the most important or foundational, perhaps user-facing concepts or entry points. Then move to more detailed, lower-level implementation details or supporting concepts.

Output the ordered list of abstraction indices, including the name in a comment for clarity. Use the format `idx # AbstractionName`.

```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
- 1 # CoreClassB (uses CoreClassA)
- ...
```

Now, provide the YAML output:
"""
        # region track_execution handles all function-level instrumentation
        with track_execution("exec", node_name="OrderChapters"):
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        # endregion

        yaml_str            = response.strip().split("```yaml")[1].split("```")[0].strip()
        ordered_indices_raw = yaml.safe_load(yaml_str)

        if not isinstance(ordered_indices_raw, list):
            raise ValueError("LLM output is not a list")

        ordered_indices = []
        seen_indices    = set()
        for entry in ordered_indices_raw:
            try:
                if isinstance(entry, int):
                    idx = entry
                elif isinstance(entry, str) and "#" in entry:
                    idx = int(entry.split("#")[0].strip())
                else:
                    idx = int(str(entry).strip())
                if not (0 <= idx < num_abstractions):
                    raise ValueError(f"Invalid index {idx} in ordered list. Max index is {num_abstractions - 1}.")
                if idx in seen_indices:
                    raise ValueError(f"Duplicate index {idx} found in ordered list.")
                ordered_indices.append(idx)
                seen_indices.add(idx)
            except (ValueError, TypeError):
                raise ValueError(f"Could not parse index from ordered list entry: {entry}")

        if len(ordered_indices) != num_abstractions:
            raise ValueError(
                f"Ordered list length ({len(ordered_indices)}) does not match number of abstractions ({num_abstractions}). "
                f"Missing indices: {set(range(num_abstractions)) - seen_indices}"
            )

        print(f"Determined chapter order (indices): {ordered_indices}")
        return ordered_indices

    def post(self, shared, prep_res, exec_res):
        shared["chapter_order"] = exec_res

        # region node boundary metrics for OrderChapters
        repo_name = shared.get("project_name", "unknown")
        _node_end_snapshot(self._node_start_time, self._node_start_rss, "OrderChapters", repo_name)
        # endregion


class WriteChapters(BatchNode):
    def prep(self, shared):
        # region WriteChapters
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # endregion

        chapter_order = shared["chapter_order"]
        abstractions  = shared["abstractions"]
        files_data    = shared["files"]
        language      = shared.get("language", "english")
        use_cache     = shared.get("use_cache", True)

        self.chapters_written_so_far = []

        chapter_filenames = {}
        all_chapters      = []
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                chapter_num  = i + 1
                chapter_name = abstractions[abstraction_index]["name"]
                safe_name    = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
                filename     = f"{i+1:02d}_{safe_name}.md"
                all_chapters.append(f"{chapter_num}. [{chapter_name}]({filename})")
                chapter_filenames[abstraction_index] = {"num": chapter_num, "name": chapter_name, "filename": filename}

        full_chapter_listing = "\n".join(all_chapters)

        items_to_process = []
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                abstraction_details       = abstractions[abstraction_index]
                related_files_content_map = get_content_for_indices(files_data, abstraction_details.get("files", []))
                prev_chapter = chapter_filenames[chapter_order[i - 1]] if i > 0 else None
                next_chapter = chapter_filenames[chapter_order[i + 1]] if i < len(chapter_order) - 1 else None
                items_to_process.append({
                    "chapter_num":               i + 1,
                    "abstraction_index":         abstraction_index,
                    "abstraction_details":       abstraction_details,
                    "related_files_content_map": related_files_content_map,
                    "project_name":              shared["project_name"],
                    "full_chapter_listing":      full_chapter_listing,
                    "chapter_filenames":         chapter_filenames,
                    "prev_chapter":              prev_chapter,
                    "next_chapter":              next_chapter,
                    "language":                  language,
                    "use_cache":                 use_cache,
                })
            else:
                print(f"Warning: Invalid abstraction index {abstraction_index} in chapter_order. Skipping.")

        print(f"Preparing to write {len(items_to_process)} chapters...")
        return items_to_process

    def exec(self, item):
        abstraction_name        = item["abstraction_details"]["name"]
        abstraction_description = item["abstraction_details"]["description"]
        chapter_num             = item["chapter_num"]
        project_name            = item.get("project_name")
        language                = item.get("language", "english")
        use_cache               = item.get("use_cache", True)

        print(f"Writing chapter {chapter_num} for: {abstraction_name} using LLM...")

        file_context_str          = "\n\n".join(
            f"--- File: {idx_path.split('# ')[1] if '# ' in idx_path else idx_path} ---\n{content}"
            for idx_path, content in item["related_files_content_map"].items()
        )
        previous_chapters_summary = "\n---\n".join(self.chapters_written_so_far)

        language_instruction  = ""
        concept_details_note  = ""
        structure_note        = ""
        prev_summary_note     = ""
        instruction_lang_note = ""
        mermaid_lang_note     = ""
        code_comment_note     = ""
        link_lang_note        = ""
        tone_note             = ""
        if language.lower() != "english":
            lang_cap              = language.capitalize()
            language_instruction  = (
                f"IMPORTANT: Write this ENTIRE tutorial chapter in **{lang_cap}**. "
                f"Some input context (like concept name, description, chapter list, previous summary) "
                f"might already be in {lang_cap}, but you MUST translate ALL other generated content "
                f"including explanations, examples, technical terms, and potentially code comments "
                f"into {lang_cap}. DO NOT use English anywhere except in code syntax, required proper "
                f"nouns, or when specified. The entire output MUST be in {lang_cap}.\n\n"
            )
            concept_details_note  = f" (Note: Provided in {lang_cap})"
            structure_note        = f" (Note: Chapter names might be in {lang_cap})"
            prev_summary_note     = f" (Note: This summary might be in {lang_cap})"
            instruction_lang_note = f" (in {lang_cap})"
            mermaid_lang_note     = f" (Use {lang_cap} for labels/text if appropriate)"
            code_comment_note     = f" (Translate to {lang_cap} if possible, otherwise keep minimal English for clarity)"
            link_lang_note        = f" (Use the {lang_cap} chapter title from the structure above)"
            tone_note             = f" (appropriate for {lang_cap} readers)"

        prompt = f"""
{language_instruction}Write a very beginner-friendly tutorial chapter (in Markdown format) for the project `{project_name}` about the concept: "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Tutorial Structure{structure_note}:
{item["full_chapter_listing"]}

Context from previous chapters{prev_summary_note}:
{previous_chapters_summary if previous_chapters_summary else "This is the first chapter."}

Relevant Code Snippets (Code itself remains unchanged):
{file_context_str if file_context_str else "No specific code snippets provided for this abstraction."}

Instructions for the chapter (Generate content in {language.capitalize()} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided concept name.
- If this is not the first chapter, begin with a brief transition from the previous chapter{instruction_lang_note}, referencing it with a proper Markdown link using its name{link_lang_note}.
- Begin with a high-level motivation explaining what problem this abstraction solves{instruction_lang_note}. Start with a central use case as a concrete example. The whole chapter should guide the reader to understand how to solve this use case. Make it very minimal and friendly to beginners.
- If the abstraction is complex, break it down into key concepts. Explain each concept one-by-one in a very beginner-friendly way{instruction_lang_note}.
- Explain how to use this abstraction to solve the use case{instruction_lang_note}. Give example inputs and outputs for code snippets (if the output isn't values, describe at a high level what will happen{instruction_lang_note}).
- Each code block should be BELOW 10 lines! If longer code blocks are needed, break them down into smaller pieces and walk through them one-by-one. Aggresively simplify the code to make it minimal. Use comments{code_comment_note} to skip non-important implementation details. Each code block should have a beginner friendly explanation right after it{instruction_lang_note}.
- Describe the internal implementation to help understand what's under the hood{instruction_lang_note}. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called{instruction_lang_note}. It's recommended to use a simple sequenceDiagram with a dummy example - keep it minimal with at most 5 participants to ensure clarity. If participant name has space, use: `participant QP as Query Processing`. {mermaid_lang_note}.
- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but make them similarly simple and beginner-friendly. Explain{instruction_lang_note}.
- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Tutorial Structure above to find the correct filename and the chapter title{link_lang_note}. Translate the surrounding text.
- Use mermaid diagrams to illustrate complex concepts (```mermaid``` format). {mermaid_lang_note}.
- Heavily use analogies and examples throughout{instruction_lang_note} to help beginners understand.
- End the chapter with a brief conclusion that summarizes what was learned{instruction_lang_note} and provides a transition to the next chapter{instruction_lang_note}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){link_lang_note}.
- Ensure the tone is welcoming and easy for a newcomer to understand{tone_note}.
- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):
"""
        # region unique per-chapter label so Prometheus surfaces individual
        # chapter durations in the function_execution_time_seconds histogram
        with track_execution(f"exec_chapter_{chapter_num}", node_name="WriteChapters"):
            chapter_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        # endregion

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
        shared["chapters"] = exec_res_list
        del self.chapters_written_so_far
        print(f"Finished writing {len(exec_res_list)} chapters.")

        # region chapter count + node boundary metrics
        repo_name = shared.get("project_name", "unknown")
        MetricsCollector.set_chapters_count(repo_name, len(exec_res_list))
        _node_end_snapshot(self._node_start_time, self._node_start_rss, "WriteChapters", repo_name)
        # endregion


class CombineTutorial(Node):
    def prep(self, shared):
        # region CombineTutorial 
        # capture node boundary start; read pipeline start injected by app.py
        self._node_start_time, self._node_start_rss = _node_start_snapshot()
        # app.py sets shared["_pipeline_start_time"] = time.perf_counter() before flow.run()
        # so total_tutorial_generation_time_seconds reflects the full end-to-end wall time.
        # Falls back to this node's start for isolated test runs.
        self._pipeline_start_time = shared.get("_pipeline_start_time", self._node_start_time)
        # endregion

        project_name       = shared["project_name"]
        output_base_dir    = shared.get("output_dir", "output")
        output_path        = os.path.join(output_base_dir, project_name)
        repo_url           = shared.get("repo_url")
        relationships_data = shared["relationships"]
        chapter_order      = shared["chapter_order"]
        abstractions       = shared["abstractions"]
        chapters_content   = shared["chapters"]

        mermaid_lines = ["flowchart TD"]
        for i, abstr in enumerate(abstractions):
            mermaid_lines.append(f'    A{i}["{abstr["name"].replace(chr(34), "")}"]')
        for rel in relationships_data["details"]:
            edge_label = rel["label"].replace('"', "").replace("\n", " ")
            if len(edge_label) > 30:
                edge_label = edge_label[:27] + "..."
            mermaid_lines.append(f'    A{rel["from"]} -- "{edge_label}" --> A{rel["to"]}')

        mermaid_diagram = "\n".join(mermaid_lines)

        index_content  = f"# Tutorial: {project_name}\n\n"
        index_content += f"{relationships_data['summary']}\n\n"
        index_content += f"**Source Repository:** [{repo_url}]({repo_url})\n\n"
        index_content += "```mermaid\n" + mermaid_diagram + "\n```\n\n"
        index_content += "## Chapters\n\n"

        chapter_files = []
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions) and i < len(chapters_content):
                abstraction_name = abstractions[abstraction_index]["name"]
                safe_name        = "".join(c if c.isalnum() else "_" for c in abstraction_name).lower()
                filename         = f"{i+1:02d}_{safe_name}.md"
                index_content   += f"{i+1}. [{abstraction_name}]({filename})\n"

                chapter_content  = chapters_content[i]
                if not chapter_content.endswith("\n\n"):
                    chapter_content += "\n\n"
                chapter_content += "---\n\nGenerated by [AI Codebase Knowledge Builder]"
                chapter_files.append({"filename": filename, "content": chapter_content})
            else:
                print(
                    f"Warning: Mismatch between chapter order, abstractions, or content "
                    f"at index {i} (abstraction index {abstraction_index}). Skipping file generation for this entry."
                )

        index_content += "\n\n---\n\nGenerated by [AI Codebase Knowledge Builder]"

        return {"output_path": output_path, "index_content": index_content, "chapter_files": chapter_files}

    def exec(self, prep_res):
        output_path   = prep_res["output_path"]
        index_content = prep_res["index_content"]
        chapter_files = prep_res["chapter_files"]

        # region track_execution instruments the file I/O block
        with track_execution("exec", node_name="CombineTutorial"):
            print(f"Combining tutorial into directory: {output_path}")
            os.makedirs(output_path, exist_ok=True)

            index_filepath = os.path.join(output_path, "index.md")
            with open(index_filepath, "w", encoding="utf-8") as f:
                f.write(index_content)
            print(f"  - Wrote {index_filepath}")

            for chapter_info in chapter_files:
                chapter_filepath = os.path.join(output_path, chapter_info["filename"])
                with open(chapter_filepath, "w", encoding="utf-8") as f:
                    f.write(chapter_info["content"])
                print(f"  - Wrote {chapter_filepath}")
        # endregion

        return output_path

    def post(self, shared, prep_res, exec_res):
        shared["final_output_dir"] = exec_res
        print(f"\nTutorial generation complete! Files are in: {exec_res}")

        # region xtotal pipeline wall-time + final node boundary metrics
        repo_name = shared.get("project_name", "unknown")
        MetricsCollector.record_total_generation_time(
            repo_name, time.perf_counter() - self._pipeline_start_time
        )
        _node_end_snapshot(self._node_start_time, self._node_start_rss, "CombineTutorial", repo_name)
        # endregion
        