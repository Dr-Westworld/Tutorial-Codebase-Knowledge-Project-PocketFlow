// src/lib.rs
pub mod github_crawler;
pub mod call_local_files;
pub mod llm_caller;
pub mod fetch_repo;
pub mod identify_abstractions;
pub mod analyze_relationships;
pub mod order_chapters; 
pub mod write_chapters;
pub mod tutorial_flow; 

// pub mod context;
// pub mod flow;
// pub mod node;
pub mod pocketflow;
// pub mod utils;

// pub use context::Context;
// pub use flow::*;
// pub use node::*;
// pub use utils::*;

pub type Params = std::collections::HashMap<String, serde_json::Value>;

use pyo3::prelude::*;

#[pymodule]
fn rust_tools(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(github_crawler::crawl_github_files_py, m)?)?;
    m.add_function(wrap_pyfunction!(llm_caller::call_llm_py, m)?)?;
    Ok(())
}