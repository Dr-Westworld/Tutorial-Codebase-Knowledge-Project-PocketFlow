// src/fetch_repo.rs
use anyhow::{anyhow, Result};
use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashSet;
use std::path::Path;
use std::sync::Arc;

// Allow using this module either as part of the same crate (crate::...)
// or using the external pocketflow_rs crate if you enable the feature
// `external_pocketflow` in Cargo.toml. This lets you compile the same file
// in both contexts without manual edits.
#[cfg(feature = "external_pocketflow")]
use pocketflow_rs::{Context, Node, Params, ProcessResult, BaseState};

#[cfg(not(feature = "external_pocketflow"))]
use crate::{context::Context, node::Node, params::Params, node::{ProcessResult, BaseState}};

use crate::github_crawler::crawl_github_files;
use crate::call_local_files::crawl_local_files;

/// Node implementation that prepares repo parameters, crawls (github or local)
/// and stores files into the context. This implementation uses the async Node
/// trait from the official PocketFlow-Rust repo (prepare / execute / post_process).
pub struct FetchRepo {
    // optional params holder (keeps parity with other nodes)
    pub params: Option<Params>,
}

impl Default for FetchRepo {
    fn default() -> Self {
        Self { params: None }
    }
}

#[async_trait]
impl Node for FetchRepo {
    type State = BaseState;

    /// Prepare: read values from context and put a `prep_result` into context
    async fn prepare(&self, context: &mut Context) -> Result<()> {
        // read from context (Shared store)
        let repo_url = context.get("repo_url").and_then(|v| v.as_str()).map(|s| s.to_string());
        let local_dir = context.get("local_dir").and_then(|v| v.as_str()).map(|s| s.to_string());
        let mut project_name = context.get("project_name").and_then(|v| v.as_str()).map(|s| s.to_string());

        if project_name.is_none() {
            if let Some(ref url) = repo_url {
                project_name = Some(
                    url.split('/')
                        .last()
                        .unwrap_or("unknown")
                        .replace(".git", ""),
                );
            } else if let Some(ref dir) = local_dir {
                project_name = Some(
                    Path::new(dir)
                        .file_name()
                        .and_then(|n| n.to_str())
                        .unwrap_or("unknown")
                        .to_string(),
                );
            }

            if let Some(ref name) = project_name {
                context.set("project_name", Value::String(name.clone()));
            }
        }

        let include_patterns = context
            .get("include_patterns")
            .and_then(|v| v.as_array().cloned())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect::<Vec<_>>());

        let exclude_patterns = context
            .get("exclude_patterns")
            .and_then(|v| v.as_array().cloned())
            .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect::<Vec<_>>());

        let max_file_size = context
            .get("max_file_size")
            .and_then(|v| v.as_u64())
            .unwrap_or(1 * 1024 * 1024);

        let token = context.get("github_token").and_then(|v| v.as_str()).map(|s| s.to_string());

        let prep_result = serde_json::json!({
            "repo_url": repo_url,
            "local_dir": local_dir,
            "token": token,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "max_file_size": max_file_size,
            "use_relative_paths": true
        });

        context.set("prep_result", prep_result);
        Ok(())
    }

    /// Execute: read `prep_result` from context, perform crawling (github or local).
    /// Because crawling functions are blocking, run them in spawn_blocking.
    async fn execute(&self, context: &Context) -> Result<Value> {
        // Read prep_result from context
        let prep_res = context
            .get("prep_result")
            .ok_or_else(|| anyhow!("prep_result not found in context"))?;

        // Extract fields (note these are Option<&Value> from Context API)
        let repo_url = prep_res.get("repo_url").and_then(|v| v.as_str()).map(|s| s.to_string());
        let local_dir = prep_res.get("local_dir").and_then(|v| v.as_str()).map(|s| s.to_string());
        let token = prep_res.get("token").and_then(|v| v.as_str()).map(|s| s.to_string());

        let include_patterns = prep_res
            .get("include_patterns")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect::<HashSet<_>>()
            });

        let exclude_patterns = prep_res
            .get("exclude_patterns")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect::<HashSet<_>>()
            });

        let max_file_size = prep_res
            .get("max_file_size")
            .and_then(|v| v.as_u64())
            .unwrap_or(1 * 1024 * 1024) as usize;

        let use_relative_paths = prep_res
            .get("use_relative_paths")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);

        // Perform blocking work inside spawn_blocking
        let crawl_result = if let Some(url) = repo_url {
            // call blocking crawl_github_files
            let token_clone = token.clone();
            tokio::task::spawn_blocking(move || {
                crawl_github_files(
                    &url,
                    token_clone.as_deref(),
                    max_file_size,
                    use_relative_paths,
                    include_patterns,
                    exclude_patterns,
                )
            })
            .await?
        } else if let Some(dir) = local_dir {
            tokio::task::spawn_blocking(move || {
                crawl_local_files(
                    &dir,
                    include_patterns,
                    exclude_patterns,
                    max_file_size,
                    use_relative_paths,
                )
            })
            .await?
        } else {
            return Err(anyhow!("Either repo_url or local_dir must be provided"));
        };

        // `crawl_result` is expected to be a struct with `files` & `stats` fields.
        // Convert files map into Vec<(String, String)> similar to original code
        let files_vec: Vec<(String, String)> = crawl_result.files.into_iter().collect();

        if files_vec.is_empty() {
            return Err(anyhow!("Failed to fetch files or repository contained no files"));
        }

        // Return files list as a JSON value
        Ok(serde_json::to_value(files_vec)?)
    }

    /// post_process: store the execution result into context (shared store) and return default ProcessResult
    async fn post_process(
        &self,
        context: &mut Context,
        result: &Result<Value>,
    ) -> Result<ProcessResult<Self::State>> {
        match result {
            Ok(value) => {
                // store files in `files` key
                context.set("files", value.clone());
                Ok(ProcessResult::default())
            }
            Err(e) => {
                context.set("error", Value::String(e.to_string()));
                Ok(ProcessResult::new(Self::State::default(), e.to_string()))
            }
        }
    }
}

/// Helper function to get content for specific file indices
/// Returns a HashMap with keys like "0 # path/to/file" and values as file content
pub fn get_content_for_indices(
    files_data: &[(String, String)],
    indices: &[usize],
) -> std::collections::HashMap<String, String> {
    let mut content_map = std::collections::HashMap::new();
    for &i in indices {
        if i < files_data.len() {
            let (path, content) = &files_data[i];
            content_map.insert(format!("{} # {}", i, path), content.clone());
        }
    }
    content_map
}

//
// -- Tests --
// Add tests that exercise prepare -> execute -> post_process flow using a temporary directory.
// These tests assume `Context` implements `new()`, `set(key, Value)` and `get(key) -> Option<&Value>`
// which is how the PocketFlow-Rust Context API is used above. If your `Context` API differs,
// adapt the tests accordingly.
//

// #[cfg(test)]
// mod tests {
//     use super::*;
//     use serde_json::json;
//     use tempfile::tempdir;
//     use tokio;

//     #[cfg(feature = "external_pocketflow")]
//     fn make_context() -> Context {
//         Context::new()
//     }

//     #[cfg(not(feature = "external_pocketflow"))]
//     fn make_context() -> Context {
//         Context::new()
//     }

//     // NEW: Test fetching a real small public GitHub repo
//     #[tokio::test]
//     async fn test_fetch_public_github_repo() {
//         let mut ctx = make_context();

//         // Lightweight, public Rust repo for testing:
//         // https://github.com/rust-lang/rustlings
//         ctx.set("repo_url", Value::String("https://github.com/rust-lang/rustlings".into()));
//         ctx.set("max_file_size", Value::Number(serde_json::Number::from(50000))); // 50KB
//         ctx.set("include_patterns", json!(["*.rs", "*.md"]));
//         ctx.set("exclude_patterns", json!([".git", "target"]));

//         let node = FetchRepo::default();
//         node.prepare(&mut ctx).await.expect("prepare ok");

//         // This will make a real GitHub API call, so it may take a few seconds.
//         // You can optionally add a GitHub token in your .env file if you hit rate limits.
//         let exec_val = node.execute(&ctx).await.expect("execute ok");

//         // We expect some Rust files in the repo.
//         let arr = exec_val.as_array().expect("execute returned array");
//         assert!(
//             !arr.is_empty(),
//             "Should fetch at least one file from rustlings repo"
//         );

//         node.post_process(&mut ctx, &Ok(exec_val)).await.expect("post_process ok");
//         assert!(ctx.get("files").is_some(), "files should be saved");
//     }

//     #[tokio::test]
//     async fn test_prepare_missing_prep_result() {
//         let ctx = make_context();
//         let node = FetchRepo::default();
//         let exec_res = node.execute(&ctx).await;
//         assert!(exec_res.is_err(), "execute without prep_result should fail");
//     }
// }
