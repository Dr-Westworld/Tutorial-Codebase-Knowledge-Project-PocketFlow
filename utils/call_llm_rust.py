# # python/use_llm.py
# import os
# from dotenv import load_dotenv
# import rust_tools

# load_dotenv()

# print("Hello, how are you?")
# test_prompt = "Hello, how are you?"
# print("Making call...")

# try:
#     response = rust_tools.call_llm_py(test_prompt, use_cache=False)
#     print(f"Response: {response}")
# except Exception as e:
#     print(f"Call failed: {e}")

# ...existing code...
import os
from dotenv import load_dotenv

# === added: ensure repo root is on sys.path so imports like `from rust import rust_tools` work ===
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
# === end added ===

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
# ...existing code...
load_dotenv()

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
    response = rust_tools.call_llm_py(test_prompt, use_cache=False)
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