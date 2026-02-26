//! PocketFlow: A workflow orchestration library for Rust
//!
//! This library provides a flexible framework for building complex workflows
//! with nodes that can be chained together using the `>>` operator.
//!
//! # Examples
//!
//! ```rust
//! use pocketflow::{Node, Flow, SharedData, NodeBase};
//! use std::error::Error;
//! 
//! #[derive(Clone)]
//! struct FetchNode {
//!     base: NodeBase,
//! }
//!
//! impl FetchNode {
//!     fn new() -> Self {
//!         Self { base: NodeBase::default() }
//!     }
//! }
//!
//! pocketflow::impl_node!(FetchNode);
//!
//! impl Node for FetchNode {
//!     fn exec(&mut self, _prep_res: &dyn std::any::Any) -> Result<Box<dyn std::any::Any>, Box<dyn Error>> {
//!         Ok(Box::new("fetched data".to_string()))
//!     }
//! }
//!
//! // Chain nodes using >>
//! let mut fetch = FetchNode::new();
//! let process = ProcessNode::new();
//! fetch >> process;
//!
//! // Create flow
//! let flow = Flow::start(fetch);
//! ```

use std::any::Any;
use std::collections::HashMap;
use std::error::Error;
use std::fmt;
use std::thread;
use std::time::Duration;

pub use async_impl::{
    AsyncBatchFlow, AsyncBatchNode, AsyncFlow, AsyncNode, AsyncParallelBatchFlow,
    AsyncParallelBatchNode,
};

/// Shared data passed between nodes in a workflow
pub type SharedData = HashMap<String, Box<dyn Any + Send>>;

/// Node parameters
pub type Params = HashMap<String, ParamValue>;

/// Supported parameter value types
#[derive(Debug, Clone)]
pub enum ParamValue {
    String(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    None,
    List(Vec<ParamValue>),
    Map(HashMap<String, ParamValue>),
}

impl From<String> for ParamValue {
    fn from(s: String) -> Self {
        Self::String(s)
    }
}

impl From<&str> for ParamValue {
    fn from(s: &str) -> Self {
        Self::String(s.to_string())
    }
}

impl From<i64> for ParamValue {
    fn from(i: i64) -> Self {
        Self::Int(i)
    }
}

impl From<i32> for ParamValue {
    fn from(i: i32) -> Self {
        Self::Int(i as i64)
    }
}

impl From<f64> for ParamValue {
    fn from(f: f64) -> Self {
        Self::Float(f)
    }
}

impl From<bool> for ParamValue {
    fn from(b: bool) -> Self {
        Self::Bool(b)
    }
}

/// PocketFlow error types
#[derive(Debug)]
pub enum FlowError {
    ExecutionError(String),
    TransitionError(String),
    NodeError(Box<dyn Error + Send>),
}

impl fmt::Display for FlowError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ExecutionError(msg) => write!(f, "Execution error: {}", msg),
            Self::TransitionError(msg) => write!(f, "Transition error: {}", msg),
            Self::NodeError(err) => write!(f, "Node error: {}", err),
        }
    }
}

impl Error for FlowError {}

/// Base functionality for all nodes
pub struct NodeBase {
    params: Params,
    successors: HashMap<String, Box<dyn NodeTrait>>,
    max_retries: usize,
    wait_ms: u64,
}

impl NodeBase {
    /// Create a new node base with retry configuration
    #[must_use]
    pub fn new(max_retries: usize, wait_ms: u64) -> Self {
        Self {
            params: HashMap::new(),
            successors: HashMap::new(),
            max_retries,
            wait_ms,
        }
    }

    /// Create with default settings (1 retry, no wait)
    #[must_use]
    pub fn default() -> Self {
        Self::new(1, 0)
    }
}

impl Clone for NodeBase {
    fn clone(&self) -> Self {
        Self {
            params: self.params.clone(),
            successors: HashMap::new(), // Don't clone successors to avoid deep copies
            max_retries: self.max_retries,
            wait_ms: self.wait_ms,
        }
    }
}

/// Internal trait for node operations
pub trait NodeTrait: Send {
    fn set_params(&mut self, params: Params);
    fn params(&self) -> &Params;
    fn add_successor(&mut self, action: String, node: Box<dyn NodeTrait>);
    fn get_successor(&self, action: &str) -> Option<&Box<dyn NodeTrait>>;
    fn has_successors(&self) -> bool;
    fn run_internal(&mut self, shared: &mut SharedData) -> Result<Option<String>, Box<dyn Error>>;
    fn clone_box(&self) -> Box<dyn NodeTrait>;
}

/// Main trait for workflow nodes
pub trait Node: NodeTrait {
    /// Preparation phase - gather data needed for execution
    fn prep(&mut self, _shared: &mut SharedData) -> Result<Box<dyn Any>, Box<dyn Error>> {
        Ok(Box::new(()))
    }

    /// Execution phase - perform the main operation
    fn exec(&mut self, prep_res: &dyn Any) -> Result<Box<dyn Any>, Box<dyn Error>>;

    /// Post-processing phase - finalize and determine next action
    fn post(
        &mut self,
        _shared: &mut SharedData,
        _prep_res: &dyn Any,
        _exec_res: &dyn Any,
    ) -> Result<Option<String>, Box<dyn Error>> {
        Ok(None)
    }

    /// Fallback handler for execution failures
    fn exec_fallback(
        &mut self,
        _prep_res: &dyn Any,
        exc: Box<dyn Error>,
    ) -> Result<Box<dyn Any>, Box<dyn Error>> {
        Err(exc)
    }

    /// Access to base node
    fn base(&self) -> &NodeBase;
    
    /// Mutable access to base node
    fn base_mut(&mut self) -> &mut NodeBase;

    /// Execute with retry logic
    fn exec_with_retry(&mut self, prep_res: &dyn Any) -> Result<Box<dyn Any>, Box<dyn Error>> {
        let max_retries = self.base().max_retries;
        let wait_ms = self.base().wait_ms;

        for retry in 0..max_retries {
            match self.exec(prep_res) {
                Ok(result) => return Ok(result),
                Err(e) => {
                    if retry == max_retries - 1 {
                        return self.exec_fallback(prep_res, e);
                    }
                    if wait_ms > 0 {
                        thread::sleep(Duration::from_millis(wait_ms));
                    }
                }
            }
        }
        unreachable!()
    }
}

/// Macro to implement NodeTrait for custom nodes
#[macro_export]
macro_rules! impl_node {
    ($type:ty) => {
        impl NodeTrait for $type {
            fn set_params(&mut self, params: Params) {
                self.base.params = params;
            }

            fn params(&self) -> &Params {
                &self.base.params
            }

            fn add_successor(&mut self, action: String, node: Box<dyn NodeTrait>) {
                if self.base.successors.contains_key(&action) {
                    eprintln!("Warning: Overwriting successor for action '{}'", action);
                }
                self.base.successors.insert(action, node);
            }

            fn get_successor(&self, action: &str) -> Option<&Box<dyn NodeTrait>> {
                self.base.successors.get(action)
            }

            fn has_successors(&self) -> bool {
                !self.base.successors.is_empty()
            }

            fn run_internal(
                &mut self,
                shared: &mut SharedData,
            ) -> Result<Option<String>, Box<dyn std::error::Error>> {
                if self.has_successors() {
                    eprintln!("Warning: Node won't run successors. Use Flow.");
                }

                let prep_res = self.prep(shared)?;
                let exec_res = self.exec_with_retry(prep_res.as_ref())?;
                self.post(shared, prep_res.as_ref(), exec_res.as_ref())
            }

            fn clone_box(&self) -> Box<dyn NodeTrait> {
                Box::new(self.clone())
            }
        }
    };
}

/// Trait for batch processing nodes
pub trait BatchNode: Node {
    /// Execute batch processing on items from prep
    fn exec_batch(
        &mut self,
        items: &[Box<dyn Any>],
    ) -> Result<Vec<Box<dyn Any>>, Box<dyn Error>> {
        items
            .iter()
            .map(|item| self.exec_with_retry(item.as_ref()))
            .collect()
    }
}

/// Implements the `>>` operator for chaining nodes
impl<T: Node + Clone + 'static> std::ops::Shr<T> for T {
    type Output = T;

    fn shr(mut self, other: T) -> Self::Output {
        self.base_mut()
            .add_successor("default".to_string(), Box::new(other));
        self
    }
}

/// Flow orchestrates multiple nodes in sequence
pub struct Flow {
    start_node: Box<dyn NodeTrait>,
    params: Params,
}

impl Flow {
    /// Create a new flow with a starting node
    #[must_use]
    pub fn start<T: Node + 'static>(node: T) -> Self {
        Self {
            start_node: Box::new(node),
            params: HashMap::new(),
        }
    }

    /// Set flow-level parameters
    pub fn with_params(mut self, params: Params) -> Self {
        self.params = params;
        self
    }

    /// Get the next node based on current node and action
    fn get_next_node(
        curr: &dyn NodeTrait,
        action: Option<&str>,
    ) -> Option<&Box<dyn NodeTrait>> {
        let action_key = action.unwrap_or("default");
        let next = curr.get_successor(action_key);

        if next.is_none() && curr.has_successors() {
            eprintln!(
                "Warning: Flow ends: '{}' not found in available successors",
                action_key
            );
        }

        next
    }

    /// Orchestrate the flow execution
    fn orchestrate(
        &mut self,
        shared: &mut SharedData,
        params: Option<Params>,
    ) -> Result<Option<String>, Box<dyn Error>> {
        let params = params.unwrap_or_else(|| self.params.clone());
        
        let mut current = self.start_node.clone_box();
        current.set_params(params.clone());

        let mut last_action = current.run_internal(shared)?;

        // Navigate through successors
        loop {
            let next = match Self::get_next_node(current.as_ref(), last_action.as_deref()) {
                Some(n) => n.clone_box(),
                None => break,
            };

            current = next;
            current.set_params(params.clone());
            last_action = current.run_internal(shared)?;
        }

        Ok(last_action)
    }

    /// Run the flow orchestration
    pub fn run(&mut self, shared: &mut SharedData) -> Result<Option<String>, Box<dyn Error>> {
        self.orchestrate(shared, None)
    }
}

/// Batch flow for processing multiple parameter sets
pub struct BatchFlow {
    start_node: Box<dyn NodeTrait>,
    params: Params,
}

impl BatchFlow {
    /// Create a new batch flow
    #[must_use]
    pub fn start<T: Node + 'static>(node: T) -> Self {
        Self {
            start_node: Box::new(node),
            params: HashMap::new(),
        }
    }

    /// Run the batch flow with multiple parameter sets
    pub fn run(
        &mut self,
        shared: &mut SharedData,
        batch_params: Vec<Params>,
    ) -> Result<(), Box<dyn Error>> {
        for params in batch_params {
            let mut merged_params = self.params.clone();
            merged_params.extend(params);

            let mut current = self.start_node.clone_box();
            current.set_params(merged_params);
            current.run_internal(shared)?;
        }
        Ok(())
    }
}

/// Async implementation module
pub mod async_impl {
    use super::*;
    use std::future::Future;
    use std::pin::Pin;

    /// Async version of the Node trait
    pub trait AsyncNode: NodeTrait {
        /// Async preparation phase
        fn prep_async<'a>(
            &'a mut self,
            shared: &'a mut SharedData,
        ) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any>, Box<dyn Error>>> + Send + 'a>>;

        /// Async execution phase
        fn exec_async<'a>(
            &'a mut self,
            prep_res: &'a dyn Any,
        ) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any>, Box<dyn Error>>> + Send + 'a>>;

        /// Async post-processing phase
        fn post_async<'a>(
            &'a mut self,
            shared: &'a mut SharedData,
            prep_res: &'a dyn Any,
            exec_res: &'a dyn Any,
        ) -> Pin<Box<dyn Future<Output = Result<Option<String>, Box<dyn Error>>> + Send + 'a>>;

        /// Async fallback handler
        fn exec_fallback_async<'a>(
            &'a mut self,
            _prep_res: &'a dyn Any,
            exc: Box<dyn Error>,
        ) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any>, Box<dyn Error>>> + Send + 'a>> {
            Box::pin(async move { Err(exc) })
        }
    }

    /// Async batch node trait
    pub trait AsyncBatchNode: AsyncNode {}

    /// Async parallel batch node trait
    pub trait AsyncParallelBatchNode: AsyncBatchNode {}

    /// Async flow orchestrator
    pub struct AsyncFlow {
        start_node: Box<dyn AsyncNode>,
        params: Params,
    }

    impl AsyncFlow {
        /// Create a new async flow
        #[must_use]
        pub fn start<T: AsyncNode + 'static>(node: T) -> Self {
            Self {
                start_node: Box::new(node),
                params: HashMap::new(),
            }
        }
    }

    /// Async batch flow
    pub struct AsyncBatchFlow {
        start_node: Box<dyn AsyncBatchNode>,
        params: Params,
    }

    impl AsyncBatchFlow {
        /// Create a new async batch flow
        #[must_use]
        pub fn start<T: AsyncBatchNode + 'static>(node: T) -> Self {
            Self {
                start_node: Box::new(node),
                params: HashMap::new(),
            }
        }
    }

    /// Async parallel batch flow
    pub struct AsyncParallelBatchFlow {
        start_node: Box<dyn AsyncParallelBatchNode>,
        params: Params,
    }

    impl AsyncParallelBatchFlow {
        /// Create a new async parallel batch flow
        #[must_use]
        pub fn start<T: AsyncParallelBatchNode + 'static>(node: T) -> Self {
            Self {
                start_node: Box::new(node),
                params: HashMap::new(),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone)]
    struct TestNode {
        base: NodeBase,
        value: i32,
    }

    impl TestNode {
        fn new(value: i32) -> Self {
            Self {
                base: NodeBase::default(),
                value,
            }
        }
    }

    impl Node for TestNode {
        fn base(&self) -> &NodeBase {
            &self.base
        }

        fn base_mut(&mut self) -> &mut NodeBase {
            &mut self.base
        }

        fn exec(&mut self, _prep_res: &dyn Any) -> Result<Box<dyn Any>, Box<dyn Error>> {
            Ok(Box::new(self.value * 2))
        }

        fn post(
            &mut self,
            _shared: &mut SharedData,
            _prep_res: &dyn Any,
            exec_res: &dyn Any,
        ) -> Result<Option<String>, Box<dyn Error>> {
            let result = exec_res
                .downcast_ref::<i32>()
                .ok_or("Type mismatch")?;
            assert_eq!(*result, self.value * 2);
            Ok(None)
        }
    }

    impl_node!(TestNode);

    #[test]
    fn test_node_execution() {
        let mut node = TestNode::new(21);
        let mut shared = SharedData::new();

        let result = node.run_internal(&mut shared);
        assert!(result.is_ok());
    }

    #[test]
    fn test_node_chaining() {
        let node1 = TestNode::new(10);
        let node2 = TestNode::new(20);

        let _chain = node1 >> node2;
    }

    #[test]
    fn test_flow_execution() {
        let node1 = TestNode::new(10);
        let mut flow = Flow::start(node1);
        let mut shared = SharedData::new();

        let result = flow.run(&mut shared);
        assert!(result.is_ok());
    }
}