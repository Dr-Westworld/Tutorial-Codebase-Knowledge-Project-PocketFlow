// src/github_crawler.rs
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tempfile::TempDir;
use url::Url;
use base64::Engine;
use base64::engine::general_purpose;

#[derive(Debug, Serialize, Deserialize)]
pub struct ContentItem {
    pub name: String,
    pub path: String,
    #[serde(rename = "type")]
    pub item_type: String,
    pub size: Option<u64>,
    pub download_url: Option<String>,
    pub url: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ContentData {
    pub encoding: Option<String>,
    pub content: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Branch {
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct CrawlStats {
    pub downloaded_count: usize,
    pub skipped_count: usize,
    pub skipped_files: Vec<(String, u64)>,
    pub base_path: Option<String>,
    pub include_patterns: Option<HashSet<String>>,
    pub exclude_patterns: Option<HashSet<String>>,
    pub source: Option<String>,
}

#[derive(Debug)]
pub struct CrawlResult {
    pub files: HashMap<String, String>,
    pub stats: CrawlStats,
}

pub fn crawl_github_files(
    repo_url: &str,
    token: Option<&str>,
    max_file_size: u64,
    use_relative_paths: bool,
    include_patterns: Option<HashSet<String>>,
    exclude_patterns: Option<HashSet<String>>,
) -> CrawlResult {
    let should_include_file = |file_path: &str, file_name: &str| -> bool {
        let include_file = if include_patterns.is_none() {
            true
        } else {
            include_patterns
                .as_ref()
                .unwrap()
                .iter()
                .any(|pattern| glob::Pattern::new(pattern).unwrap().matches(file_name))
        };

        if let Some(ref exclude_pats) = exclude_patterns {
            if include_file {
                let exclude_file = exclude_pats
                    .iter()
                    .any(|pattern| glob::Pattern::new(pattern).unwrap().matches(file_path));
                return !exclude_file;
            }
        }

        include_file
    };

    let is_ssh_url = repo_url.starts_with("git@") || repo_url.ends_with(".git");

    if is_ssh_url {
        let tmpdir = TempDir::new().unwrap();
        let tmpdir_path = tmpdir.path();
        println!(
            "Cloning SSH repo {} to temp dir {} ...",
            repo_url,
            tmpdir_path.display()
        );

        match git2::Repository::clone(repo_url, tmpdir_path) {
            Ok(_repo) => {}
            Err(e) => {
                println!("Error cloning repo: {}", e);
                return CrawlResult {
                    files: HashMap::new(),
                    stats: CrawlStats {
                        downloaded_count: 0,
                        skipped_count: 0,
                        skipped_files: Vec::new(),
                        base_path: None,
                        include_patterns: None,
                        exclude_patterns: None,
                        source: Some(format!("error: {}", e)),
                    },
                };
            }
        }

        let mut files = HashMap::new();
        let mut skipped_files = Vec::new();

        fn walk_dir(
            dir: &Path,
            base: &Path,
            files: &mut HashMap<String, String>,
            skipped_files: &mut Vec<(String, u64)>,
            max_file_size: u64,
            should_include: &dyn Fn(&str, &str) -> bool,
        ) {
            if let Ok(entries) = fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        walk_dir(&path, base, files, skipped_files, max_file_size, should_include);
                    } else if path.is_file() {
                        let rel_path = path.strip_prefix(base).unwrap().to_str().unwrap();
                        let filename = path.file_name().unwrap().to_str().unwrap();

                        let file_size = match fs::metadata(&path) {
                            Ok(metadata) => metadata.len(),
                            Err(_) => continue,
                        };

                        if file_size > max_file_size {
                            skipped_files.push((rel_path.to_string(), file_size));
                            println!(
                                "Skipping {}: size {} exceeds limit {}",
                                rel_path, file_size, max_file_size
                            );
                            continue;
                        }

                        if !should_include(rel_path, filename) {
                            println!(
                                "Skipping {}: does not match include/exclude patterns",
                                rel_path
                            );
                            continue;
                        }

                        match fs::read_to_string(&path) {
                            Ok(content) => {
                                files.insert(rel_path.to_string(), content);
                                println!("Added {} ({} bytes)", rel_path, file_size);
                            }
                            Err(e) => {
                                println!("Failed to read {}: {}", rel_path, e);
                            }
                        }
                    }
                }
            }
        }

        walk_dir(
            tmpdir_path,
            tmpdir_path,
            &mut files,
            &mut skipped_files,
            max_file_size,
            &should_include_file,
        );

        let downloaded_count = files.len();
        let skipped_count = skipped_files.len();

        return CrawlResult {
            files,
            stats: CrawlStats {
                downloaded_count,
                skipped_count,
                skipped_files,
                base_path: None,
                include_patterns: include_patterns.clone(),
                exclude_patterns: exclude_patterns.clone(),
                source: Some("ssh_clone".to_string()),
            },
        };
    }

    let parsed_url = Url::parse(repo_url).unwrap();
    let path_parts: Vec<&str> = parsed_url.path().trim_matches('/').split('/').collect();

    if path_parts.len() < 2 {
        panic!("Invalid GitHub URL: {}", repo_url);
    }

    let owner = path_parts[0];
    let repo = path_parts[1];

    let client = Client::builder()
        .user_agent("github-crawler-rust/1.0")
        .build()
        .unwrap();
    
    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(
        "Accept",
        "application/vnd.github.v3+json".parse().unwrap(),
    );
    if let Some(token_val) = token {
        headers.insert(
            "Authorization",
            format!("token {}", token_val).parse().unwrap(),
        );
    }

    let fetch_branches = |owner: &str, repo: &str| -> Vec<Branch> {
        let url = format!("https://api.github.com/repos/{}/{}/branches", owner, repo);
        let response = client
            .get(&url)
            .headers(headers.clone())
            .timeout(Duration::from_secs(30))
            .send();

        match response {
            Ok(resp) => {
                if resp.status() == 404 {
                    if token.is_none() {
                        println!("Error 404: Repository not found or is private.\nIf this is a private repository, please provide a valid GitHub token via the 'token' argument or set the GITHUB_TOKEN environment variable.");
                    } else {
                        println!("Error 404: Repository not found or insufficient permissions with the provided token.\nPlease verify the repository exists and the token has access to this repository.");
                    }
                    return Vec::new();
                }

                if resp.status() != 200 {
                    println!(
                        "Error fetching the branches of {}/{}: {} - {}",
                        owner,
                        repo,
                        resp.status(),
                        resp.text().unwrap_or_default()
                    );
                    return Vec::new();
                }

                resp.json::<Vec<Branch>>().unwrap_or_default()
            }
            Err(_) => Vec::new(),
        }
    };

    let check_tree = |owner: &str, repo: &str, tree: &str| -> bool {
        let url = format!(
            "https://api.github.com/repos/{}/{}/git/trees/{}",
            owner, repo, tree
        );
        let response = client
            .get(&url)
            .headers(headers.clone())
            .timeout(Duration::from_secs(30))
            .send();

        match response {
            Ok(resp) => resp.status() == 200,
            Err(_) => false,
        }
    };

    let (ref_val, specific_path) = if path_parts.len() > 2 && path_parts[2] == "tree" {
        let branches = fetch_branches(owner, repo);

        if branches.is_empty() {
            return CrawlResult {
                files: HashMap::new(),
                stats: CrawlStats {
                    downloaded_count: 0,
                    skipped_count: 0,
                    skipped_files: Vec::new(),
                    base_path: None,
                    include_patterns,
                    exclude_patterns,
                    source: None,
                },
            };
        }

        let relevant_path = path_parts[3..].join("/");

        let mut ref_result = None;
        for branch in &branches {
            if relevant_path.starts_with(&branch.name) {
                ref_result = Some(branch.name.clone());
                break;
            }
        }

        if ref_result.is_none() {
            let tree = path_parts[3];
            if check_tree(owner, repo, tree) {
                ref_result = Some(tree.to_string());
            }
        }

        if ref_result.is_none() {
            println!("The given path does not match with any branch and any tree in the repository.\nPlease verify the path is exists.");
            return CrawlResult {
                files: HashMap::new(),
                stats: CrawlStats {
                    downloaded_count: 0,
                    skipped_count: 0,
                    skipped_files: Vec::new(),
                    base_path: None,
                    include_patterns,
                    exclude_patterns,
                    source: None,
                },
            };
        }

        let ref_str = ref_result.unwrap();
        let part_index = if ref_str.contains('/') { 5 } else { 4 };
        let sp = if part_index < path_parts.len() {
            path_parts[part_index..].join("/")
        } else {
            String::new()
        };

        (Some(ref_str), sp)
    } else {
        (None, String::new())
    };

    let mut files = HashMap::new();
    let mut skipped_files = Vec::new();

    fn fetch_contents(
        owner: &str,
        repo: &str,
        path: &str,
        ref_val: &Option<String>,
        client: &Client,
        headers: &reqwest::header::HeaderMap,
        token: Option<&str>,
        files: &mut HashMap<String, String>,
        skipped_files: &mut Vec<(String, u64)>,
        max_file_size: u64,
        use_relative_paths: bool,
        specific_path: &str,
        should_include_file: &dyn Fn(&str, &str) -> bool,
        exclude_patterns: &Option<HashSet<String>>,
    ) {
        let url = format!(
            "https://api.github.com/repos/{}/{}/contents/{}",
            owner, repo, path
        );

        let mut request = client.get(&url).headers(headers.clone());
        if let Some(ref r) = ref_val {
            request = request.query(&[("ref", r)]);
        }

        let response = request.timeout(Duration::from_secs(30)).send();

        let resp = match response {
            Ok(r) => r,
            Err(_) => return,
        };

        let status = resp.status();
        let resp_headers = resp.headers().clone();
        let resp_text = resp.text().unwrap_or_default();

        if status == 403 && resp_text.to_lowercase().contains("rate limit exceeded") {
            let reset_time = resp_headers
                .get("X-RateLimit-Reset")
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
                .unwrap_or(0);
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let wait_time = if reset_time > now {
                reset_time - now + 1
            } else {
                1
            };
            println!("Rate limit exceeded. Waiting for {} seconds...", wait_time);
            thread::sleep(Duration::from_secs(wait_time));
            return fetch_contents(
                owner,
                repo,
                path,
                ref_val,
                client,
                headers,
                token,
                files,
                skipped_files,
                max_file_size,
                use_relative_paths,
                specific_path,
                should_include_file,
                exclude_patterns,
            );
        }

        if status == 404 {
            if token.is_none() {
                println!("Error 404: Repository not found or is private.\nIf this is a private repository, please provide a valid GitHub token via the 'token' argument or set the GITHUB_TOKEN environment variable.");
            } else if path.is_empty() && ref_val.as_deref() == Some("main") {
                println!("Error 404: Repository not found. Check if the default branch is not 'main'\nTry adding branch name to the request i.e. cargo run -- --repo https://github.com/username/repo/tree/master");
            } else {
                println!("Error 404: Path '{}' not found in repository or insufficient permissions with the provided token.\nPlease verify the token has access to this repository and the path exists.", path);
            }
            return;
        }

        if status != 200 {
            println!(
                "Error fetching {}: {} - {}",
                path,
                status,
                resp_text
            );
            return;
        }

        let contents_result: Result<Vec<ContentItem>, _> = serde_json::from_str(&resp_text);
        let mut contents = match contents_result {
            Ok(c) => c,
            Err(_) => {
                let single_result: Result<ContentItem, _> = serde_json::from_str(&resp_text);
                match single_result {
                    Ok(item) => vec![item],
                    Err(_) => return,
                }
            }
        };

        if contents.is_empty() {
            if let Ok(single) = serde_json::from_str::<ContentItem>(&resp_text) {
                contents = vec![single];
            }
        }

        for item in contents {
            let item_path = &item.path;

            let rel_path = if use_relative_paths && !specific_path.is_empty() {
                if item_path.starts_with(specific_path) {
                    item_path[specific_path.len()..].trim_start_matches('/').to_string()
                } else {
                    item_path.clone()
                }
            } else {
                item_path.clone()
            };

            if item.item_type == "file" {
                if !should_include_file(&rel_path, &item.name) {
                    println!("Skipping {}: Does not match include/exclude patterns", rel_path);
                    continue;
                }

                let file_size = item.size.unwrap_or(0);
                if file_size > max_file_size {
                    skipped_files.push((item_path.clone(), file_size));
                    println!(
                        "Skipping {}: File size ({} bytes) exceeds limit ({} bytes)",
                        rel_path, file_size, max_file_size
                    );
                    continue;
                }

                if let Some(ref download_url) = item.download_url {
                    let file_response = client
                        .get(download_url)
                        .headers(headers.clone())
                        .timeout(Duration::from_secs(30))
                        .send();

                    if let Ok(file_resp) = file_response {
                        let content_length = file_resp
                            .headers()
                            .get("content-length")
                            .and_then(|v| v.to_str().ok())
                            .and_then(|v| v.parse::<u64>().ok())
                            .unwrap_or(0);

                        if content_length > max_file_size {
                            skipped_files.push((item_path.clone(), content_length));
                            println!(
                                "Skipping {}: Content length ({} bytes) exceeds limit ({} bytes)",
                                rel_path, content_length, max_file_size
                            );
                            continue;
                        }

                        if file_resp.status() == 200 {
                            if let Ok(text) = file_resp.text() {
                                files.insert(rel_path.clone(), text);
                                println!("Downloaded: {} ({} bytes) ", rel_path, file_size);
                            }
                        } else {
                            println!("Failed to download {}: {}", rel_path, file_resp.status());
                        }
                    }
                } else {
                    let content_response = client
                        .get(&item.url)
                        .headers(headers.clone())
                        .timeout(Duration::from_secs(30))
                        .send();

                    if let Ok(content_resp) = content_response {
                        if content_resp.status() == 200 {
                            if let Ok(content_data) = content_resp.json::<ContentData>() {
                                if content_data.encoding.as_deref() == Some("base64") {
                                    if let Some(ref content_str) = content_data.content {
                                        let estimated_size = (content_str.len() as f64 * 0.75) as u64;
                                        if estimated_size > max_file_size {
                                            skipped_files.push((item_path.clone(), estimated_size));
                                            println!(
                                                "Skipping {}: Encoded content exceeds size limit",
                                                rel_path
                                            );
                                            continue;
                                        }

                                        let content_clean = content_str.replace('\n', "");
                                        if let Ok(decoded) = general_purpose::STANDARD.decode(&content_clean) {
                                            if let Ok(file_content) = String::from_utf8(decoded) {
                                                files.insert(rel_path.clone(), file_content);
                                                println!("Downloaded: {} ({} bytes)", rel_path, file_size);
                                            }
                                        }
                                    }
                                } else {
                                    println!("Unexpected content format for {}", rel_path);
                                }
                            }
                        } else {
                            println!(
                                "Failed to get content for {}: {}",
                                rel_path,
                                content_resp.status()
                            );
                        }
                    }
                }
            } else if item.item_type == "dir" {
                if let Some(ref exclude_pats) = exclude_patterns {
                    let dir_excluded = exclude_pats.iter().any(|pattern| {
                        glob::Pattern::new(pattern).unwrap().matches(item_path)
                            || glob::Pattern::new(pattern).unwrap().matches(&rel_path)
                    });
                    if dir_excluded {
                        continue;
                    }
                }

                fetch_contents(
                    owner,
                    repo,
                    item_path,
                    ref_val,
                    client,
                    headers,
                    token,
                    files,
                    skipped_files,
                    max_file_size,
                    use_relative_paths,
                    specific_path,
                    should_include_file,
                    exclude_patterns,
                );
            }
        }
    }

    fetch_contents(
        owner,
        repo,
        &specific_path,
        &ref_val,
        &client,
        &headers,
        token,
        &mut files,
        &mut skipped_files,
        max_file_size,
        use_relative_paths,
        &specific_path,
        &should_include_file,
        &exclude_patterns,
    );

    let downloaded_count = files.len();
    let skipped_count = skipped_files.len();
    let base_path = if use_relative_paths {
        Some(specific_path)
    } else {
        None
    };

    CrawlResult {
        files,
        stats: CrawlStats {
            downloaded_count,
            skipped_count,
            skipped_files,
            base_path,
            include_patterns,
            exclude_patterns,
            source: None,
        },
    }
}

#[pyfunction]
#[pyo3(signature = (repo_url, token=None, max_file_size=1048576, use_relative_paths=false, include_patterns=None, exclude_patterns=None))]
pub fn crawl_github_files_py(
    repo_url: &str,
    token: Option<&str>,
    max_file_size: u64,
    use_relative_paths: bool,
    include_patterns: Option<Vec<String>>,
    exclude_patterns: Option<Vec<String>>,
) -> PyResult<(HashMap<String, String>, PyObject)> {
    let include_set = include_patterns.map(|v| v.into_iter().collect());
    let exclude_set = exclude_patterns.map(|v| v.into_iter().collect());
    
    let result = crawl_github_files(
        repo_url,
        token,
        max_file_size,
        use_relative_paths,
        include_set,
        exclude_set,
    );
    
    Python::with_gil(|py| {
        let stats_dict = PyDict::new(py);
        stats_dict.set_item("downloaded_count", result.stats.downloaded_count)?;
        stats_dict.set_item("skipped_count", result.stats.skipped_count)?;
        
        let skipped_list = PyList::new(py, result.stats.skipped_files);
        stats_dict.set_item("skipped_files", skipped_list)?;
        stats_dict.set_item("base_path", result.stats.base_path)?;
        
        let include_list = result.stats.include_patterns.map(|s| {
            PyList::new(py, s.into_iter().collect::<Vec<_>>())
        });
        stats_dict.set_item("include_patterns", include_list)?;
        
        let exclude_list = result.stats.exclude_patterns.map(|s| {
            PyList::new(py, s.into_iter().collect::<Vec<_>>())
        });
        stats_dict.set_item("exclude_patterns", exclude_list)?;
        stats_dict.set_item("source", result.stats.source)?;
        
        Ok((result.files, stats_dict.into()))
    })
}