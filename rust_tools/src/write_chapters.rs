// src/write_chapters.rs
use pocketflow_rs::{BatchNode, Node, SharedState};
use serde_json::Value;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use crate::llm_caller::call_llm;
use crate::fetch_repo::get_content_for_indices;
use crate::identify_abstractions::Abstraction;
use crate::analyze_relationships::RelationshipsData;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ChapterFilename {
    num: usize,
    name: String,
    filename: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ChapterItem {
    chapter_num: usize,
    abstraction_index: usize,
    abstraction_details: Abstraction,
    related_files_content_map: HashMap<String, String>,
    project_name: String,
    full_chapter_listing: String,
    chapter_filenames: HashMap<usize, ChapterFilename>,
    prev_chapter: Option<ChapterFilename>,
    next_chapter: Option<ChapterFilename>,
    language: String,
    use_cache: bool,
}

pub struct WriteChapters {
    chapters_written_so_far: Vec<String>,
}

impl WriteChapters {
    pub fn new() -> Self {
        Self {
            chapters_written_so_far: Vec::new(),
        }
    }
}

impl BatchNode for WriteChapters {
    fn prep(&mut self, shared: &mut SharedState) -> Result<Vec<Value>, Box<dyn std::error::Error>> {
        let chapter_order = shared.get("chapter_order")
            .and_then(|v| serde_json::from_value::<Vec<usize>>(v.clone()).ok())
            .ok_or("chapter_order not found in shared state")?;
        
        let abstractions = shared.get("abstractions")
            .and_then(|v| serde_json::from_value::<Vec<Abstraction>>(v.clone()).ok())
            .ok_or("abstractions not found in shared state")?;
        
        let files_data = shared.get("files")
            .and_then(|v| serde_json::from_value::<Vec<(String, String)>>(v.clone()).ok())
            .ok_or("files not found in shared state")?;
        
        let project_name = shared.get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        
        let language = shared.get("language")
            .and_then(|v| v.as_str())
            .unwrap_or("english")
            .to_string();
        
        let use_cache = shared.get("use_cache")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        self.chapters_written_so_far.clear();

        let mut all_chapters = Vec::new();
        let mut chapter_filenames = HashMap::new();

        for (i, &abstraction_index) in chapter_order.iter().enumerate() {
            if abstraction_index < abstractions.len() {
                let chapter_num = i + 1;
                let chapter_name = &abstractions[abstraction_index].name;
                let safe_name: String = chapter_name.chars()
                    .map(|c| if c.is_alphanumeric() { c } else { '_' })
                    .collect::<String>()
                    .to_lowercase();
                let filename = format!("{:02}_{}.md", i + 1, safe_name);
                all_chapters.push(format!("{}. [{}]({})", chapter_num, chapter_name, filename));
                
                chapter_filenames.insert(
                    abstraction_index,
                    ChapterFilename {
                        num: chapter_num,
                        name: chapter_name.clone(),
                        filename,
                    },
                );
            }
        }

        let full_chapter_listing = all_chapters.join("\n");

        let mut items_to_process = Vec::new();

        for (i, &abstraction_index) in chapter_order.iter().enumerate() {
            if abstraction_index < abstractions.len() {
                let abstraction_details = abstractions[abstraction_index].clone();
                let related_file_indices = &abstraction_details.files;
                let related_files_content_map = get_content_for_indices(&files_data, related_file_indices);

                let prev_chapter = if i > 0 {
                    let prev_idx = chapter_order[i - 1];
                    chapter_filenames.get(&prev_idx).cloned()
                } else {
                    None
                };

                let next_chapter = if i < chapter_order.len() - 1 {
                    let next_idx = chapter_order[i + 1];
                    chapter_filenames.get(&next_idx).cloned()
                } else {
                    None
                };

                items_to_process.push(ChapterItem {
                    chapter_num: i + 1,
                    abstraction_index,
                    abstraction_details,
                    related_files_content_map,
                    project_name: project_name.clone(),
                    full_chapter_listing: full_chapter_listing.clone(),
                    chapter_filenames: chapter_filenames.clone(),
                    prev_chapter,
                    next_chapter,
                    language: language.clone(),
                    use_cache,
                });
            } else {
                println!("Warning: Invalid abstraction index {} in chapter_order. Skipping.", abstraction_index);
            }
        }

        println!("Preparing to write {} chapters...", items_to_process.len());
        Ok(items_to_process.into_iter().map(|item| serde_json::to_value(item).unwrap()).collect())
    }

    fn exec(&mut self, item: &Value) -> Result<Value, Box<dyn std::error::Error>> {
        let item_data: ChapterItem = serde_json::from_value(item.clone())?;
        
        let abstraction_name = &item_data.abstraction_details.name;
        let abstraction_description = &item_data.abstraction_details.description;
        let chapter_num = item_data.chapter_num;
        let project_name = &item_data.project_name;
        let language = &item_data.language;
        let use_cache = item_data.use_cache;

        println!("Writing chapter {} for: {} using LLM...", chapter_num, abstraction_name);

        let file_context_str = item_data.related_files_content_map.iter()
            .map(|(idx_path, content)| {
                let path = if idx_path.contains("# ") {
                    idx_path.split("# ").nth(1).unwrap_or(idx_path)
                } else {
                    idx_path
                };
                format!("--- File: {} ---\n{}", path, content)
            })
            .collect::<Vec<_>>()
            .join("\n\n");

        let previous_chapters_summary = self.chapters_written_so_far.join("\n---\n");

        let (language_instruction, concept_details_note, structure_note, prev_summary_note, 
             instruction_lang_note, mermaid_lang_note, code_comment_note, link_lang_note, tone_note) = 
            if language.to_lowercase() != "english" {
                let lang_cap = language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..];
                (
                    format!("IMPORTANT: Write this ENTIRE tutorial chapter in **{}**. Some input context (like concept name, description, chapter list, previous summary) might already be in {}, but you MUST translate ALL other generated content including explanations, examples, technical terms, and potentially code comments into {}. DO NOT use English anywhere except in code syntax, required proper nouns, or when specified. The entire output MUST be in {}.\n\n", 
                        lang_cap, lang_cap, lang_cap, lang_cap),
                    format!(" (Note: Provided in {})", lang_cap),
                    format!(" (Note: Chapter names might be in {})", lang_cap),
                    format!(" (Note: This summary might be in {})", lang_cap),
                    format!(" (in {})", lang_cap),
                    format!(" (Use {} for labels/text if appropriate)", lang_cap),
                    format!(" (Translate to {} if possible, otherwise keep minimal English for clarity)", lang_cap),
                    format!(" (Use the {} chapter title from the structure above)", lang_cap),
                    format!(" (appropriate for {} readers)", lang_cap),
                )
            } else {
                (String::new(), String::new(), String::new(), String::new(), 
                 String::new(), String::new(), String::new(), String::new(), String::new())
            };

        let prev_summary_text = if previous_chapters_summary.is_empty() {
            "This is the first chapter."
        } else {
            &previous_chapters_summary
        };

        let file_context_text = if file_context_str.is_empty() {
            "No specific code snippets provided for this abstraction."
        } else {
            &file_context_str
        };

        let prompt = format!(r#"
{}Write a very beginner-friendly tutorial chapter (in Markdown format) for the project `{}` about the concept: "{}". This is Chapter {}.

Concept Details{}:
- Name: {}
- Description:
{}

Complete Tutorial Structure{}:
{}

Context from previous chapters{}:
{}

Relevant Code Snippets (Code itself remains unchanged):
{}

Instructions for the chapter (Generate content in {} unless specified otherwise):
- Start with a clear heading (e.g., `# Chapter {}: {}`). Use the provided concept name.

- If this is not the first chapter, begin with a brief transition from the previous chapter{}, referencing it with a proper Markdown link using its name{}.

- Begin with a high-level motivation explaining what problem this abstraction solves{}. Start with a central use case as a concrete example. The whole chapter should guide the reader to understand how to solve this use case. Make it very minimal and friendly to beginners.

- If the abstraction is complex, break it down into key concepts. Explain each concept one-by-one in a very beginner-friendly way{}.

- Explain how to use this abstraction to solve the use case{}. Give example inputs and outputs for code snippets (if the output isn't values, describe at a high level what will happen{}).

- Each code block should be BELOW 10 lines! If longer code blocks are needed, break them down into smaller pieces and walk through them one-by-one. Aggresively simplify the code to make it minimal. Use comments{} to skip non-important implementation details. Each code block should have a beginner friendly explanation right after it{}.

- Describe the internal implementation to help understand what's under the hood{}. First provide a non-code or code-light walkthrough on what happens step-by-step when the abstraction is called{}. It's recommended to use a simple sequenceDiagram with a dummy example - keep it minimal with at most 5 participants to ensure clarity. If participant name has space, use: `participant QP as Query Processing`. {}.

- Then dive deeper into code for the internal implementation with references to files. Provide example code blocks, but make them similarly simple and beginner-friendly. Explain{}.

- IMPORTANT: When you need to refer to other core abstractions covered in other chapters, ALWAYS use proper Markdown links like this: [Chapter Title](filename.md). Use the Complete Tutorial Structure above to find the correct filename and the chapter title{}. Translate the surrounding text.

- Use mermaid diagrams to illustrate complex concepts (```mermaid``` format). {}.

- Heavily use analogies and examples throughout{} to help beginners understand.

- End the chapter with a brief conclusion that summarizes what was learned{} and provides a transition to the next chapter{}. If there is a next chapter, use a proper Markdown link: [Next Chapter Title](next_chapter_filename){}.

- Ensure the tone is welcoming and easy for a newcomer to understand{}.

- Output *only* the Markdown content for this chapter.

Now, directly provide a super beginner-friendly Markdown output (DON'T need ```markdown``` tags):
"#, language_instruction, project_name, abstraction_name, chapter_num,
            concept_details_note, abstraction_name, abstraction_description,
            structure_note, item_data.full_chapter_listing,
            prev_summary_note, prev_summary_text,
            file_context_text,
            language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..],
            chapter_num, abstraction_name,
            instruction_lang_note, link_lang_note, instruction_lang_note, instruction_lang_note,
            instruction_lang_note, instruction_lang_note, code_comment_note, instruction_lang_note,
            instruction_lang_note, instruction_lang_note, mermaid_lang_note, instruction_lang_note,
            link_lang_note, mermaid_lang_note, instruction_lang_note, instruction_lang_note,
            instruction_lang_note, link_lang_note, tone_note);

        let cur_retry = self.get_retry_count();
        let mut chapter_content = call_llm(&prompt, use_cache && cur_retry == 0)?;

        let actual_heading = format!("# Chapter {}: {}", chapter_num, abstraction_name);
        if !chapter_content.trim().starts_with(&format!("# Chapter {}", chapter_num)) {
            let lines: Vec<&str> = chapter_content.trim().split('\n').collect();
            if !lines.is_empty() && lines[0].trim().starts_with('#') {
                chapter_content = format!("{}\n{}", actual_heading, lines[1..].join("\n"));
            } else {
                chapter_content = format!("{}\n\n{}", actual_heading, chapter_content);
            }
        }

        self.chapters_written_so_far.push(chapter_content.clone());

        Ok(serde_json::json!(chapter_content))
    }

    fn post(&self, shared: &mut SharedState, _prep_res: &Vec<Value>, exec_res_list: &Vec<Value>) -> Result<(), Box<dyn std::error::Error>> {
        shared.insert("chapters".to_string(), serde_json::to_value(exec_res_list)?);
        println!("Finished writing {} chapters.", exec_res_list.len());
        Ok(())
    }

    fn get_retry_count(&self) -> usize {
        0
    }
}


pub struct CombineTutorial;

impl Node for CombineTutorial {
    fn prep(&self, shared: &mut SharedState) -> Result<Value, Box<dyn std::error::Error>> {
        let project_name = shared.get("project_name")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        
        let output_base_dir = shared.get("output_dir")
            .and_then(|v| v.as_str())
            .unwrap_or("output");
        
        let output_path = format!("{}/{}", output_base_dir, project_name);
        
        let repo_url = shared.get("repo_url")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let relationships_data = shared.get("relationships")
            .and_then(|v| serde_json::from_value::<RelationshipsData>(v.clone()).ok())
            .ok_or("relationships not found in shared state")?;
        
        let chapter_order = shared.get("chapter_order")
            .and_then(|v| serde_json::from_value::<Vec<usize>>(v.clone()).ok())
            .ok_or("chapter_order not found in shared state")?;
        
        let abstractions = shared.get("abstractions")
            .and_then(|v| serde_json::from_value::<Vec<Abstraction>>(v.clone()).ok())
            .ok_or("abstractions not found in shared state")?;
        
        let chapters_content = shared.get("chapters")
            .and_then(|v| serde_json::from_value::<Vec<String>>(v.clone()).ok())
            .ok_or("chapters not found in shared state")?;

        let mut mermaid_lines = vec!["flowchart TD".to_string()];
        
        for (i, abstr) in abstractions.iter().enumerate() {
            let node_id = format!("A{}", i);
            let sanitized_name = abstr.name.replace('"', "");
            mermaid_lines.push(format!("    {}[\"{}\"]", node_id, sanitized_name));
        }

        for rel in &relationships_data.details {
            let from_node_id = format!("A{}", rel.from);
            let to_node_id = format!("A{}", rel.to);
            let mut edge_label = rel.label.replace('"', "").replace('\n', " ");
            let max_label_len = 30;
            if edge_label.len() > max_label_len {
                edge_label = format!("{}...", &edge_label[..max_label_len - 3]);
            }
            mermaid_lines.push(format!("    {} -- \"{}\" --> {}", from_node_id, edge_label, to_node_id));
        }

        let mermaid_diagram = mermaid_lines.join("\n");

        let mut index_content = format!("# Tutorial: {}\n\n", project_name);
        index_content.push_str(&format!("{}\n\n", relationships_data.summary));
        index_content.push_str(&format!("**Source Repository:** [{}]({})\n\n", repo_url, repo_url));
        index_content.push_str("```mermaid\n");
        index_content.push_str(&mermaid_diagram);
        index_content.push_str("\n```\n\n");
        index_content.push_str("## Chapters\n\n");

        let mut chapter_files = Vec::new();

        for (i, &abstraction_index) in chapter_order.iter().enumerate() {
            if abstraction_index < abstractions.len() && i < chapters_content.len() {
                let abstraction_name = &abstractions[abstraction_index].name;
                let safe_name: String = abstraction_name.chars()
                    .map(|c| if c.is_alphanumeric() { c } else { '_' })
                    .collect::<String>()
                    .to_lowercase();
                let filename = format!("{:02}_{}.md", i + 1, safe_name);
                index_content.push_str(&format!("{}. [{}]({})\n", i + 1, abstraction_name, filename));

                let mut chapter_content = chapters_content[i].clone();
                if !chapter_content.ends_with("\n\n") {
                    chapter_content.push_str("\n\n");
                }
                chapter_content.push_str("---\n\nGenerated by [AI Codebase Knowledge Builder]");

                chapter_files.push(serde_json::json!({
                    "filename": filename,
                    "content": chapter_content
                }));
            } else {
                println!("Warning: Mismatch between chapter order, abstractions, or content at index {} (abstraction index {}). Skipping file generation for this entry.", i, abstraction_index);
            }
        }

        index_content.push_str("\n\n---\n\nGenerated by [AI Codebase Knowledge Builder]");

        Ok(serde_json::json!({
            "output_path": output_path,
            "index_content": index_content,
            "chapter_files": chapter_files
        }))
    }

    fn exec(&self, prep_res: &Value) -> Result<Value, Box<dyn std::error::Error>> {
        let output_path = prep_res.get("output_path").and_then(|v| v.as_str()).unwrap();
        let index_content = prep_res.get("index_content").and_then(|v| v.as_str()).unwrap();
        let chapter_files = prep_res.get("chapter_files").and_then(|v| v.as_array()).unwrap();

        println!("Combining tutorial into directory: {}", output_path);
        fs::create_dir_all(output_path)?;

        let index_filepath = format!("{}/index.md", output_path);
        fs::write(&index_filepath, index_content)?;
        println!("  - Wrote {}", index_filepath);

        for chapter_info in chapter_files {
            let filename = chapter_info.get("filename").and_then(|v| v.as_str()).unwrap();
            let content = chapter_info.get("content").and_then(|v| v.as_str()).unwrap();
            let chapter_filepath = format!("{}/{}", output_path, filename);
            fs::write(&chapter_filepath, content)?;
            println!("  - Wrote {}", chapter_filepath);
        }

        Ok(serde_json::json!(output_path))
    }

    fn post(&self, shared: &mut SharedState, _prep_res: &Value, exec_res: &Value) -> Result<(), Box<dyn std::error::Error>> {
        shared.insert("final_output_dir".to_string(), exec_res.clone());
        println!("\nTutorial generation complete! Files are in: {}", exec_res.as_str().unwrap());
        Ok(())
    }
}