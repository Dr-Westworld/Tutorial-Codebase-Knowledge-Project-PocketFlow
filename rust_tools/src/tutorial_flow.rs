// tutorial_flow.rs
//
// Rust conversion of flow.py — builds and runs the tutorial generation pipeline.
//
// Python original:
//   fetch_repo >> identify_abstractions >> analyze_relationships
//              >> order_chapters >> write_chapters >> combine_tutorial
//
// In Rust we use pocketflow_rs's build_flow! macro and a single
// TutorialState::Default condition (the pipeline is strictly linear).

use pocketflow_rs::{build_flow, Context};
use anyhow::Result;
use serde_json::Value;

use crate::tutorial_nodes::{
    AnalyzeRelationships,
    CombineTutorial,
    FetchRepo,
    IdentifyAbstractions,
    OrderChapters,
    TutorialState,
    WriteChapters,
};

/// Mirrors Python's `create_tutorial_flow()`.
/// Returns a `pocketflow_rs::Flow<TutorialState>` ready to be `.run()`-ed.
///
/// All edge conditions use `TutorialState::Default` because every node in
/// the pipeline succeeds by returning the default state — exactly mirroring
/// the Python `>>` operator which wires nodes with the implicit "default" action.
pub fn create_tutorial_flow() -> pocketflow_rs::Flow<TutorialState> {
    build_flow!(
        // Starting node — mirrors `fetch_repo = FetchRepo()`  +  flow start
        start: ("fetch_repo", FetchRepo),

        // Remaining nodes — mirrors the individual instantiations in Python
        nodes: [
            ("identify_abstractions", IdentifyAbstractions { max_retries: 5, wait_secs: 20 }),
            ("analyze_relationships", AnalyzeRelationships { max_retries: 5, wait_secs: 20 }),
            ("order_chapters",        OrderChapters        { max_retries: 5, wait_secs: 20 }),
            ("write_chapters",        WriteChapters        { max_retries: 5, wait_secs: 20 }),
            ("combine_tutorial",      CombineTutorial)
        ],

        // Linear edges — mirrors `node_a >> node_b` in Python.
        // Each edge fires on TutorialState::Default (the only state we use).
        edges: [
            ("fetch_repo",            "identify_abstractions", TutorialState::Default),
            ("identify_abstractions", "analyze_relationships",  TutorialState::Default),
            ("analyze_relationships", "order_chapters",         TutorialState::Default),
            ("order_chapters",        "write_chapters",         TutorialState::Default),
            ("write_chapters",        "combine_tutorial",       TutorialState::Default)
        ]
    )
}

/// Convenience wrapper that mirrors the expected Python call-site:
///
///   ```python
///   flow = create_tutorial_flow()
///   flow.run(shared)
///   ```
///
/// In Rust the shared dict becomes a `pocketflow_rs::Context` pre-loaded
/// with all the same keys the Python `shared` dict would contain.
///
/// # Parameters
/// All the same keys that the Python caller would put into `shared`:
/// - `repo_url`          – GitHub URL  (or None / absent)
/// - `local_dir`         – local path  (or None / absent)
/// - `github_token`      – optional PAT
/// - `project_name`      – optional override (derived if absent)
/// - `include_patterns`  – JSON array of glob patterns
/// - `exclude_patterns`  – JSON array of glob patterns
/// - `max_file_size`     – integer byte limit
/// - `output_dir`        – base output directory (default "output")
/// - `language`          – tutorial language  (default "english")
/// - `use_cache`         – bool  (default true)
/// - `max_abstraction_num` – integer (default 10)
pub async fn run_tutorial_flow(context: Context) -> Result<Value> {
    let flow = create_tutorial_flow();
    flow.run(context).await
}

// ─────────────────────────────────────────────
// Helper: build a Context from the same keyword arguments
// that Python callers pass to `flow.run(shared)`.
// ─────────────────────────────────────────────
/// Build a [`Context`] suitable for [`run_tutorial_flow`].
///
/// # Example
/// ```rust
/// let ctx = TutorialContextBuilder::new()
///     .local_dir("/path/to/repo")
///     .language("english")
///     .output_dir("output")
///     .max_file_size(100_000)
///     .build();
///
/// run_tutorial_flow(ctx).await?;
/// ```
pub struct TutorialContextBuilder {
    context: Context,
}

impl TutorialContextBuilder {
    pub fn new() -> Self {
        use serde_json::json;
        let mut context = Context::new();
        // Sensible defaults that mirror the Python shared-dict defaults
        context.set("include_patterns", json!([]));
        context.set("exclude_patterns", json!([]));
        context.set("max_file_size",    json!(100_000_u64));
        context.set("output_dir",       json!("output"));
        context.set("language",         json!("english"));
        context.set("use_cache",        json!(true));
        context.set("max_abstraction_num", json!(10_u64));
        Self { context }
    }

    pub fn repo_url(mut self, url: &str) -> Self {
        self.context.set("repo_url", serde_json::json!(url));
        self
    }

    pub fn local_dir(mut self, dir: &str) -> Self {
        self.context.set("local_dir", serde_json::json!(dir));
        self
    }

    pub fn github_token(mut self, token: &str) -> Self {
        self.context.set("github_token", serde_json::json!(token));
        self
    }

    pub fn project_name(mut self, name: &str) -> Self {
        self.context.set("project_name", serde_json::json!(name));
        self
    }

    pub fn include_patterns(mut self, patterns: Vec<&str>) -> Self {
        self.context.set("include_patterns", serde_json::json!(patterns));
        self
    }

    pub fn exclude_patterns(mut self, patterns: Vec<&str>) -> Self {
        self.context.set("exclude_patterns", serde_json::json!(patterns));
        self
    }

    pub fn max_file_size(mut self, size: u64) -> Self {
        self.context.set("max_file_size", serde_json::json!(size));
        self
    }

    pub fn output_dir(mut self, dir: &str) -> Self {
        self.context.set("output_dir", serde_json::json!(dir));
        self
    }

    pub fn language(mut self, lang: &str) -> Self {
        self.context.set("language", serde_json::json!(lang));
        self
    }

    pub fn use_cache(mut self, flag: bool) -> Self {
        self.context.set("use_cache", serde_json::json!(flag));
        self
    }

    pub fn max_abstraction_num(mut self, n: u64) -> Self {
        self.context.set("max_abstraction_num", serde_json::json!(n));
        self
    }

    pub fn build(self) -> Context {
        self.context
    }
}

impl Default for TutorialContextBuilder {
    fn default() -> Self {
        Self::new()
    }
}

// ─────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    /// Smoke-test: the flow should be constructable without panicking.
    #[test]
    fn test_create_flow_does_not_panic() {
        let _flow = create_tutorial_flow();
    }

    /// Smoke-test: the builder should produce a Context with expected keys.
    #[test]
    fn test_context_builder_defaults() {
        let ctx = TutorialContextBuilder::new().build();
        assert!(ctx.get("include_patterns").is_some());
        assert!(ctx.get("exclude_patterns").is_some());
        assert!(ctx.get("max_file_size").is_some());
        assert!(ctx.get("output_dir").is_some());
        assert!(ctx.get("language").is_some());
        assert!(ctx.get("use_cache").is_some());
        assert!(ctx.get("max_abstraction_num").is_some());
    }

    #[test]
    fn test_context_builder_with_values() {
        let ctx = TutorialContextBuilder::new()
            .local_dir("/tmp/myrepo")
            .language("spanish")
            .max_file_size(50_000)
            .use_cache(false)
            .build();

        assert_eq!(ctx.get("local_dir").unwrap(), "/tmp/myrepo");
        assert_eq!(ctx.get("language").unwrap(), "spanish");
        assert_eq!(ctx.get("max_file_size").unwrap(), 50_000_u64);
        assert_eq!(ctx.get("use_cache").unwrap(), false);
    }
}
