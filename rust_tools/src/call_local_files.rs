// src/call_local_files.rs
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;

#[derive(Debug)]
pub struct CrawlStats {
    pub downloaded_count: usize,
    pub skipped_count: usize,
    pub skipped_files: Vec<(String, u64)>,
    pub base_path: Option<String>,
    pub include_patterns: Option<HashSet<String>>,
    pub exclude_patterns: Option<HashSet<String>>,
}

#[derive(Debug)]
pub struct CrawlResult {
    pub files: HashMap<String, String>,
    pub stats: CrawlStats,
}

pub fn crawl_local_files(
    directory: &str,
    include_patterns: Option<HashSet<String>>,
    exclude_patterns: Option<HashSet<String>>,
    max_file_size: u64,
    use_relative_paths: bool,
) -> CrawlResult {
    let mut files = HashMap::new();
    let mut skipped_files = Vec::new();

    let base_path = Path::new(directory);

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

    fn walk_dir(
        dir: &Path,
        base: &Path,
        files: &mut HashMap<String, String>,
        skipped_files: &mut Vec<(String, u64)>,
        max_file_size: u64,
        use_relative_paths: bool,
        should_include: &dyn Fn(&str, &str) -> bool,
    ) {
        if let Ok(entries) = fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    walk_dir(&path, base, files, skipped_files, max_file_size, use_relative_paths, should_include);
                } else if path.is_file() {
                    let rel_path = if use_relative_paths {
                        path.strip_prefix(base).unwrap().to_str().unwrap()
                    } else {
                        path.to_str().unwrap()
                    };
                    
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
        base_path,
        base_path,
        &mut files,
        &mut skipped_files,
        max_file_size,
        use_relative_paths,
        &should_include_file,
    );

    let downloaded_count = files.len();
    let skipped_count = skipped_files.len();

    CrawlResult {
        files,
        stats: CrawlStats {
            downloaded_count,
            skipped_count,
            skipped_files,
            base_path: if use_relative_paths {
                Some(directory.to_string())
            } else {
                None
            },
            include_patterns,
            exclude_patterns,
        },
    }
}