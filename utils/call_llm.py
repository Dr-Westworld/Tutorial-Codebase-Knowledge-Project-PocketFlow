


import os
import logging
import json
import time
from datetime import datetime
from dotenv import load_dotenv   # NEW

# Load environment variables from .env file
load_dotenv()

# Use the modern Google GenAI SDK
import google.generativeai as genai

# Performance monitoring
from utils.performance_tracker import track_performance
from utils.metrics import MetricsCollector

# Configure logging
log_directory = os.getenv("LOG_DIR", "logs")
os.makedirs(log_directory, exist_ok=True)
log_file = os.path.join(
    log_directory, f"llm_calls_{datetime.now().strftime('%Y%m%d')}.log"
)

logger = logging.getLogger("llm_logger")
logger.setLevel(logging.INFO)
logger.propagate = False
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

# Simple cache configuration
cache_file = os.getenv("LLM_CACHE_FILE", "llm_cache.json")

# Configure the GenAI SDK from .env
_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if _API_KEY:
    genai.configure(api_key=_API_KEY)
    logger.info("Configured google.generativeai from GEMINI_API_KEY")
else:
    logger.warning("GEMINI_API_KEY is not set in .env or environment.")

def _load_cache() -> dict:
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.warning("Failed to load cache - starting with an empty cache")
        return {}

def _save_cache(cache: dict) -> None:
    try:
        tmp_path = cache_file + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_file)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def call_llm(prompt: str, use_cache: bool = True) -> str:
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")

    logger.info(f"PROMPT: {prompt}")

    # Start LLM call timing
    llm_start_time = time.perf_counter()
    # model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    cache_hit = False
    api_status = "success"

    if use_cache:
        cache = _load_cache()
        if prompt in cache:
            logger.info("Cache hit")
            logger.info(f"RESPONSE: {cache[prompt]}")
            # Record cache hit metrics
            llm_duration = time.perf_counter() - llm_start_time
            cache_hit = True
            try:
                MetricsCollector.record_llm_call(
                    model=model_name,
                    use_cache=True,
                    cache_hit=True,
                    duration_sec=llm_duration,
                    status="success"
                )
            except Exception as e:
                logger.warning(f"Error recording LLM cache hit metrics: {e}")
            return cache[prompt]

    if not _API_KEY:
        error_msg = "GEMINI_API_KEY is not set in .env file or environment."
        logger.error(error_msg)
        llm_duration = time.perf_counter() - llm_start_time
        api_status = "error"
        try:
            MetricsCollector.record_llm_call(
                model=model_name,
                use_cache=use_cache,
                cache_hit=False,
                duration_sec=llm_duration,
                status="error"
            )
        except Exception as e:
            logger.warning(f"Error recording LLM error metrics: {e}")
        raise RuntimeError(error_msg)

    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(contents=prompt)

        response_text = getattr(response, "text", None) or str(response)

        logger.info(f"RESPONSE: {response_text}")

        if use_cache:
            cache = _load_cache()
            cache[prompt] = response_text
            _save_cache(cache)

        # Record API call metrics
        llm_duration = time.perf_counter() - llm_start_time
        try:
            MetricsCollector.record_llm_call(
                model=model_name,
                use_cache=use_cache,
                cache_hit=False,
                duration_sec=llm_duration,
                status="success"
            )
        except Exception as e:
            logger.warning(f"Error recording LLM API metrics: {e}")

        return response_text

    except Exception as e:
        logger.exception("LLM call failed")
        # Record failure metrics
        llm_duration = time.perf_counter() - llm_start_time
        try:
            MetricsCollector.record_llm_call(
                model=model_name,
                use_cache=use_cache,
                cache_hit=False,
                duration_sec=llm_duration,
                status="failed"
            )
        except Exception as me:
            logger.warning(f"Error recording LLM failure metrics: {me}")
        raise

if __name__ == "__main__":
    # print("Hello, how are you?")
    # test_prompt = "Hello, how are you?"
    # print("Making call...")
    # try:
    #     response1 = call_llm(test_prompt, use_cache=False)
    #     print(f"Response: {response1}")
    # except Exception as e:
    #     print(f"Call failed: {e}")
    # === added: timing & memory monitoring imports ===
    import time
    import threading
    try:
        import psutil
    except Exception:
        psutil = None
    import tracemalloc
    # === end added ===

    import rust_tools
    # === added: start timers and memory tracking ===
    start_time = time.perf_counter()
    tracemalloc.start()

    mem_samples = []
    mem_stop = threading.Event()

    def _mem_sampler(stop_event, interval=1.0):
        proc = psutil.Process(os.getpid()) if psutil else None
        while not stop_event.is_set():
            t = time.perf_counter() - start_time
            if proc:
                try:
                    rss = proc.memory_info().rss
                except Exception:
                    rss = None
            else:
                rss = None
            mem_samples.append((t, rss))
            time.sleep(interval)

    # Start background sampler (1s interval); safe no-op if psutil missing
    sampler_thread = threading.Thread(target=_mem_sampler, args=(mem_stop, 1.0), daemon=True)
    sampler_thread.start()
    # === end added ===

    print("Hello, how are you?")
    test_prompt = "Hello, how are you?"
    print("Making call...")

    try:
        response = call_llm(test_prompt, use_cache=False)
        print(f"Response: {response}")
    except Exception as e:
        print(f"Call failed: {e}")
    finally:
        # stop memory sampler
        mem_stop.set()
        sampler_thread.join(timeout=2.0)

        elapsed = time.perf_counter() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # compute peak RSS observed (psutil) if available
        peak_rss = None
        if mem_samples:
            rss_values = [s for _, s in mem_samples if s is not None]
            if rss_values:
                peak_rss = max(rss_values)

        print(f"Total elapsed time: {elapsed:.3f} s")
        print(f"tracemalloc: current={current} bytes, peak={peak} bytes")
        if peak_rss is not None:
            print(f"Process peak RSS (observed): {peak_rss / (1024*1024):.2f} MB")
        else:
            print("psutil not available or RSS samples missing. Install psutil to get process RSS measurements.")
    # ...existing code...

#     How are you doing today? And how can I help you?
# Total elapsed time: 4.020 s
# tracemalloc: current=469113 bytes, peak=582297 bytes
# Process peak RSS (observed): 81.54 MB

# How are you today?
# How are you today?
# Total elapsed time: 2.886 s
# tracemalloc: current=17862 bytes, peak=18854 bytes
# Process peak RSS (observed): 24.42 MB