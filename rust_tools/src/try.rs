use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use sysinfo::{System, SystemExt};

#[derive(Debug, Clone)]
struct ModelConfig {
    context_limit: usize,
    d_model: usize,
    n_layers: usize,
    n_heads: usize,
    vocab_size: usize,
    dtype_bytes: usize, // fp16/bf16 = 2, fp32 = 4
}

fn bytes_to_human(n: usize) -> String {
    let units = ["B", "KB", "MB", "GB", "TB", "PB"];
    let mut value = n as f64;
    let mut idx = 0usize;

    while value >= 1024.0 && idx < units.len() - 1 {
        value /= 1024.0;
        idx += 1;
    }

    format!("{:.2} {}", value, units[idx])
}

fn simple_tokenize(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut current = String::new();

    for ch in text.chars() {
        if ch.is_alphanumeric() || ch == '\'' || ch == '_' {
            current.push(ch);
        } else {
            if !current.is_empty() {
                tokens.push(current.clone());
                current.clear();
            }
            if !ch.is_whitespace() {
                tokens.push(ch.to_string());
            }
        }
    }

    if !current.is_empty() {
        tokens.push(current);
    }

    tokens
}

fn token_to_id(token: &str, vocab_size: usize) -> usize {
    let mut hasher = DefaultHasher::new();
    token.hash(&mut hasher);
    (hasher.finish() as usize) % vocab_size
}

fn estimate_token_ids_bytes(seq_len: usize) -> usize {
    seq_len * 4 // int32
}

fn estimate_embedding_bytes(seq_len: usize, d_model: usize, dtype_bytes: usize) -> usize {
    seq_len * d_model * dtype_bytes
}

fn estimate_attention_bytes(seq_len: usize, n_heads: usize, dtype_bytes: usize) -> usize {
    // [heads, seq_len, seq_len]
    n_heads * seq_len * seq_len * dtype_bytes
}

fn estimate_kv_cache_bytes(
    seq_len: usize,
    n_layers: usize,
    n_heads: usize,
    head_dim: usize,
    dtype_bytes: usize,
) -> usize {
    // K and V for each layer
    2 * n_layers * seq_len * n_heads * head_dim * dtype_bytes
}

fn estimate_logits_bytes(seq_len: usize, vocab_size: usize, dtype_bytes: usize) -> usize {
    seq_len * vocab_size * dtype_bytes
}

fn current_process_memory() -> Option<(u64, u64)> {
    let mut sys = System::new_all();
    sys.refresh_all();

    let pid = sysinfo::get_current_pid().ok()?;
    let proc = sys.process(pid)?;

    // memory() returns KB in sysinfo
    let rss = proc.memory() * 1024;
    let vms = proc.virtual_memory() * 1024;
    Some((rss, vms))
}

fn simulate(prompt: &str, cfg: &ModelConfig) {
    println!("{}", "=".repeat(80));
    println!("PROMPT");
    println!("{}", "=".repeat(80));
    println!("{}", prompt);
    println!();

    if let Some((rss, vms)) = current_process_memory() {
        println!("Current Rust process memory:");
        println!("  RSS: {}", bytes_to_human(rss as usize));
        println!("  VMS: {}", bytes_to_human(vms as usize));
        println!();
    }

    println!("{}", "=".repeat(80));
    println!("STAGE 1 — RAW TEXT");
    println!("{}", "=".repeat(80));
    println!("Character count: {}", prompt.chars().count());
    println!("UTF-8 byte count: {}", prompt.as_bytes().len());
    println!(
        "Approx string memory (very rough): {}",
        bytes_to_human(std::mem::size_of_val(prompt))
    );
    println!();

    let tokens = simple_tokenize(prompt);
    let token_ids: Vec<usize> = tokens
        .iter()
        .map(|t| token_to_id(t, cfg.vocab_size))
        .collect();

    let seq_len = token_ids.len();

    println!("{}", "=".repeat(80));
    println!("STAGE 2 — TOKENIZATION");
    println!("{}", "=".repeat(80));
    println!("Token count: {}", seq_len);
    println!("Tokens: {:?}", tokens);
    println!("Token IDs: {:?}", token_ids);
    println!(
        "Token IDs memory (int32 estimate): {}",
        bytes_to_human(estimate_token_ids_bytes(seq_len))
    );
    println!();

    println!("{}", "=".repeat(80));
    println!("CONTEXT CHECK");
    println!("{}", "=".repeat(80));
    if seq_len > cfg.context_limit {
        println!(
            "WARNING: prompt exceeds context limit ({} > {})",
            seq_len, cfg.context_limit
        );
    } else {
        println!("Fits in context window: {} / {}", seq_len, cfg.context_limit);
    }
    println!();

    let emb_bytes = estimate_embedding_bytes(seq_len, cfg.d_model, cfg.dtype_bytes);
    println!("{}", "=".repeat(80));
    println!("STAGE 3 — EMBEDDINGS");
    println!("{}", "=".repeat(80));
    println!("Tensor shape: [{}, {}]", seq_len, cfg.d_model);
    println!("Embedding tensor memory: {}", bytes_to_human(emb_bytes));
    println!();

    let head_dim = cfg.d_model / cfg.n_heads;
    let attn_bytes_per_layer = estimate_attention_bytes(seq_len, cfg.n_heads, cfg.dtype_bytes);
    println!("{}", "=".repeat(80));
    println!("STAGE 4 — SELF-ATTENTION");
    println!("{}", "=".repeat(80));
    println!(
        "Tensor shape per layer: [{}, {}, {}]",
        cfg.n_heads, seq_len, seq_len
    );
    println!(
        "Attention memory per layer: {}",
        bytes_to_human(attn_bytes_per_layer)
    );
    println!(
        "Attention memory for all layers: {}",
        bytes_to_human(attn_bytes_per_layer * cfg.n_layers)
    );
    println!();

    let kv_bytes =
        estimate_kv_cache_bytes(seq_len, cfg.n_layers, cfg.n_heads, head_dim, cfg.dtype_bytes);
    println!("{}", "=".repeat(80));
    println!("STAGE 5 — KV CACHE");
    println!("{}", "=".repeat(80));
    println!("Head dimension: {}", head_dim);
    println!("KV cache memory: {}", bytes_to_human(kv_bytes));
    println!();

    let logits_bytes = estimate_logits_bytes(seq_len, cfg.vocab_size, cfg.dtype_bytes);
    println!("{}", "=".repeat(80));
    println!("STAGE 6 — LOGITS");
    println!("{}", "=".repeat(80));
    println!("Tensor shape: [{}, {}]", seq_len, cfg.vocab_size);
    println!("Logits memory: {}", bytes_to_human(logits_bytes));
    println!();

    let total_estimated = estimate_token_ids_bytes(seq_len)
        + emb_bytes
        + attn_bytes_per_layer * cfg.n_layers
        + kv_bytes
        + logits_bytes;

    println!("{}", "=".repeat(80));
    println!("SUMMARY");
    println!("{}", "=".repeat(80));
    println!(
        "Estimated total working memory: {}",
        bytes_to_human(total_estimated)
    );
    println!("Model config:");
    println!("  context_limit = {}", cfg.context_limit);
    println!("  d_model       = {}", cfg.d_model);
    println!("  n_layers      = {}", cfg.n_layers);
    println!("  n_heads       = {}", cfg.n_heads);
    println!("  vocab_size    = {}", cfg.vocab_size);
    println!("  dtype_bytes   = {}", cfg.dtype_bytes);
    println!();
}

fn main() {
    let cfg = ModelConfig {
        context_limit: 64,
        d_model: 32,
        n_layers: 2,
        n_heads: 4,
        vocab_size: 5000,
        dtype_bytes: 2, // fp16-style estimate
    };

    let prompt = "hello how are you doing today, this is a small demo";
    simulate(prompt, &cfg);
}