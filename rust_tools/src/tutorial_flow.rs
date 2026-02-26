// src/tutorial_flow.rs
use pocketflow_rs::Flow;
use crate::fetch_repo::FetchRepo;
use crate::identify_abstractions::IdentifyAbstractions;
use crate::analyze_relationships::AnalyzeRelationships;
use crate::order_chapters::OrderChapters;
use crate::write_chapters::{WriteChapters, CombineTutorial};

pub fn create_tutorial_flow() -> Flow {
    let fetch_repo = FetchRepo;
    // let identify_abstractions = IdentifyAbstractions::with_retries(5, 20);
    // let analyze_relationships = AnalyzeRelationships::with_retries(5, 20);
    // let order_chapters = OrderChapters::with_retries(5, 20);
    // let write_chapters = WriteChapters::new().with_retries(5, 20);
    let identify_abstractions = IdentifyAbstractions;
    let analyze_relationships = AnalyzeRelationships;
    let order_chapters = OrderChapters;
    let write_chapters = WriteChapters::new();
    let combine_tutorial = CombineTutorial;

    let mut flow = Flow::new();
    
    flow.add_node("fetch_repo", Box::new(fetch_repo));
    flow.add_node("identify_abstractions", Box::new(identify_abstractions));
    flow.add_node("analyze_relationships", Box::new(analyze_relationships));
    flow.add_node("order_chapters", Box::new(order_chapters));
    flow.add_node("write_chapters", Box::new(write_chapters));
    flow.add_node("combine_tutorial", Box::new(combine_tutorial));
    
    flow.connect("fetch_repo", "identify_abstractions");
    flow.connect("identify_abstractions", "analyze_relationships");
    flow.connect("analyze_relationships", "order_chapters");
    flow.connect("order_chapters", "write_chapters");
    flow.connect("write_chapters", "combine_tutorial");
    
    flow.set_start("fetch_repo");
    
    flow
}