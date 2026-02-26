// src/llm_caller.rs
use pyo3::prelude::*;
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, Write};
use std::path::Path;
use chrono::Local;
use log::{info, warn, error};

#[derive(Debug, Serialize, Deserialize)]
struct GenerateContentRequest {
    contents: Vec<Content>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Content {
    parts: Vec<Part>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Part {
    text: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct GenerateContentResponse {
    candidates: Option<Vec<Candidate>>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Candidate {
    content: ContentResponse,
}

#[derive(Debug, Serialize, Deserialize)]
struct ContentResponse {
    parts: Vec<PartResponse>,
}

#[derive(Debug, Serialize, Deserialize)]
struct PartResponse {
    text: String,
}

fn load_cache(cache_file: &str) -> HashMap<String, String> {
    if !Path::new(cache_file).exists() {
        return HashMap::new();
    }
    
    match File::open(cache_file) {
        Ok(file) => {
            let reader = BufReader::new(file);
            match serde_json::from_reader(reader) {
                Ok(cache) => cache,
                Err(_) => {
                    warn!("Failed to load cache - starting with an empty cache");
                    HashMap::new()
                }
            }
        }
        Err(_) => {
            warn!("Failed to open cache file - starting with an empty cache");
            HashMap::new()
        }
    }
}

fn save_cache(cache: &HashMap<String, String>, cache_file: &str) {
    let tmp_path = format!("{}.tmp", cache_file);
    
    match File::create(&tmp_path) {
        Ok(mut file) => {
            match serde_json::to_string_pretty(cache) {
                Ok(json_str) => {
                    if file.write_all(json_str.as_bytes()).is_ok() {
                        let _ = fs::rename(&tmp_path, cache_file);
                    } else {
                        error!("Failed to write cache to temporary file");
                    }
                }
                Err(e) => {
                    error!("Failed to serialize cache: {}", e);
                }
            }
        }
        Err(e) => {
            error!("Failed to create temporary cache file: {}", e);
        }
    }
}

pub fn call_llm(prompt: &str, use_cache: bool) -> Result<String, Box<dyn std::error::Error>> {
    info!("PROMPT: {}", prompt);
    
    let cache_file = env::var("LLM_CACHE_FILE").unwrap_or_else(|_| "llm_cache.json".to_string());
    
    if use_cache {
        let cache = load_cache(&cache_file);
        if let Some(cached_response) = cache.get(prompt) {
            info!("Cache hit");
            info!("RESPONSE: {}", cached_response);
            return Ok(cached_response.clone());
        }
    }
    
    let api_key = env::var("GEMINI_API_KEY")
        .map_err(|_| "GEMINI_API_KEY is not set in .env file or environment.")?;
    
    if api_key.trim().is_empty() {
        error!("GEMINI_API_KEY is not set in .env file or environment.");
        return Err("GEMINI_API_KEY is not set in .env file or environment.".into());
    }
    
    let model_name = env::var("GEMINI_MODEL").unwrap_or_else(|_| "gemini-2.0-flash-exp".to_string());
    
    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
        model_name, api_key
    );
    
    let request_body = GenerateContentRequest {
        contents: vec![Content {
            parts: vec![Part {
                text: prompt.to_string(),
            }],
        }],
    };
    
    let client = Client::new();
    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&request_body)
        .send()?;
    
    if !response.status().is_success() {
        let error_text = response.text()?;
        error!("LLM call failed: {}", error_text);
        return Err(format!("LLM call failed: {}", error_text).into());
    }
    
    let response_data: GenerateContentResponse = response.json()?;
    
    let response_text = response_data
    .candidates
    .and_then(| candidates| candidates.into_iter().next())
    .map(|candidate| {
        candidate
            .content
            .parts
            .into_iter()
            .map(|part| part.text) // move the Strings out
            .collect::<Vec<_>>()
            .join("")
    })
    .ok_or("No response text found")?;

    info!("RESPONSE: {}", response_text);
    
    if use_cache {
        let mut cache = load_cache(&cache_file);
        cache.insert(prompt.to_string(), response_text.clone());
        save_cache(&cache, &cache_file);
    }
    
    Ok(response_text)
}

pub fn setup_logger() {
    let log_directory = env::var("LOG_DIR").unwrap_or_else(|_| "logs".to_string());
    fs::create_dir_all(&log_directory).ok();
    
    let log_file = format!(
        "{}/llm_calls_{}.log",
        log_directory,
        Local::now().format("%Y%m%d")
    );
    
    let target = Box::new(
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_file)
            .expect("Failed to open log file")
    );
    
    env_logger::Builder::new()
        .target(env_logger::Target::Pipe(target))
        .filter_level(log::LevelFilter::Info)
        .format(|buf, record| {
            writeln!(
                buf,
                "{} - {} - {}",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                record.level(),
                record.args()
            )
        })
        .init();
}

#[pyfunction]
#[pyo3(signature = (prompt, use_cache=true))]
pub fn call_llm_py(prompt: &str, use_cache: bool) -> PyResult<String> {
    setup_logger();
    
    match call_llm(prompt, use_cache) {
        Ok(response) => Ok(response),
        Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
    }
}