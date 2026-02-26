// src/analyze_relationships.rs
use pocketflow_rs::{Node, SharedState};
use serde_json::Value;
use serde::{Deserialize, Serialize};
use yaml_rust::YamlLoader;
use crate::llm_caller::call_llm;
use crate::fetch_repo::get_content_for_indices;
use crate::identify_abstractions::Abstraction;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Relationship {
    pub from: usize,
    pub to: usize,
    pub label: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RelationshipsData {
    pub summary: String,
    pub details: Vec<Relationship>,
}

pub struct AnalyzeRelationships;

impl Node for AnalyzeRelationships {
    fn prep(&self, shared: &mut SharedState) -> Result<Value, Box<dyn std::error::Error>> {
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

        let num_abstractions = abstractions.len();

        let mut context = String::from("Identified Abstractions:\\n");
        let mut all_relevant_indices = std::collections::HashSet::new();
        let mut abstraction_info_for_prompt = Vec::new();
        
        for (i, abstr) in abstractions.iter().enumerate() {
            let file_indices_str = abstr.files.iter()
                .map(|idx| idx.to_string())
                .collect::<Vec<_>>()
                .join(", ");
            
            let info_line = format!("- Index {}: {} (Relevant file indices: [{}])\\n  Description: {}", 
                i, abstr.name, file_indices_str, abstr.description);
            context.push_str(&info_line);
            context.push_str("\\n");
            abstraction_info_for_prompt.push(format!("{} # {}", i, abstr.name));
            all_relevant_indices.extend(&abstr.files);
        }

        context.push_str("\\nRelevant File Snippets (Referenced by Index and Path):\\n");
        
        let mut sorted_indices: Vec<usize> = all_relevant_indices.into_iter().collect();
        sorted_indices.sort();
        
        let relevant_files_content_map = get_content_for_indices(&files_data, &sorted_indices);
        
        let file_context_str = relevant_files_content_map.iter()
            .map(|(idx_path, content)| format!("--- File: {} ---\\n{}", idx_path, content))
            .collect::<Vec<_>>()
            .join("\\n\\n");
        
        context.push_str(&file_context_str);

        Ok(serde_json::json!({
            "context": context,
            "abstraction_listing": abstraction_info_for_prompt.join("\n"),
            "num_abstractions": num_abstractions,
            "project_name": project_name,
            "language": language,
            "use_cache": use_cache
        }))
    }

    fn exec(&self, prep_res: &Value) -> Result<Value, Box<dyn std::error::Error>> {
        let context = prep_res.get("context").and_then(|v| v.as_str()).unwrap();
        let abstraction_listing = prep_res.get("abstraction_listing").and_then(|v| v.as_str()).unwrap();
        let num_abstractions = prep_res.get("num_abstractions").and_then(|v| v.as_u64()).unwrap() as usize;
        let project_name = prep_res.get("project_name").and_then(|v| v.as_str()).unwrap();
        let language = prep_res.get("language").and_then(|v| v.as_str()).unwrap();
        let use_cache = prep_res.get("use_cache").and_then(|v| v.as_bool()).unwrap();

        println!("Analyzing relationships using LLM...");

        let mut language_instruction = String::new();
        let mut lang_hint = String::new();
        let mut list_lang_note = String::new();
        
        if language.to_lowercase() != "english" {
            let lang_cap = language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..];
            language_instruction = format!("IMPORTANT: Generate the `summary` and relationship `label` fields in **{}** language. Do NOT use English for these fields.\n\n", lang_cap);
            lang_hint = format!(" (in {})", lang_cap);
            list_lang_note = format!(" (Names might be in {})", lang_cap);
        }

        let prompt = format!(r#"
Based on the following abstractions and relevant code snippets from the project `{}`:

List of Abstraction Indices and Names{}:
{}

Context (Abstractions, Descriptions, Code):
{}

{}Please provide:
1. A high-level `summary` of the project's main purpose and functionality in a few beginner-friendly sentences{}. Use markdown formatting with **bold** and *italic* text to highlight important concepts.
2. A list (`relationships`) describing the key interactions between these abstractions. For each relationship, specify:
    - `from_abstraction`: Index of the source abstraction (e.g., `0 # AbstractionName1`)
    - `to_abstraction`: Index of the target abstraction (e.g., `1 # AbstractionName2`)
    - `label`: A brief label for the interaction **in just a few words**{} (e.g., "Manages", "Inherits", "Uses").
    Ideally the relationship should be backed by one abstraction calling or passing parameters to another.
    Simplify the relationship and exclude those non-important ones.

IMPORTANT: Make sure EVERY abstraction is involved in at least ONE relationship (either as source or target). Each abstraction index must appear at least once across all relationships.

Format the output as YAML:
```yaml
summary: |
  A brief, simple explanation of the project{}.
  Can span multiple lines with **bold** and *italic* for emphasis.
relationships:
  - from_abstraction: 0 # AbstractionName1
    to_abstraction: 1 # AbstractionName2
    label: "Manages"{}
  - from_abstraction: 2 # AbstractionName3
    to_abstraction: 0 # AbstractionName1
    label: "Provides config"{}
  # ... other relationships
```

Now, provide the YAML output:
"#, project_name, list_lang_note, abstraction_listing, context, 
            language_instruction, lang_hint, lang_hint, lang_hint, lang_hint, lang_hint);

        let cur_retry = self.get_retry_count();
        let response = call_llm(&prompt, use_cache && cur_retry == 0)?;

        let yaml_str = response.trim()
            .split("```yaml").nth(1)
            .ok_or("YAML block not found")?
            .split("```").next()
            .ok_or("YAML block end not found")?
            .trim();

        let docs = YamlLoader::load_from_str(yaml_str)?;
        let relationships_yaml = docs.get(0).ok_or("No YAML document found")?;

        let summary = relationships_yaml["summary"].as_str()
            .ok_or("summary is not a string")?
            .trim()
            .to_string();

        let relationships_list = relationships_yaml["relationships"].as_vec()
            .ok_or("relationships is not a list")?;

        let mut validated_relationships = Vec::new();
        
        for rel in relationships_list {
            let label = rel["label"].as_str()
                .ok_or(format!("Relationship label is not a string: {:?}", rel))?
                .trim()
                .to_string();

            let from_str = rel["from_abstraction"].as_str()
                .or_else(|| rel["from_abstraction"].as_i64().map(|i| i.to_string().leak() as &str))
                .ok_or(format!("from_abstraction not found in relationship: {:?}", rel))?;
            
            let to_str = rel["to_abstraction"].as_str()
                .or_else(|| rel["to_abstraction"].as_i64().map(|i| i.to_string().leak() as &str))
                .ok_or(format!("to_abstraction not found in relationship: {:?}", rel))?;

            let from_idx = from_str.split('#').next().unwrap().trim().parse::<usize>()?;
            let to_idx = to_str.split('#').next().unwrap().trim().parse::<usize>()?;

            if from_idx >= num_abstractions || to_idx >= num_abstractions {
                return Err(format!("Invalid index in relationship: from={}, to={}. Max index is {}.", 
                    from_idx, to_idx, num_abstractions - 1).into());
            }

            validated_relationships.push(Relationship {
                from: from_idx,
                to: to_idx,
                label,
            });
        }

        println!("Generated project summary and relationship details.");
        
        let result = RelationshipsData {
            summary,
            details: validated_relationships,
        };

        Ok(serde_json::to_value(result)?)
    }

    fn post(&self, shared: &mut SharedState, _prep_res: &Value, exec_res: &Value) -> Result<(), Box<dyn std::error::Error>> {
        shared.insert("relationships".to_string(), exec_res.clone());
        Ok(())
    }

    fn get_retry_count(&self) -> usize {
        0
    }
}