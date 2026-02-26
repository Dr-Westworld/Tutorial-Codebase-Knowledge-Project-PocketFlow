// src/identify_abstractions.rs
use pocketflow_rs::{Node, SharedState};
use serde_json::Value;
use serde::{Deserialize, Serialize};
use yaml_rust::{YamlLoader, Yaml};
use crate::llm_caller::call_llm;
use crate::fetch_repo::get_content_for_indices;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Abstraction {
    pub name: String,
    pub description: String,
    pub files: Vec<usize>,
}

pub struct IdentifyAbstractions;

impl Node for IdentifyAbstractions {
    fn prep(&self, shared: &mut SharedState) -> Result<Value, Box<dyn std::error::Error>> {
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
        
        let max_abstraction_num = shared.get("max_abstraction_num")
            .and_then(|v| v.as_u64())
            .unwrap_or(10) as usize;

        let mut context = String::new();
        let mut file_info = Vec::new();
        
        for (i, (path, content)) in files_data.iter().enumerate() {
            let entry = format!("--- File Index {}: {} ---\n{}\n\n", i, path, content);
            context.push_str(&entry);
            file_info.push((i, path.clone()));
        }

        let file_listing_for_prompt = file_info
            .iter()
            .map(|(idx, path)| format!("- {} # {}", idx, path))
            .collect::<Vec<_>>()
            .join("\n");

        Ok(serde_json::json!({
            "context": context,
            "file_listing_for_prompt": file_listing_for_prompt,
            "file_count": files_data.len(),
            "project_name": project_name,
            "language": language,
            "use_cache": use_cache,
            "max_abstraction_num": max_abstraction_num
        }))
    }

    fn exec(&self, prep_res: &Value) -> Result<Value, Box<dyn std::error::Error>> {
        let context = prep_res.get("context").and_then(|v| v.as_str()).unwrap();
        let file_listing_for_prompt = prep_res.get("file_listing_for_prompt").and_then(|v| v.as_str()).unwrap();
        let file_count = prep_res.get("file_count").and_then(|v| v.as_u64()).unwrap() as usize;
        let project_name = prep_res.get("project_name").and_then(|v| v.as_str()).unwrap();
        let language = prep_res.get("language").and_then(|v| v.as_str()).unwrap();
        let use_cache = prep_res.get("use_cache").and_then(|v| v.as_bool()).unwrap();
        let max_abstraction_num = prep_res.get("max_abstraction_num").and_then(|v| v.as_u64()).unwrap() as usize;

        println!("Identifying abstractions using LLM...");

        let mut language_instruction = String::new();
        let mut name_lang_hint = String::new();
        let mut desc_lang_hint = String::new();
        
        if language.to_lowercase() != "english" {
            language_instruction = format!("IMPORTANT: Generate the `name` and `description` for each abstraction in **{}** language. Do NOT use English for these fields.\n\n", 
                language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..]);
            name_lang_hint = format!(" (value in {})", language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..]);
            desc_lang_hint = format!(" (value in {})", language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..]);
        }

        let prompt = format!(r#"
For the project `{}`:

Codebase Context:
{}

{}Analyze the codebase context.
Identify the top 5-{} core most important abstractions to help those new to the codebase.

For each abstraction, provide:
1. A concise `name`{}.
2. A beginner-friendly `description` explaining what it is with a simple analogy, in around 100 words{}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{}

Format the output as a YAML list of dictionaries:
`````yaml
- name: |
    Query Processing{}
  description: |
    Explains what the abstraction does.
    It's like a central dispatcher routing requests.{}
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
- name: |
    Query Optimization{}
  description: |
    Another core concept, similar to a blueprint for objects.{}
  file_indices:
    - 5 # path/to/another.js
# ... up to {} abstractions
````"#, project_name, context, language_instruction, max_abstraction_num,
            name_lang_hint, desc_lang_hint, file_listing_for_prompt, 
            name_lang_hint, desc_lang_hint, name_lang_hint, desc_lang_hint, max_abstraction_num);

        let cur_retry = self.get_retry_count();
        let response = call_llm(&prompt, use_cache && cur_retry == 0)?;

        let yaml_str = response.trim()
            .split("```yaml").nth(1)
            .ok_or("YAML block not found")?
            .split("```").next()
            .ok_or("YAML block end not found")?
            .trim();

        let docs = YamlLoader::load_from_str(yaml_str)?;
        let abstractions_yaml = docs.get(0).ok_or("No YAML document found")?;

        if !abstractions_yaml.as_vec().is_some() {
            return Err("LLM Output is not a list".into());
        }

        let mut validated_abstractions = Vec::new();
        
        for item in abstractions_yaml.as_vec().unwrap() {
            let name = item["name"].as_str()
                .ok_or(format!("Name is not a string in item: {:?}", item))?
                .trim()
                .to_string();
            
            let description = item["description"].as_str()
                .ok_or(format!("Description is not a string in item: {:?}", item))?
                .trim()
                .to_string();
            
            let file_indices = item["file_indices"].as_vec()
                .ok_or(format!("file_indices is not a list in item: {:?}", item))?;

            let mut validated_indices = Vec::new();
            
            for idx_entry in file_indices {
                let idx = if let Some(int_val) = idx_entry.as_i64() {
                    int_val as usize
                } else if let Some(str_val) = idx_entry.as_str() {
                    if str_val.contains('#') {
                        str_val.split('#').next().unwrap().trim().parse::<usize>()?
                    } else {
                        str_val.trim().parse::<usize>()?
                    }
                } else {
                    return Err(format!("Could not parse index from entry: {:?} in item {}", idx_entry, name).into());
                };

                if idx >= file_count {
                    return Err(format!("Invalid file index {} found in item {}. Max index is {}.", idx, name, file_count - 1).into());
                }
                validated_indices.push(idx);
            }

            let mut unique_indices = validated_indices.clone();
            unique_indices.sort();
            unique_indices.dedup();

            validated_abstractions.push(Abstraction {
                name,
                description,
                files: unique_indices,
            });
        }

        println!("Identified {} abstractions.", validated_abstractions.len());
        Ok(serde_json::to_value(validated_abstractions)?)
    }

    fn post(&self, shared: &mut SharedState, _prep_res: &Value, exec_res: &Value) -> Result<(), Box<dyn std::error::Error>> {
        shared.insert("abstractions".to_string(), exec_res.clone());
        Ok(())
    }

    fn get_retry_count(&self) -> usize {
        0
    }
}