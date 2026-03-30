import math
import sys
from dataclasses import dataclass

try:
    import psutil
except ImportError:
    psutil = None


# -----------------------------
# Utilities
# -----------------------------
def bytes_to_human(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024:
            return f"{x:.2f} {u}"
        x /= 1024
    return f"{x:.2f} PB"


def sizeof_python_object(obj) -> int:
    seen = set()

    def inner(o):
        oid = id(o)
        if oid in seen:
            return 0
        seen.add(oid)

        size = sys.getsizeof(o)

        if isinstance(o, dict):
            size += sum(inner(k) + inner(v) for k, v in o.items())
        elif isinstance(o, (list, tuple, set, frozenset)):
            size += sum(inner(i) for i in o)

        return size

    return inner(obj)


def current_process_memory() -> dict:
    if psutil is None:
        return {"rss": None, "vms": None}
    p = psutil.Process()
    mem = p.memory_info()
    return {"rss": mem.rss, "vms": mem.vms}


# -----------------------------
# Toy tokenizer
# -----------------------------
def simple_tokenize(text: str):
    tokens = []
    current = []
    for ch in text:
        if ch.isalnum() or ch in ["'", "_"]:
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
            if not ch.isspace():
                tokens.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def token_to_id(token: str, vocab_size: int = 50000) -> int:
    return abs(hash(token)) % vocab_size


# -----------------------------
# Config
# -----------------------------
@dataclass
class ModelConfig:
    context_limit: int = 64      # total allowed tokens
    reserve_output: int = 16     # tokens kept aside for the reply
    d_model: int = 32
    n_layers: int = 2
    n_heads: int = 4
    vocab_size: int = 5000
    dtype_bytes: int = 2         # fp16/bf16 = 2, fp32 = 4


# -----------------------------
# Memory estimates
# -----------------------------
def estimate_embedding_bytes(seq_len: int, d_model: int, dtype_bytes: int) -> int:
    return seq_len * d_model * dtype_bytes


def estimate_attention_bytes(seq_len: int, n_heads: int, dtype_bytes: int) -> int:
    return n_heads * seq_len * seq_len * dtype_bytes


def estimate_kv_cache_bytes(seq_len: int, n_layers: int, n_heads: int, head_dim: int, dtype_bytes: int) -> int:
    return 2 * n_layers * seq_len * n_heads * head_dim * dtype_bytes


def estimate_logits_bytes(seq_len: int, vocab_size: int, dtype_bytes: int) -> int:
    return seq_len * vocab_size * dtype_bytes


def estimate_token_ids_bytes(seq_len: int) -> int:
    return seq_len * 4  # int32


# -----------------------------
# Context check
# -----------------------------
def check_context(seq_len: int, cfg: ModelConfig):
    """
    Returns:
        allowed_input_tokens: how many input tokens fit after reserve_output
        fits: bool
        message: str
    """
    allowed_input_tokens = cfg.context_limit - cfg.reserve_output
    if allowed_input_tokens < 0:
        allowed_input_tokens = 0

    if seq_len > allowed_input_tokens:
        msg = (
            f"Rejected: prompt is too large.\n"
            f"  prompt_tokens = {seq_len}\n"
            f"  max_input_tokens = {allowed_input_tokens}\n"
            f"  context_limit = {cfg.context_limit}\n"
            f"  reserved_for_output = {cfg.reserve_output}\n"
            f"  total_if_accepted = {seq_len + cfg.reserve_output} > {cfg.context_limit}"
        )
        return allowed_input_tokens, False, msg

    msg = (
        f"Accepted: prompt fits.\n"
        f"  prompt_tokens = {seq_len}\n"
        f"  max_input_tokens = {allowed_input_tokens}\n"
        f"  context_limit = {cfg.context_limit}\n"
        f"  reserved_for_output = {cfg.reserve_output}\n"
        f"  total_if_accepted = {seq_len + cfg.reserve_output} <= {cfg.context_limit}"
    )
    return allowed_input_tokens, True, msg


# -----------------------------
# Simulation
# -----------------------------
def simulate(prompt: str, cfg: ModelConfig):
    print("=" * 80)
    print("PROMPT")
    print("=" * 80)
    print(prompt)
    print()

    proc_mem = current_process_memory()
    if proc_mem["rss"] is not None:
        print("Current Python process memory:")
        print(f"  RSS: {bytes_to_human(proc_mem['rss'])}")
        print(f"  VMS: {bytes_to_human(proc_mem['vms'])}")
        print()

    print("=" * 80)
    print("STAGE 1 — RAW TEXT")
    print("=" * 80)
    print(f"Character count: {len(prompt)}")
    print(f"UTF-8 byte count: {len(prompt.encode('utf-8'))}")
    print(f"Python object size (approx): {bytes_to_human(sizeof_python_object(prompt))}")
    print()

    tokens = simple_tokenize(prompt)
    token_ids = [token_to_id(t, cfg.vocab_size) for t in tokens]
    seq_len = len(token_ids)

    print("=" * 80)
    print("STAGE 2 — TOKENIZATION")
    print("=" * 80)
    print(f"Token count: {seq_len}")
    print(f"Tokens: {tokens}")
    print(f"Token IDs: {token_ids}")
    print(f"Token IDs memory (int32 estimate): {bytes_to_human(estimate_token_ids_bytes(seq_len))}")
    print()

    allowed_input_tokens, fits, msg = check_context(seq_len, cfg)

    print("=" * 80)
    print("CONTEXT CHECK")
    print("=" * 80)
    print(msg)
    print()

    print("=" * 80)
    print("LIMITS")
    print("=" * 80)
    print(f"Context limit: {cfg.context_limit} tokens")
    print(f"Reserved for output: {cfg.reserve_output} tokens")
    print(f"Maximum input tokens allowed: {allowed_input_tokens} tokens")
    print()

    if not fits:
        print("=" * 80)
        print("STOPPED")
        print("=" * 80)
        print("The prompt was rejected before running the model.")
        return {
            "accepted": False,
            "reason": msg,
            "prompt_tokens": seq_len,
            "max_input_tokens": allowed_input_tokens,
            "context_limit": cfg.context_limit,
        }

    # If it fits, continue with the memory estimates
    emb_bytes = estimate_embedding_bytes(seq_len, cfg.d_model, cfg.dtype_bytes)
    head_dim = cfg.d_model // cfg.n_heads
    attn_bytes_per_layer = estimate_attention_bytes(seq_len, cfg.n_heads, cfg.dtype_bytes)
    kv_bytes = estimate_kv_cache_bytes(seq_len, cfg.n_layers, cfg.n_heads, head_dim, cfg.dtype_bytes)
    logits_bytes = estimate_logits_bytes(seq_len, cfg.vocab_size, cfg.dtype_bytes)

    print("=" * 80)
    print("STAGE 3 — EMBEDDINGS")
    print("=" * 80)
    print(f"Tensor shape: [{seq_len}, {cfg.d_model}]")
    print(f"Embedding tensor memory: {bytes_to_human(emb_bytes)}")
    print()

    print("=" * 80)
    print("STAGE 4 — SELF-ATTENTION")
    print("=" * 80)
    print(f"Tensor shape per layer: [{cfg.n_heads}, {seq_len}, {seq_len}]")
    print(f"Attention memory per layer: {bytes_to_human(attn_bytes_per_layer)}")
    print(f"Attention memory for all layers: {bytes_to_human(attn_bytes_per_layer * cfg.n_layers)}")
    print()

    print("=" * 80)
    print("STAGE 5 — KV CACHE")
    print("=" * 80)
    print(f"Head dimension: {head_dim}")
    print(f"KV cache memory: {bytes_to_human(kv_bytes)}")
    print()

    print("=" * 80)
    print("STAGE 6 — LOGITS")
    print("=" * 80)
    print(f"Tensor shape: [{seq_len}, {cfg.vocab_size}]")
    print(f"Logits memory: {bytes_to_human(logits_bytes)}")
    print()

    total_estimated = (
        estimate_token_ids_bytes(seq_len)
        + emb_bytes
        + (attn_bytes_per_layer * cfg.n_layers)
        + kv_bytes
        + logits_bytes
    )

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Prompt accepted: yes")
    print(f"Estimated total working memory: {bytes_to_human(total_estimated)}")
    print()

    return {
        "accepted": True,
        "prompt_tokens": seq_len,
        "max_input_tokens": allowed_input_tokens,
        "context_limit": cfg.context_limit,
        "token_ids": token_ids,
        "embedding_bytes": emb_bytes,
        "attention_bytes_total": attn_bytes_per_layer * cfg.n_layers,
        "kv_cache_bytes": kv_bytes,
        "logits_bytes": logits_bytes,
        "total_estimated": total_estimated,
    }


if __name__ == "__main__":
    cfg = ModelConfig(
        context_limit=32,   # total tokens allowed
        reserve_output=8,   # keep room for the reply
        d_model=32,
        n_layers=2,
        n_heads=4,
        vocab_size=5000,
        dtype_bytes=2
    )

    prompt = "hello how are you doing today, this is a small demo for testing for my major project that is needed for my university."
    simulate(prompt, cfg)