// tutorial_nodes.rs
//
// Rust conversion of nodes.py — Tutorial generation pipeline.
// Each Python Node (prep / exec / post) maps to the pocketflow_rs
// Node trait (prepare / execute / post_process).
//
// Pattern used throughout:
//   prepare()      – reads shared Context, stores computed prep data
//                    back into Context under a "__prep_<NodeName>" key.
//   execute()      – reads the "__prep_*" key, calls LLM / IO, returns Value.
//   post_process() – stores exec result into Context under final keys,
//                    mirrors what Python's post() did to `shared`.

use pocketflow_rs::{Context, Node, ProcessResult, ProcessState};

use anyhow::{anyhow, Result};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use tracing::info;

// ─────────────────────────────────────────────
// External call_llm (mirrors `from rust_tools import call_llm`)
// ─────────────────────────────────────────────
extern "Rust" {
    // Provided by the rust_tools crate / module already in scope.
    // Signature mirrors the Python call:  call_llm(prompt, use_cache=True)
    fn call_llm(prompt: &str, use_cache: bool) -> Result<String>;
}

// ─────────────────────────────────────────────
// Shared pipeline State
// (single state is fine; flow is strictly linear)
// ─────────────────────────────────────────────
#[derive(Debug, Clone, PartialEq, Default)]
pub enum TutorialState {
    #[default]
    Default,
}

impl ProcessState for TutorialState {
    fn is_default(&self) -> bool {
        true
    }
    fn to_condition(&self) -> String {
        "default".to_string()
    }
}

// ─────────────────────────────────────────────
// Helper: mirrors Python get_content_for_indices()
// files_data: JSON array of [path, content] pairs stored in Context
// ─────────────────────────────────────────────
fn get_content_for_indices(
    files_data: &[(String, String)],
    indices: &[usize],
) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for &i in indices {
        if i < files_data.len() {
            let (path, content) = &files_data[i];
            // Key format mirrors Python:  "i # path"
            map.insert(format!("{} # {}", i, path), content.clone());
        }
    }
    map
}

// Deserialise the "files" value stored in Context into a Vec of (path, content).
fn files_from_context(context: &Context) -> Result<Vec<(String, String)>> {
    let raw = context
        .get("files")
        .ok_or_else(|| anyhow!("'files' not found in context"))?;
    let pairs: Vec<(String, String)> = serde_json::from_value(raw.clone())?;
    Ok(pairs)
}

// ─────────────────────────────────────────────
// Retry helper: mirrors Python Node(max_retries=5, wait=20)
// ─────────────────────────────────────────────
async fn call_llm_with_retry(
    prompt: &str,
    use_cache_flag: bool,
    max_retries: u32,
    wait_secs: u64,
) -> Result<String> {
    let mut last_err = anyhow!("LLM call failed");
    for attempt in 0..max_retries {
        // Use cache only on the first attempt (mirrors `self.cur_retry == 0`)
        let use_cache = use_cache_flag && attempt == 0;
        match unsafe { call_llm(prompt, use_cache) } {
            Ok(resp) => return Ok(resp),
            Err(e) => {
                last_err = e;
                if attempt < max_retries - 1 {
                    tokio::time::sleep(std::time::Duration::from_secs(wait_secs)).await;
                }
            }
        }
    }
    Err(last_err)
}

// ═══════════════════════════════════════════════════════════════════
// 1. FetchRepo
//    Python: reads repo_url / local_dir from shared, calls crawl_*,
//            stores file list in shared["files"].
// ═══════════════════════════════════════════════════════════════════
pub struct FetchRepo;

#[async_trait]
impl Node for FetchRepo {
    type State = TutorialState;

    // prepare() — mirrors Python prep():
    //   derives project_name if absent, assembles crawl config,
    //   persists project_name early so downstream nodes can read it.
    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let repo_url = context
            .get("repo_url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let local_dir = context
            .get("local_dir")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        // Derive project_name if not already set (mirrors Python logic)
        if context.get("project_name").is_none() {
            let project_name = if let Some(ref url) = repo_url {
                url.split('/').last().unwrap_or("project").replace(".git", "")
            } else if let Some(ref dir) = local_dir {
                Path::new(dir)
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("project")
                    .to_string()
            } else {
                "project".to_string()
            };
            context.set("project_name", json!(project_name));
        }

        // Store crawl config under a prep key for execute() to read.
        let prep = json!({
            "repo_url": repo_url,
            "local_dir": local_dir,
            "token": context.get("github_token"),
            "include_patterns": context.get("include_patterns").cloned().unwrap_or(json!([])),
            "exclude_patterns": context.get("exclude_patterns").cloned().unwrap_or(json!([])),
            "max_file_size": context.get("max_file_size").cloned().unwrap_or(json!(100_000)),
            "use_relative_paths": true,
        });
        context.set("__prep_FetchRepo", prep);
        Ok(())
    }

    // execute() — mirrors Python exec():
    //   calls crawl_github_files or crawl_local_files,
    //   returns [(path, content)] as JSON.
    async fn execute(&self, context: &Context) -> Result<Value> {
        let prep = context
            .get("__prep_FetchRepo")
            .cloned()
            .ok_or_else(|| anyhow!("FetchRepo prep data missing"))?;

        let repo_url = prep["repo_url"].as_str().map(|s| s.to_string());
        let local_dir = prep["local_dir"].as_str().map(|s| s.to_string());

        let files_list: Vec<(String, String)> = if let Some(url) = repo_url {
            info!("Crawling repository: {}...", url);
            // crawl_github_files is provided by rust_tools; call it here.
            // Placeholder — replace with actual FFI / async call:
            return Err(anyhow!(
                "crawl_github_files not yet wired up in Rust. \
                 Implement via rust_tools::crawl_github_files(url, token, ...)."
            ));
        } else if let Some(dir) = local_dir {
            info!("Crawling directory: {}...", dir);
            // crawl_local_files also lives in rust_tools.
            // Placeholder — replace with actual call:
            return Err(anyhow!(
                "crawl_local_files not yet wired up in Rust. \
                 Implement via rust_tools::crawl_local_files(dir, ...)."
            ));
        } else {
            return Err(anyhow!("Either repo_url or local_dir must be provided"));
        };

        if files_list.is_empty() {
            return Err(anyhow!("Failed to fetch files"));
        }
        info!("Fetched {} files.", files_list.len());

        // Serialise as JSON array of [path, content] pairs
        Ok(json!(files_list))
    }

    // post_process() — mirrors Python post():
    //   stores exec result into shared["files"].
    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(files_json) => {
                context.set("files", files_json.clone());
                context.remove("__prep_FetchRepo");
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 2. IdentifyAbstractions
//    Python: builds LLM prompt from all file content, parses YAML,
//            stores validated abstraction list in shared["abstractions"].
// ═══════════════════════════════════════════════════════════════════
pub struct IdentifyAbstractions {
    pub max_retries: u32,
    pub wait_secs: u64,
}

impl Default for IdentifyAbstractions {
    fn default() -> Self {
        Self { max_retries: 5, wait_secs: 20 }
    }
}

#[async_trait]
impl Node for IdentifyAbstractions {
    type State = TutorialState;

    // prepare() — mirrors Python prep():
    //   builds the full LLM context string and file listing from files_data.
    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let files_data = files_from_context(context)?;
        let project_name = context
            .get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("project")
            .to_string();
        let language = context
            .get("language")
            .and_then(|v| v.as_str())
            .unwrap_or("english")
            .to_string();
        let use_cache = context
            .get("use_cache")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);
        let max_abstraction_num = context
            .get("max_abstraction_num")
            .and_then(|v| v.as_u64())
            .unwrap_or(10) as usize;

        // Build LLM context string + file listing (mirrors create_llm_context)
        let mut llm_context = String::new();
        let mut file_listing_parts: Vec<String> = Vec::new();
        for (i, (path, content)) in files_data.iter().enumerate() {
            llm_context.push_str(&format!(
                "--- File Index {}: {} ---\n{}\n\n",
                i, path, content
            ));
            file_listing_parts.push(format!("- {} # {}", i, path));
        }
        let file_listing_for_prompt = file_listing_parts.join("\n");

        context.set(
            "__prep_IdentifyAbstractions",
            json!({
                "llm_context": llm_context,
                "file_listing_for_prompt": file_listing_for_prompt,
                "file_count": files_data.len(),
                "project_name": project_name,
                "language": language,
                "use_cache": use_cache,
                "max_abstraction_num": max_abstraction_num,
            }),
        );
        Ok(())
    }

    // execute() — mirrors Python exec():
    //   builds prompt, calls LLM with retry, parses + validates YAML.
    async fn execute(&self, context: &Context) -> Result<Value> {
        let prep = context
            .get("__prep_IdentifyAbstractions")
            .cloned()
            .ok_or_else(|| anyhow!("IdentifyAbstractions prep data missing"))?;

        let llm_context = prep["llm_context"].as_str().unwrap_or("").to_string();
        let file_listing = prep["file_listing_for_prompt"].as_str().unwrap_or("").to_string();
        let file_count = prep["file_count"].as_u64().unwrap_or(0) as usize;
        let project_name = prep["project_name"].as_str().unwrap_or("project").to_string();
        let language = prep["language"].as_str().unwrap_or("english").to_string();
        let use_cache = prep["use_cache"].as_bool().unwrap_or(true);
        let max_abstraction_num = prep["max_abstraction_num"].as_u64().unwrap_or(10) as usize;

        info!("Identifying abstractions using LLM...");

        // Language hints (mirrors Python logic)
        let (language_instruction, name_lang_hint, desc_lang_hint) =
            if language.to_lowercase() != "english" {
                let cap = capitalize(&language);
                (
                    format!(
                        "IMPORTANT: Generate the `name` and `description` for each abstraction \
                         in **{}** language. Do NOT use English for these fields.\n\n",
                        cap
                    ),
                    format!(" (value in {})", cap),
                    format!(" (value in {})", cap),
                )
            } else {
                (String::new(), String::new(), String::new())
            };

        let prompt = format!(
            r#"
For the project `{project_name}`:

Codebase Context:
{llm_context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core most important abstractions to help those new to the codebase.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` explaining what it is with a simple analogy, in around 100 words{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing}

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
```"#
        );

        let response =
            call_llm_with_retry(&prompt, use_cache, self.max_retries, self.wait_secs).await?;

        // --- Parse YAML response (mirrors Python validation block) ---
        let yaml_str = extract_yaml_block(&response)?;
        let raw: serde_yaml::Value = serde_yaml::from_str(&yaml_str)
            .map_err(|e| anyhow!("YAML parse error: {}", e))?;

        let items = raw
            .as_sequence()
            .ok_or_else(|| anyhow!("LLM output is not a YAML list"))?;

        let mut validated: Vec<Value> = Vec::new();
        for item in items {
            let name = item["name"]
                .as_str()
                .ok_or_else(|| anyhow!("Missing or non-string 'name' in abstraction"))?
                .trim()
                .to_string();
            let description = item["description"]
                .as_str()
                .ok_or_else(|| anyhow!("Missing or non-string 'description'"))?
                .trim()
                .to_string();
            let file_indices_raw = item["file_indices"]
                .as_sequence()
                .ok_or_else(|| anyhow!("'file_indices' is not a list"))?;

            let mut indices: Vec<usize> = Vec::new();
            for entry in file_indices_raw {
                let idx = parse_index_entry(entry, file_count)
                    .map_err(|e| anyhow!("Index parse error in '{}': {}", name, e))?;
                indices.push(idx);
            }
            // Deduplicate and sort (mirrors Python set + sorted)
            indices.sort_unstable();
            indices.dedup();

            validated.push(json!({
                "name": name,
                "description": description,
                "files": indices,
            }));
        }

        info!("Identified {} abstractions.", validated.len());
        Ok(json!(validated))
    }

    // post_process() — mirrors Python post():
    //   stores validated abstractions in shared["abstractions"].
    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(abstractions) => {
                context.set("abstractions", abstractions.clone());
                context.remove("__prep_IdentifyAbstractions");
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 3. AnalyzeRelationships
//    Python: builds prompt from abstractions + file snippets,
//            calls LLM, stores summary + relationship graph in
//            shared["relationships"].
// ═══════════════════════════════════════════════════════════════════
pub struct AnalyzeRelationships {
    pub max_retries: u32,
    pub wait_secs: u64,
}

impl Default for AnalyzeRelationships {
    fn default() -> Self {
        Self { max_retries: 5, wait_secs: 20 }
    }
}

#[async_trait]
impl Node for AnalyzeRelationships {
    type State = TutorialState;

    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let abstractions: Vec<Value> = serde_json::from_value(
            context
                .get("abstractions")
                .cloned()
                .ok_or_else(|| anyhow!("'abstractions' missing from context"))?,
        )?;
        let files_data = files_from_context(context)?;
        let project_name = context
            .get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("project")
            .to_string();
        let language = context
            .get("language")
            .and_then(|v| v.as_str())
            .unwrap_or("english")
            .to_string();
        let use_cache = context
            .get("use_cache")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        let num_abstractions = abstractions.len();

        // Build context string + abstraction listing (mirrors Python prep)
        let mut ctx_str = String::from("Identified Abstractions:\\n");
        let mut abstraction_listing_parts: Vec<String> = Vec::new();
        let mut all_relevant_indices: Vec<usize> = Vec::new();

        for (i, abstr) in abstractions.iter().enumerate() {
            let name = abstr["name"].as_str().unwrap_or("").to_string();
            let description = abstr["description"].as_str().unwrap_or("").to_string();
            let file_indices: Vec<usize> = serde_json::from_value(abstr["files"].clone())
                .unwrap_or_default();
            let indices_str = file_indices
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join(", ");

            ctx_str.push_str(&format!(
                "- Index {}: {} (Relevant file indices: [{}])\\n  Description: {}\\n",
                i, name, indices_str, description
            ));
            abstraction_listing_parts.push(format!("{} # {}", i, name));
            all_relevant_indices.extend(file_indices);
        }

        // Gather relevant file snippets
        all_relevant_indices.sort_unstable();
        all_relevant_indices.dedup();
        let file_content_map = get_content_for_indices(&files_data, &all_relevant_indices);

        ctx_str.push_str("\\nRelevant File Snippets (Referenced by Index and Path):\\n");
        let file_ctx_parts: Vec<String> = file_content_map
            .iter()
            .map(|(idx_path, content)| format!("--- File: {} ---\\n{}", idx_path, content))
            .collect();
        ctx_str.push_str(&file_ctx_parts.join("\\n\\n"));

        context.set(
            "__prep_AnalyzeRelationships",
            json!({
                "context_str": ctx_str,
                "abstraction_listing": abstraction_listing_parts.join("\n"),
                "num_abstractions": num_abstractions,
                "project_name": project_name,
                "language": language,
                "use_cache": use_cache,
            }),
        );
        Ok(())
    }

    async fn execute(&self, context: &Context) -> Result<Value> {
        let prep = context
            .get("__prep_AnalyzeRelationships")
            .cloned()
            .ok_or_else(|| anyhow!("AnalyzeRelationships prep data missing"))?;

        let ctx_str = prep["context_str"].as_str().unwrap_or("").to_string();
        let abstraction_listing = prep["abstraction_listing"].as_str().unwrap_or("").to_string();
        let num_abstractions = prep["num_abstractions"].as_u64().unwrap_or(0) as usize;
        let project_name = prep["project_name"].as_str().unwrap_or("project").to_string();
        let language = prep["language"].as_str().unwrap_or("english").to_string();
        let use_cache = prep["use_cache"].as_bool().unwrap_or(true);

        info!("Analyzing relationships using LLM...");

        // Language hints (mirrors Python logic)
        let (language_instruction, lang_hint, list_lang_note) =
            if language.to_lowercase() != "english" {
                let cap = capitalize(&language);
                (
                    format!(
                        "IMPORTANT: Generate the `summary` and relationship `label` fields \
                         in **{}** language. Do NOT use English for these fields.\n\n",
                        cap
                    ),
                    format!(" (in {})", cap),
                    format!(" (Names might be in {})", cap),
                )
            } else {
                (String::new(), String::new(), String::new())
            };

        let prompt = format!(
            r#"
Based on the following abstractions and relevant code snippets from the project `{project_name}`:

List of Abstraction Indices and Names{list_lang_note}:
{abstraction_listing}

Context (Abstractions, Descriptions, Code):
{ctx_str}

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

Now, provide the YAML output:"#
        );

        let response =
            call_llm_with_retry(&prompt, use_cache, self.max_retries, self.wait_secs).await?;

        // --- Parse + validate YAML (mirrors Python validation) ---
        let yaml_str = extract_yaml_block(&response)?;
        let raw: serde_yaml::Value = serde_yaml::from_str(&yaml_str)
            .map_err(|e| anyhow!("YAML parse error: {}", e))?;

        let summary = raw["summary"]
            .as_str()
            .ok_or_else(|| anyhow!("'summary' missing or not a string"))?
            .trim()
            .to_string();

        let rels_raw = raw["relationships"]
            .as_sequence()
            .ok_or_else(|| anyhow!("'relationships' is not a list"))?;

        let mut validated_rels: Vec<Value> = Vec::new();
        for rel in rels_raw {
            let label = rel["label"]
                .as_str()
                .ok_or_else(|| anyhow!("Relationship 'label' missing or not a string"))?
                .trim()
                .to_string();

            let from_idx =
                parse_yaml_index(&rel["from_abstraction"], num_abstractions, "from_abstraction")?;
            let to_idx =
                parse_yaml_index(&rel["to_abstraction"], num_abstractions, "to_abstraction")?;

            validated_rels.push(json!({
                "from": from_idx,
                "to": to_idx,
                "label": label,
            }));
        }

        info!("Generated project summary and relationship details.");
        Ok(json!({
            "summary": summary,
            "details": validated_rels,
        }))
    }

    // post_process() — mirrors Python post():
    //   stores result in shared["relationships"].
    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(relationships) => {
                context.set("relationships", relationships.clone());
                context.remove("__prep_AnalyzeRelationships");
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 4. OrderChapters
//    Python: asks LLM for the best chapter ordering, validates it,
//            stores ordered index list in shared["chapter_order"].
// ═══════════════════════════════════════════════════════════════════
pub struct OrderChapters {
    pub max_retries: u32,
    pub wait_secs: u64,
}

impl Default for OrderChapters {
    fn default() -> Self {
        Self { max_retries: 5, wait_secs: 20 }
    }
}

#[async_trait]
impl Node for OrderChapters {
    type State = TutorialState;

    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let abstractions: Vec<Value> = serde_json::from_value(
            context
                .get("abstractions")
                .cloned()
                .ok_or_else(|| anyhow!("'abstractions' missing"))?,
        )?;
        let relationships: Value = context
            .get("relationships")
            .cloned()
            .ok_or_else(|| anyhow!("'relationships' missing"))?;
        let project_name = context
            .get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("project")
            .to_string();
        let language = context
            .get("language")
            .and_then(|v| v.as_str())
            .unwrap_or("english")
            .to_string();
        let use_cache = context
            .get("use_cache")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        // Build abstraction listing (mirrors Python prep)
        let abstraction_listing = abstractions
            .iter()
            .enumerate()
            .map(|(i, a)| format!("- {} # {}", i, a["name"].as_str().unwrap_or("")))
            .collect::<Vec<_>>()
            .join("\n");

        // Build relationship context
        let summary_note = if language.to_lowercase() != "english" {
            format!(" (Note: Project Summary might be in {})", capitalize(&language))
        } else {
            String::new()
        };

        let summary = relationships["summary"].as_str().unwrap_or("").to_string();
        let mut context_str = format!("Project Summary{}:\n{}\n\nRelationships (Indices refer to abstractions above):\n", summary_note, summary);

        if let Some(details) = relationships["details"].as_array() {
            for rel in details {
                let from_idx = rel["from"].as_u64().unwrap_or(0) as usize;
                let to_idx = rel["to"].as_u64().unwrap_or(0) as usize;
                let label = rel["label"].as_str().unwrap_or("");
                let from_name = abstractions
                    .get(from_idx)
                    .and_then(|a| a["name"].as_str())
                    .unwrap_or("");
                let to_name = abstractions
                    .get(to_idx)
                    .and_then(|a| a["name"].as_str())
                    .unwrap_or("");
                context_str.push_str(&format!(
                    "- From {} ({}) to {} ({}): {}\n",
                    from_idx, from_name, to_idx, to_name, label
                ));
            }
        }

        let list_lang_note = if language.to_lowercase() != "english" {
            format!(" (Names might be in {})", capitalize(&language))
        } else {
            String::new()
        };

        context.set(
            "__prep_OrderChapters",
            json!({
                "abstraction_listing": abstraction_listing,
                "context_str": context_str,
                "num_abstractions": abstractions.len(),
                "project_name": project_name,
                "list_lang_note": list_lang_note,
                "use_cache": use_cache,
            }),
        );
        Ok(())
    }

    async fn execute(&self, context: &Context) -> Result<Value> {
        let prep = context
            .get("__prep_OrderChapters")
            .cloned()
            .ok_or_else(|| anyhow!("OrderChapters prep data missing"))?;

        let abstraction_listing = prep["abstraction_listing"].as_str().unwrap_or("").to_string();
        let context_str = prep["context_str"].as_str().unwrap_or("").to_string();
        let num_abstractions = prep["num_abstractions"].as_u64().unwrap_or(0) as usize;
        let project_name = prep["project_name"].as_str().unwrap_or("project").to_string();
        let list_lang_note = prep["list_lang_note"].as_str().unwrap_or("").to_string();
        let use_cache = prep["use_cache"].as_bool().unwrap_or(true);

        info!("Determining chapter order using LLM...");

        let prompt = format!(
            r#"
Given the following project abstractions and their relationships for the project `{project_name}`:

Abstractions (Index # Name){list_lang_note}:
{abstraction_listing}

Context about relationships and project summary:
{context_str}

If you are going to make a tutorial for `{project_name}`, what is the best order to explain these abstractions, from first to last?
Ideally, first explain those that are the most important or foundational, perhaps user-facing concepts or entry points. Then move to more detailed, lower-level implementation details or supporting concepts.

Output the ordered list of abstraction indices, including the name in a comment for clarity. Use the format `idx # AbstractionName`.

```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
- 1 # CoreClassB (uses CoreClassA)
- ...
```

Now, provide the YAML output:"#
        );

        let response =
            call_llm_with_retry(&prompt, use_cache, self.max_retries, self.wait_secs).await?;

        // Parse + validate YAML (mirrors Python validation)
        let yaml_str = extract_yaml_block(&response)?;
        let raw: serde_yaml::Value = serde_yaml::from_str(&yaml_str)
            .map_err(|e| anyhow!("YAML parse error: {}", e))?;

        let entries = raw
            .as_sequence()
            .ok_or_else(|| anyhow!("LLM output is not a list"))?;

        let mut ordered_indices: Vec<usize> = Vec::new();
        let mut seen: std::collections::HashSet<usize> = std::collections::HashSet::new();

        for entry in entries {
            let idx = parse_yaml_index(entry, num_abstractions, "chapter order entry")?;
            if seen.contains(&idx) {
                return Err(anyhow!("Duplicate index {} in ordered list", idx));
            }
            ordered_indices.push(idx);
            seen.insert(idx);
        }

        if ordered_indices.len() != num_abstractions {
            let missing: Vec<usize> = (0..num_abstractions)
                .filter(|i| !seen.contains(i))
                .collect();
            return Err(anyhow!(
                "Ordered list length ({}) != num_abstractions ({}). Missing: {:?}",
                ordered_indices.len(),
                num_abstractions,
                missing
            ));
        }

        info!("Determined chapter order (indices): {:?}", ordered_indices);
        Ok(json!(ordered_indices))
    }

    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(order) => {
                context.set("chapter_order", order.clone());
                context.remove("__prep_OrderChapters");
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 5. WriteChapters
//    Python: BatchNode — prep() returns a list of items; exec() is
//    called for each item in sequence.  We replicate by iterating
//    inside execute() and building `chapters_written_so_far` as we go,
//    exactly mirroring the Python instance-variable approach.
// ═══════════════════════════════════════════════════════════════════
pub struct WriteChapters {
    pub max_retries: u32,
    pub wait_secs: u64,
}

impl Default for WriteChapters {
    fn default() -> Self {
        Self { max_retries: 5, wait_secs: 20 }
    }
}

#[async_trait]
impl Node for WriteChapters {
    type State = TutorialState;

    // prepare() — builds per-chapter item list (mirrors Python prep())
    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let chapter_order: Vec<usize> = serde_json::from_value(
            context
                .get("chapter_order")
                .cloned()
                .ok_or_else(|| anyhow!("'chapter_order' missing"))?,
        )?;
        let abstractions: Vec<Value> = serde_json::from_value(
            context
                .get("abstractions")
                .cloned()
                .ok_or_else(|| anyhow!("'abstractions' missing"))?,
        )?;
        let files_data = files_from_context(context)?;
        let project_name = context
            .get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("project")
            .to_string();
        let language = context
            .get("language")
            .and_then(|v| v.as_str())
            .unwrap_or("english")
            .to_string();
        let use_cache = context
            .get("use_cache")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        // Build chapter_filenames map  { abstraction_index -> {num, name, filename} }
        // Mirrors the Python prep() dict-building block.
        let mut chapter_filenames: HashMap<usize, Value> = HashMap::new();
        let mut all_chapters: Vec<String> = Vec::new();
        for (i, &abs_idx) in chapter_order.iter().enumerate() {
            if abs_idx < abstractions.len() {
                let chapter_num = i + 1;
                let name = abstractions[abs_idx]["name"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                let safe_name = sanitize_name(&name);
                let filename = format!("{:02}_{}.md", chapter_num, safe_name);
                all_chapters.push(format!("{}. [{}]({})", chapter_num, name, filename));
                chapter_filenames.insert(
                    abs_idx,
                    json!({ "num": chapter_num, "name": name, "filename": filename }),
                );
            }
        }
        let full_chapter_listing = all_chapters.join("\n");

        // Build the per-chapter items list
        let mut items: Vec<Value> = Vec::new();
        for (i, &abs_idx) in chapter_order.iter().enumerate() {
            if abs_idx >= abstractions.len() {
                eprintln!("Warning: invalid abstraction index {}. Skipping.", abs_idx);
                continue;
            }
            let abstr = &abstractions[abs_idx];
            let file_indices: Vec<usize> =
                serde_json::from_value(abstr["files"].clone()).unwrap_or_default();
            let file_content_map = get_content_for_indices(&files_data, &file_indices);

            // prev/next chapter info
            let prev_chapter = if i > 0 {
                chapter_order
                    .get(i - 1)
                    .and_then(|&pi| chapter_filenames.get(&pi))
                    .cloned()
            } else {
                None
            };
            let next_chapter = if i + 1 < chapter_order.len() {
                chapter_order
                    .get(i + 1)
                    .and_then(|&ni| chapter_filenames.get(&ni))
                    .cloned()
            } else {
                None
            };

            // Serialise file_content_map as JSON object
            let file_content_json: Value = file_content_map
                .into_iter()
                .map(|(k, v)| (k, json!(v)))
                .collect::<serde_json::Map<_, _>>()
                .into();

            items.push(json!({
                "chapter_num": i + 1,
                "abstraction_index": abs_idx,
                "abstraction_name": abstr["name"],
                "abstraction_description": abstr["description"],
                "file_content_map": file_content_json,
                "project_name": project_name,
                "full_chapter_listing": full_chapter_listing,
                "prev_chapter": prev_chapter,
                "next_chapter": next_chapter,
                "language": language,
                "use_cache": use_cache,
            }));
        }

        info!("Preparing to write {} chapters...", items.len());
        context.set("__prep_WriteChapters", json!(items));
        Ok(())
    }

    // execute() — iterates over items list, calling LLM for each chapter.
    // Mirrors the Python BatchNode pattern: exec() is called per item,
    // accumulating chapters_written_so_far between iterations.
    async fn execute(&self, context: &Context) -> Result<Value> {
        let items: Vec<Value> = serde_json::from_value(
            context
                .get("__prep_WriteChapters")
                .cloned()
                .ok_or_else(|| anyhow!("WriteChapters prep data missing"))?,
        )?;

        let mut chapters_written_so_far: Vec<String> = Vec::new(); // mirrors self.chapters_written_so_far
        let mut all_chapter_contents: Vec<Value> = Vec::new();

        for item in &items {
            let chapter_content =
                self.write_single_chapter(item, &chapters_written_so_far).await?;
            chapters_written_so_far.push(chapter_content.clone());
            all_chapter_contents.push(json!(chapter_content));
        }

        Ok(json!(all_chapter_contents))
    }

    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(chapters) => {
                let count = chapters.as_array().map(|a| a.len()).unwrap_or(0);
                context.set("chapters", chapters.clone());
                context.remove("__prep_WriteChapters");
                info!("Finished writing {} chapters.", count);
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

impl WriteChapters {
    // Mirrors the Python exec() body — called for a single chapter item.
    async fn write_single_chapter(
        &self,
        item: &Value,
        chapters_written_so_far: &[String],
    ) -> Result<String> {
        let abstraction_name = item["abstraction_name"].as_str().unwrap_or("").to_string();
        let abstraction_description =
            item["abstraction_description"].as_str().unwrap_or("").to_string();
        let chapter_num = item["chapter_num"].as_u64().unwrap_or(1) as usize;
        let project_name = item["project_name"].as_str().unwrap_or("project").to_string();
        let language = item["language"].as_str().unwrap_or("english").to_string();
        let use_cache = item["use_cache"].as_bool().unwrap_or(true);
        let full_chapter_listing = item["full_chapter_listing"].as_str().unwrap_or("").to_string();

        info!(
            "Writing chapter {} for: {} using LLM...",
            chapter_num, abstraction_name
        );

        // Reconstruct file context string from stored map
        let file_ctx_str = if let Some(map) = item["file_content_map"].as_object() {
            map.iter()
                .map(|(idx_path, content)| {
                    let display = if idx_path.contains("# ") {
                        idx_path.splitn(2, "# ").nth(1).unwrap_or(idx_path).to_string()
                    } else {
                        idx_path.clone()
                    };
                    format!(
                        "--- File: {} ---\n{}",
                        display,
                        content.as_str().unwrap_or("")
                    )
                })
                .collect::<Vec<_>>()
                .join("\n\n")
        } else {
            String::new()
        };

        let previous_chapters_summary = chapters_written_so_far.join("\n---\n");

        // Language hints (mirrors Python exec logic)
        let (
            language_instruction,
            concept_details_note,
            structure_note,
            prev_summary_note,
            instruction_lang_note,
            mermaid_lang_note,
            code_comment_note,
            link_lang_note,
            tone_note,
        ) = if language.to_lowercase() != "english" {
            let cap = capitalize(&language);
            (
                format!("IMPORTANT: Write this ENTIRE tutorial chapter in **{}**. Some input context (like concept name, description, chapter list, previous summary) might already be in {}, but you MUST translate ALL other generated content including explanations, examples, technical terms, and potentially code comments into {}. DO NOT use English anywhere except in code syntax, required proper nouns, or when specified. The entire output MUST be in {}.\n\n", cap, cap, cap, cap),
                format!(" (Note: Provided in {})", cap),
                format!(" (Note: Chapter names might be in {})", cap),
                format!(" (Note: This summary might be in {})", cap),
                format!(" (in {})", cap),
                format!(" (Use {} for labels/text if appropriate)", cap),
                format!(" (Translate to {} if possible, otherwise keep minimal English for clarity)", cap),
                format!(" (Use the {} chapter title from the structure above)", cap),
                format!(" (appropriate for {} readers)", cap),
            )
        } else {
            (
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
                String::new(),
            )
        };

        // Prev / next navigation links
        let prev_link = item["prev_chapter"]
            .as_object()
            .map(|p| {
                format!(
                    "[{}]({})",
                    p.get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("Previous"),
                    p.get("filename")
                        .and_then(|v| v.as_str())
                        .unwrap_or("#")
                )
            });

        let next_link = item["next_chapter"]
            .as_object()
            .map(|n| {
                format!(
                    "[{}]({})",
                    n.get("name").and_then(|v| v.as_str()).unwrap_or("Next"),
                    n.get("filename").and_then(|v| v.as_str()).unwrap_or("#")
                )
            });

        let transition_note = prev_link
            .as_ref()
            .map(|l| format!("(Previous chapter: {})", l))
            .unwrap_or_default();

        let next_note = next_link
            .as_ref()
            .map(|l| format!("If there is a next chapter, use a proper Markdown link: {}", l))
            .unwrap_or_default();

        let prompt = format!(
            r#"
{language_instruction}Write a very beginner-friendly tutorial chapter (in Markdown format) for the project `{project_name}` about the concept: "{abstraction_name}". This is Chapter {chapter_num}.

Concept Details{concept_details_note}:
- Name: {abstraction_name}
- Description:
{abstraction_description}

Complete Tutorial Structure{structure_note}:
{full_chapter_listing}

Context from previous chapters{prev_summary_note}:
{previous_chapters}

Relevant Code Snippets (Code itself remains unchanged):
{file_ctx_str_display}

Instructions for the chapter (Generate content in {language} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {chapter_num}: {abstraction_name}`). Use the provided concept name.

- If this is not the first chapter, begin with a brief transition from the previous chapter{instruction_lang_note} {transition_note}.

- Begin with a high-level motivation explaining what problem this abstraction solves{instruction_lang_note}. Start with a central use case as a concrete example. The whole chapter should guide the reader to understand how to solve this use case. Make it very minimal and friendly to beginners.

- If the abstraction is complex, break it down into key concepts. Explain each concept one-by-one in a very beginner-friendly way{instruction_lang_note}.

- Explain how to use this abstraction to solve the use case{instruction_lang_note}. Give example inputs and outputs for code snippets.

- Each code block should be BELOW 10 lines! If longer code blocks are needed, break them down into smaller pieces and walk through them one-by-one. Aggressively simplify. Use comments{code_comment_note} to skip non-important details.

- Describe the internal implementation to help understand what's under the hood{instruction_lang_note}. First provide a non-code walkthrough on what happens step-by-step. Use a simple sequenceDiagram — keep it minimal with at most 5 participants. {mermaid_lang_note}.

- Then dive deeper into the internal implementation with references to files.

- IMPORTANT: When referring to other chapters, ALWAYS use Markdown links. {link_lang_note}.

- Use mermaid diagrams to illustrate complex concepts. {mermaid_lang_note}.

- Heavily use analogies and examples throughout{instruction_lang_note}.

- End the chapter with a brief conclusion and transition to the next chapter{instruction_lang_note}. {next_note}.

- Ensure the tone is welcoming and easy for a newcomer to understand{tone_note}.

- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):"#,
            language_instruction = language_instruction,
            project_name = project_name,
            abstraction_name = abstraction_name,
            chapter_num = chapter_num,
            concept_details_note = concept_details_note,
            abstraction_description = abstraction_description,
            structure_note = structure_note,
            full_chapter_listing = full_chapter_listing,
            prev_summary_note = prev_summary_note,
            previous_chapters = if previous_chapters_summary.is_empty() {
                "This is the first chapter.".to_string()
            } else {
                previous_chapters_summary
            },
            file_ctx_str_display = if file_ctx_str.is_empty() {
                "No specific code snippets provided for this abstraction.".to_string()
            } else {
                file_ctx_str
            },
            language = language,
            instruction_lang_note = instruction_lang_note,
            transition_note = transition_note,
            code_comment_note = code_comment_note,
            mermaid_lang_note = mermaid_lang_note,
            link_lang_note = link_lang_note,
            next_note = next_note,
            tone_note = tone_note,
        );

        let mut chapter_content =
            call_llm_with_retry(&prompt, use_cache, self.max_retries, self.wait_secs).await?;

        // Basic validation / heading fix (mirrors Python exec cleanup)
        let expected_prefix = format!("# Chapter {}", chapter_num);
        if !chapter_content.trim().starts_with(&expected_prefix) {
            let actual_heading = format!("# Chapter {}: {}", chapter_num, abstraction_name);
            let mut lines: Vec<&str> = chapter_content.trim().lines().collect();
            if lines.first().map(|l| l.starts_with('#')).unwrap_or(false) {
                // Replace existing heading
                lines[0] = &actual_heading;
                chapter_content = lines.join("\n");
            } else {
                // Prepend heading
                chapter_content = format!("{}\n\n{}", actual_heading, chapter_content.trim());
            }
        }

        Ok(chapter_content)
    }
}

// ═══════════════════════════════════════════════════════════════════
// 6. CombineTutorial
//    Python: builds Mermaid diagram + index.md, writes all files.
// ═══════════════════════════════════════════════════════════════════
pub struct CombineTutorial;

#[async_trait]
impl Node for CombineTutorial {
    type State = TutorialState;

    // prepare() — mirrors Python prep():
    //   builds Mermaid diagram, index.md content, and chapter file list.
    async fn prepare(&self, context: &mut Context) -> Result<()> {
        let project_name = context
            .get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("project")
            .to_string();
        let output_base_dir = context
            .get("output_dir")
            .and_then(|v| v.as_str())
            .unwrap_or("output")
            .to_string();
        let output_path = format!("{}/{}", output_base_dir, project_name);
        let repo_url = context
            .get("repo_url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_default();

        let relationships: Value = context
            .get("relationships")
            .cloned()
            .ok_or_else(|| anyhow!("'relationships' missing"))?;
        let chapter_order: Vec<usize> = serde_json::from_value(
            context
                .get("chapter_order")
                .cloned()
                .ok_or_else(|| anyhow!("'chapter_order' missing"))?,
        )?;
        let abstractions: Vec<Value> = serde_json::from_value(
            context
                .get("abstractions")
                .cloned()
                .ok_or_else(|| anyhow!("'abstractions' missing"))?,
        )?;
        let chapters_content: Vec<String> = serde_json::from_value(
            context
                .get("chapters")
                .cloned()
                .ok_or_else(|| anyhow!("'chapters' missing"))?,
        )?;

        // --- Build Mermaid diagram (mirrors Python prep) ---
        let mut mermaid_lines = vec!["flowchart TD".to_string()];
        for (i, abstr) in abstractions.iter().enumerate() {
            let node_id = format!("A{}", i);
            let sanitized = abstr["name"]
                .as_str()
                .unwrap_or("")
                .replace('"', "");
            mermaid_lines.push(format!("    {}[\"{}\"]", node_id, sanitized));
        }
        if let Some(details) = relationships["details"].as_array() {
            for rel in details {
                let from = rel["from"].as_u64().unwrap_or(0) as usize;
                let to = rel["to"].as_u64().unwrap_or(0) as usize;
                let mut edge_label = rel["label"]
                    .as_str()
                    .unwrap_or("")
                    .replace('"', "")
                    .replace('\n', " ");
                const MAX_LABEL_LEN: usize = 30;
                if edge_label.len() > MAX_LABEL_LEN {
                    edge_label = format!("{}...", &edge_label[..MAX_LABEL_LEN - 3]);
                }
                mermaid_lines.push(format!(
                    "    A{} -- \"{}\" --> A{}",
                    from, edge_label, to
                ));
            }
        }
        let mermaid_diagram = mermaid_lines.join("\n");

        // --- Build index.md content (mirrors Python prep) ---
        let summary = relationships["summary"].as_str().unwrap_or("").to_string();
        let mut index_content = format!("# Tutorial: {}\n\n", project_name);
        index_content.push_str(&format!("{}\n\n", summary));
        index_content.push_str(&format!(
            "**Source Repository:** [{}]({})\n\n",
            repo_url, repo_url
        ));
        index_content.push_str("```mermaid\n");
        index_content.push_str(&mermaid_diagram);
        index_content.push_str("\n```\n\n## Chapters\n\n");

        // Build chapter file entries + populate index
        let mut chapter_files: Vec<Value> = Vec::new();
        for (i, &abs_idx) in chapter_order.iter().enumerate() {
            if abs_idx < abstractions.len() && i < chapters_content.len() {
                let abstraction_name = abstractions[abs_idx]["name"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                let safe_name = sanitize_name(&abstraction_name);
                let filename = format!("{:02}_{}.md", i + 1, safe_name);

                index_content.push_str(&format!(
                    "{}. [{}]({})\n",
                    i + 1,
                    abstraction_name,
                    filename
                ));

                // Append attribution footer (mirrors Python post prep)
                let mut chapter_text = chapters_content[i].clone();
                if !chapter_text.ends_with("\n\n") {
                    chapter_text.push_str("\n\n");
                }
                chapter_text.push_str("---\n\nGenerated by [AI Codebase Knowledge Builder]");

                chapter_files.push(json!({
                    "filename": filename,
                    "content": chapter_text,
                }));
            } else {
                eprintln!(
                    "Warning: Mismatch at index {} (abstraction index {}). Skipping.",
                    i, abs_idx
                );
            }
        }

        index_content.push_str("\n\n---\n\nGenerated by [AI Codebase Knowledge Builder]");

        context.set(
            "__prep_CombineTutorial",
            json!({
                "output_path": output_path,
                "index_content": index_content,
                "chapter_files": chapter_files,
            }),
        );
        Ok(())
    }

    // execute() — mirrors Python exec(): creates dirs, writes all files.
    async fn execute(&self, context: &Context) -> Result<Value> {
        let prep = context
            .get("__prep_CombineTutorial")
            .cloned()
            .ok_or_else(|| anyhow!("CombineTutorial prep data missing"))?;

        let output_path = prep["output_path"].as_str().unwrap_or("output").to_string();
        let index_content = prep["index_content"].as_str().unwrap_or("").to_string();
        let chapter_files = prep["chapter_files"]
            .as_array()
            .cloned()
            .unwrap_or_default();

        info!("Combining tutorial into directory: {}", output_path);

        // Create output directory (mirrors os.makedirs)
        fs::create_dir_all(&output_path)
            .map_err(|e| anyhow!("Failed to create output dir '{}': {}", output_path, e))?;

        // Write index.md
        let index_path = format!("{}/index.md", output_path);
        fs::write(&index_path, &index_content)
            .map_err(|e| anyhow!("Failed to write '{}': {}", index_path, e))?;
        info!("  - Wrote {}", index_path);

        // Write chapter files
        for chapter in &chapter_files {
            let filename = chapter["filename"].as_str().unwrap_or("chapter.md");
            let content = chapter["content"].as_str().unwrap_or("");
            let chapter_path = format!("{}/{}", output_path, filename);
            fs::write(&chapter_path, content)
                .map_err(|e| anyhow!("Failed to write '{}': {}", chapter_path, e))?;
            info!("  - Wrote {}", chapter_path);
        }

        Ok(json!(output_path))
    }

    // post_process() — mirrors Python post(): stores final output path.
    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<TutorialState>> {
        match result {
            Ok(path) => {
                context.set("final_output_dir", path.clone());
                context.remove("__prep_CombineTutorial");
                info!(
                    "\nTutorial generation complete! Files are in: {}",
                    path.as_str().unwrap_or("")
                );
                Ok(ProcessResult::default())
            }
            Err(e) => Err(anyhow!("{}", e)),
        }
    }
}

// ─────────────────────────────────────────────
// Utility functions
// ─────────────────────────────────────────────

/// Extract the content between ```yaml and ``` fences.
/// Mirrors the Python pattern:  response.strip().split("```yaml")[1].split("```")[0].strip()
fn extract_yaml_block(response: &str) -> Result<String> {
    let parts: Vec<&str> = response.splitn(2, "```yaml").collect();
    if parts.len() < 2 {
        return Err(anyhow!("No ```yaml block found in LLM response"));
    }
    let after = parts[1];
    let inner = after
        .splitn(2, "```")
        .next()
        .ok_or_else(|| anyhow!("Unclosed ```yaml block"))?;
    Ok(inner.trim().to_string())
}

/// Parse an integer index from a YAML value of the form "N # name" or just N.
fn parse_yaml_index(entry: &serde_yaml::Value, max: usize, ctx: &str) -> Result<usize> {
    let idx: usize = match entry {
        serde_yaml::Value::Number(n) => n
            .as_u64()
            .ok_or_else(|| anyhow!("Not a u64 in {}", ctx))? as usize,
        serde_yaml::Value::String(s) => {
            let raw = if s.contains('#') {
                s.split('#').next().unwrap_or(s).trim().to_string()
            } else {
                s.trim().to_string()
            };
            raw.parse::<usize>()
                .map_err(|_| anyhow!("Could not parse index '{}' in {}", raw, ctx))?
        }
        _ => return Err(anyhow!("Unexpected YAML type for index in {}", ctx)),
    };
    if idx >= max {
        return Err(anyhow!(
            "Index {} out of range (max {}) in {}",
            idx,
            max - 1,
            ctx
        ));
    }
    Ok(idx)
}

/// Same but for serde_json::Value entries (used in file_indices lists).
fn parse_index_entry(entry: &serde_yaml::Value, file_count: usize) -> Result<usize> {
    parse_yaml_index(entry, file_count, "file_indices")
}

/// Capitalise first letter of a string (mirrors Python str.capitalize()).
fn capitalize(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        None => String::new(),
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
    }
}

/// Mirror Python:  "".join(c if c.isalnum() else "_" for c in name).lower()
fn sanitize_name(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_alphanumeric() { c } else { '_' })
        .collect::<String>()
        .to_lowercase()
}
