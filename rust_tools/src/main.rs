// src/main.rs
use dotenv::dotenv;
use std::env;
use std::collections::HashSet;
use clap::{Arg, ArgAction, Command};
use serde_json::json;
use pocketflow_rs::SharedState;

mod fetch_repo;
mod call_local_files;
mod github_crawler;
mod llm_caller;
mod identify_abstractions;
mod analyze_relationships;
mod order_chapters;
mod write_chapters;
mod tutorial_flow;

use tutorial_flow::create_tutorial_flow;

fn get_default_include_patterns() -> HashSet<String> {
    vec![
        "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.java", "*.pyi", "*.pyx",
        "*.c", "*.cc", "*.cpp", "*.h", "*.md", "*.rst", "*Dockerfile",
        "*Makefile", "*.yaml", "*.yml",
    ]
    .into_iter()
    .map(|s| s.to_string())
    .collect()
}

fn get_default_exclude_patterns() -> HashSet<String> {
    vec![
        "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*",
        "*docs/*",
        "*venv/*",
        "*.venv/*",
        "*test*",
        "*tests/*",
        "*examples/*",
        "v1/*",
        "*dist/*",
        "*build/*",
        "*experimental/*",
        "*deprecated/*",
        "*misc/*",
        "*legacy/*",
        ".git/*", ".github/*", ".next/*", ".vscode/*",
        "*obj/*",
        "*bin/*",
        "*node_modules/*",
        "*.log",
    ]
    .into_iter()
    .map(|s| s.to_string())
    .collect()
}

fn main() {
    dotenv().ok();

    let matches = Command::new("AI Codebase Knowledge Builder")
        .about("Generate a tutorial for a GitHub codebase or local directory.")
        .arg(
            Arg::new("repo")
                .long("repo")
                .value_name("URL")
                .help("URL of the public GitHub repository.")
                .conflicts_with("dir")
        )
        .arg(
            Arg::new("dir")
                .long("dir")
                .value_name("PATH")
                .help("Path to local directory.")
                .conflicts_with("repo")
        )
        .arg(
            Arg::new("name")
                .short('n')
                .long("name")
                .value_name("NAME")
                .help("Project name (optional, derived from repo/directory if omitted).")
        )
        .arg(
            Arg::new("token")
                .short('t')
                .long("token")
                .value_name("TOKEN")
                .help("GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).")
        )
        .arg(
            Arg::new("output")
                .short('o')
                .long("output")
                .value_name("DIR")
                .default_value("output")
                .help("Base directory for output (default: ./output).")
        )
        .arg(
            Arg::new("include")
                .short('i')
                .long("include")
                .value_name("PATTERNS")
                .num_args(1..)
                .help("Include file patterns (e.g. '*.py' '*.js'). Defaults to common code files if not specified.")
        )
        .arg(
            Arg::new("exclude")
                .short('e')
                .long("exclude")
                .value_name("PATTERNS")
                .num_args(1..)
                .help("Exclude file patterns (e.g. 'tests/*' 'docs/*'). Defaults to test/build directories if not specified.")
        )
        .arg(
            Arg::new("max-size")
                .short('s')
                .long("max-size")
                .value_name("BYTES")
                .default_value("100000")
                .value_parser(clap::value_parser!(u64))
                .help("Maximum file size in bytes (default: 100000, about 100KB).")
        )
        .arg(
            Arg::new("language")
                .long("language")
                .value_name("LANG")
                .default_value("english")
                .help("Language for the generated tutorial (default: english)")
        )
        .arg(
            Arg::new("no-cache")
                .long("no-cache")
                .action(ArgAction::SetTrue)
                .help("Disable LLM response caching (default: caching enabled)")
        )
        .arg(
            Arg::new("max-abstractions")
                .long("max-abstractions")
                .value_name("NUM")
                .default_value("10")
                .value_parser(clap::value_parser!(u64))
                .help("Maximum number of abstractions to identify (default: 10)")
        )
        .get_matches();

    let repo = matches.get_one::<String>("repo").map(|s| s.as_str());
    let dir = matches.get_one::<String>("dir").map(|s| s.as_str());

    if repo.is_none() && dir.is_none() {
        eprintln!("Error: Either --repo or --dir must be provided.");
        std::process::exit(1);
    }

    let name = matches.get_one::<String>("name").map(|s| s.as_str());
    let token_arg = matches.get_one::<String>("token").map(|s| s.as_str());
    let output = matches.get_one::<String>("output").map(|s| s.as_str()).unwrap();
    let max_size = *matches.get_one::<u64>("max-size").unwrap();
    let language = matches.get_one::<String>("language").map(|s| s.as_str()).unwrap();
    let no_cache = matches.get_flag("no-cache");
    let max_abstractions = *matches.get_one::<u64>("max-abstractions").unwrap();

    let github_token = if repo.is_some() {
        let token = token_arg
            .map(|s| s.to_string())
            .or_else(|| env::var("GITHUB_TOKEN").ok());
        
        if token.is_none() {
            println!("Warning: No GitHub token provided. You might hit rate limits for public repositories.");
        }
        token
    } else {
        None
    };

    let include_patterns: HashSet<String> = if let Some(patterns) = matches.get_many::<String>("include") {
        patterns.map(|s| s.to_string()).collect()
    } else {
        get_default_include_patterns()
    };

    let exclude_patterns: HashSet<String> = if let Some(patterns) = matches.get_many::<String>("exclude") {
        patterns.map(|s| s.to_string()).collect()
    } else {
        get_default_exclude_patterns()
    };

    let mut shared = SharedState::new();
    
    if let Some(r) = repo {
        shared.insert("repo_url".to_string(), json!(r));
    }
    if let Some(d) = dir {
        shared.insert("local_dir".to_string(), json!(d));
    }
    if let Some(n) = name {
        shared.insert("project_name".to_string(), json!(n));
    }
    if let Some(t) = github_token {
        shared.insert("github_token".to_string(), json!(t));
    }
    
    shared.insert("output_dir".to_string(), json!(output));
    shared.insert("include_patterns".to_string(), json!(include_patterns.into_iter().collect::<Vec<_>>()));
    shared.insert("exclude_patterns".to_string(), json!(exclude_patterns.into_iter().collect::<Vec<_>>()));
    shared.insert("max_file_size".to_string(), json!(max_size));
    shared.insert("language".to_string(), json!(language));
    shared.insert("use_cache".to_string(), json!(!no_cache));
    shared.insert("max_abstraction_num".to_string(), json!(max_abstractions));
    shared.insert("files".to_string(), json!(Vec::<String>::new()));
    shared.insert("abstractions".to_string(), json!(Vec::<String>::new()));
    shared.insert("relationships".to_string(), json!({}));
    shared.insert("chapter_order".to_string(), json!(Vec::<usize>::new()));
    shared.insert("chapters".to_string(), json!(Vec::<String>::new()));
    shared.insert("final_output_dir".to_string(), json!(null));

    let source = repo.or(dir).unwrap();
    let lang_cap = language.chars().next().unwrap().to_uppercase().collect::<String>() + &language[1..];
    println!("Starting tutorial generation for: {} in {} language", source, lang_cap);
    println!("LLM caching: {}", if no_cache { "Disabled" } else { "Enabled" });

    let mut tutorial_flow = create_tutorial_flow();
    
    match tutorial_flow.run(&mut shared) {
        Ok(_) => {
            println!("Tutorial generation completed successfully!");
        }
        Err(e) => {
            eprintln!("Error during tutorial generation: {}", e);
            std::process::exit(1);
        }
    }
} 