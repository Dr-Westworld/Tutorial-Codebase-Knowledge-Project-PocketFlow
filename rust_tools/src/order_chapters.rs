// src/order_chapters.rs
use pocketflow_rs::{Node, SharedState};
use serde_json::Value;
use yaml_rust::YamlLoader;
use crate::llm_caller::call_llm;
use crate::identify_abstractions::Abstraction;
use crate::analyze_relationships::RelationshipsData;

pub struct OrderChapters;

impl Node for OrderChapters {
    fn prep(&self, shared: &mut SharedState) -> Result<Value, Box<dyn std::error::Error>> {
        let abstractions = shared.get("abstractions")
            .and_then(|v| serde_json::from_value::<Vec<Abstraction>>(v.clone()).ok())
            .ok_or("abstractions not found in shared state")?;
        
        let relationships = shared.get("relationships")
            .and_then(|v| serde_json::from_value::<RelationshipsData>(v.clone()).ok())
            .ok_or("relationships not found in shared state")?;
        
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

        let abstraction_info_for_prompt: Vec<String> = abstractions.iter()
            .enumerate()
            .map(|(i, a)| format!("- {} # {}", i, a.name))
            .collect();
        
        let abstraction_listing = abstraction_info_for_prompt.join("\n");

        let mut summary_note = String::new();
        if language.to_lowercase() != "english" {
            let lang_cap = language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..];
            summary_note = format!(" (Note: Project Summary might be in {})", lang_cap);
        }

        let mut context = format!("Project Summary{}:\n{}\n\n", summary_note, relationships.summary);
        context.push_str("Relationships (Indices refer to abstractions above):\n");
        
        for rel in &relationships.details {
            let from_name = &abstractions[rel.from].name;
            let to_name = &abstractions[rel.to].name;
            context.push_str(&format!("- From {} ({}) to {} ({}): {}\n", 
                rel.from, from_name, rel.to, to_name, rel.label));
        }

        let mut list_lang_note = String::new();
        if language.to_lowercase() != "english" {
            let lang_cap = language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..];
            list_lang_note = format!(" (Names might be in {})", lang_cap);
        }

        Ok(serde_json::json!({
            "abstraction_listing": abstraction_listing,
            "context": context,
            "num_abstractions": abstractions.len(),
            "project_name": project_name,
            "list_lang_note": list_lang_note,
            "use_cache": use_cache
        }))
    }

    fn exec(&self, prep_res: &Value) -> Result<Value, Box<dyn std::error::Error>> {
        let abstraction_listing = prep_res.get("abstraction_listing").and_then(|v| v.as_str()).unwrap();
        let context = prep_res.get("context").and_then(|v| v.as_str()).unwrap();
        let num_abstractions = prep_res.get("num_abstractions").and_then(|v| v.as_u64()).unwrap() as usize;
        let project_name = prep_res.get("project_name").and_then(|v| v.as_str()).unwrap();
        let list_lang_note = prep_res.get("list_lang_note").and_then(|v| v.as_str()).unwrap();
        let use_cache = prep_res.get("use_cache").and_then(|v| v.as_bool()).unwrap();

        println!("Determining chapter order using LLM...");

        let prompt = format!(r#"
Given the following project abstractions and their relationships for the project ```` {} ````:

Abstractions (Index # Name){}:
{}

Context about relationships and project summary:
{}

If you are going to make a tutorial for ```` {} ````, what is the best order to explain these abstractions, from first to last?
Ideally, first explain those that are the most important or foundational, perhaps user-facing concepts or entry points. Then move to more detailed, lower-level implementation details or supporting concepts.

Output the ordered list of abstraction indices, including the name in a comment for clarity. Use the format `idx # AbstractionName`.
```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
- 1 # CoreClassB (uses CoreClassA)
- ...
```

Now, provide the YAML output:
"#, project_name, list_lang_note, abstraction_listing, context, project_name);

        let cur_retry = self.get_retry_count();
        let response = call_llm(&prompt, use_cache && cur_retry == 0)?;

        let yaml_str = response.trim()
            .split("```yaml").nth(1)
            .ok_or("YAML block not found")?
            .split("```").next()
            .ok_or("YAML block end not found")?
            .trim();

        let docs = YamlLoader::load_from_str(yaml_str)?;
        let ordered_yaml = docs.get(0).ok_or("No YAML document found")?;

        let ordered_indices_raw = ordered_yaml.as_vec()
            .ok_or("LLM output is not a list")?;

        let mut ordered_indices = Vec::new();
        let mut seen_indices = std::collections::HashSet::new();

        for entry in ordered_indices_raw {
            let idx = if let Some(int_val) = entry.as_i64() {
                int_val as usize
            } else if let Some(str_val) = entry.as_str() {
                if str_val.contains('#') {
                    str_val.split('#').next().unwrap().trim().parse::<usize>()?
                } else {
                    str_val.trim().parse::<usize>()?
                }
            } else {
                return Err(format!("Could not parse index from ordered list entry: {:?}", entry).into());
            };

            if idx >= num_abstractions {
                return Err(format!("Invalid index {} in ordered list. Max index is {}.", idx, num_abstractions - 1).into());
            }
            
            if seen_indices.contains(&idx) {
                return Err(format!("Duplicate index {} found in ordered list.", idx).into());
            }
            
            ordered_indices.push(idx);
            seen_indices.insert(idx);
        }

        if ordered_indices.len() != num_abstractions {
            let missing: Vec<usize> = (0..num_abstractions)
                .filter(|i| !seen_indices.contains(i))
                .collect();
            return Err(format!("Ordered list length ({}) does not match number of abstractions ({}). Missing indices: {:?}", 
                ordered_indices.len(), num_abstractions, missing).into());
        }

        println!("Determined chapter order (indices): {:?}", ordered_indices);
        Ok(serde_json::to_value(ordered_indices)?)
    }

    fn post(&self, shared: &mut SharedState, _prep_res: &Value, exec_res: &Value) -> Result<(), Box<dyn std::error::Error>> {
        shared.insert("chapter_order".to_string(), exec_res.clone());
        Ok(())
    }

    fn get_retry_count(&self) -> usize {
        0
    }
}