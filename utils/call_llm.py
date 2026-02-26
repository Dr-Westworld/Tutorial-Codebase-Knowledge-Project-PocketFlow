# # from google import genai
# # import os
# # import logging
# # import json
# # from datetime import datetime

# import os
# import logging
# import json
# from datetime import datetime

# # Use the modern Google GenAI SDK
# import google.generativeai as genai

# # Configure logging
# log_directory = os.getenv("LOG_DIR", "logs")
# os.makedirs(log_directory, exist_ok=True)
# log_file = os.path.join(
#     log_directory, f"llm_calls_{datetime.now().strftime('%Y%m%d')}.log"
# )

# # Set up logger
# logger = logging.getLogger("llm_logger")
# logger.setLevel(logging.INFO)
# logger.propagate = False  # Prevent propagation to root logger
# file_handler = logging.FileHandler(log_file, encoding='utf-8')
# file_handler.setFormatter(
#     logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
# )
# logger.addHandler(file_handler)

# # Simple cache configuration
# cache_file = "llm_cache.json"


# # Configure the GenAI SDK at module import
# _API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# if _API_KEY:
#     genai.configure(api_key=_API_KEY)
#     logger.info("Configured google.generativeai from GEMINI_API_KEY")
# else:
#     logger.warning("GEMINI_API_KEY is not set. Calls will fail until key is provided in the environment.")

# def _load_cache() -> dict:
#     if not os.path.exists(cache_file):
#         return {}
#     try:
#         with open(cache_file, "r", encoding="utf-8") as f:
#             return json.load(f) or {}
#     except Exception:
#         logger.warning("Failed to load cache - starting with an empty cache")
#         return {}

# def _save_cache(cache: dict) -> None:
#     try:
#         # Write atomically: write to a temp file then rename
#         tmp_path = cache_file + ".tmp"
#         with open(tmp_path, "w", encoding="utf-8") as f:
#             json.dump(cache, f, ensure_ascii=False, indent=2)
#         os.replace(tmp_path, cache_file)
#     except Exception as e:
#         logger.error(f"Failed to save cache: {e}")

# def call_llm(prompt: str, use_cache: bool = True) -> str:
#     """Call the configured Gemini model and return text.

#     Uses a simple on-disk JSON cache when use_cache=True.
#     """
#     if not isinstance(prompt, str):
#         raise TypeError("prompt must be a string")

#     logger.info(f"PROMPT: {prompt}")

#     # Try cache
#     if use_cache:
#         cache = _load_cache()
#         if prompt in cache:
#             logger.info("Cache hit")
#             logger.info(f"RESPONSE: {cache[prompt]}")
#             return cache[prompt]

#     # Ensure the SDK is configured
#     if not _API_KEY:
#         error_msg = "GEMINI_API_KEY is not set in environment variables."
#         logger.error(error_msg)
#         raise RuntimeError(error_msg)

#     model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

#     try:
#         # Use the GenerativeModel object directly (recommended)
#         model = genai.GenerativeModel(model_name)

#         # generate_content accepts a string or list for 'contents'
#         response = model.generate_content(contents=prompt)

#         # Robustly extract text from response
#         response_text = None
#         if hasattr(response, "text") and response.text:
#             response_text = response.text
#         else:
#             # Try common alternate fields
#             try:
#                 # some SDK versions use response.candidates[0].content
#                 response_text = response.candidates[0].content
#             except Exception:
#                 try:
#                     response_text = getattr(response, "result", None)
#                 except Exception:
#                     response_text = None

#         # As a last resort, stringify the response object
#         if not response_text:
#             response_text = str(response)

#         logger.info(f"RESPONSE: {response_text}")

#         # Update cache
#         if use_cache:
#             cache = _load_cache()  # re-load to reduce risk of clobbering
#             cache[prompt] = response_text
#             _save_cache(cache)

#         return response_text

#     except Exception as e:
#         logger.exception("LLM call failed")
#         raise


# # # Maintain a single reusable client to avoid destructor/close issues
# # _GENAI_CLIENT = None

# # def _get_genai_client():
# #     global _GENAI_CLIENT
# #     if _GENAI_CLIENT is None:
# #         _GENAI_CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
# #     return _GENAI_CLIENT


# # # By default, we Google Gemini 2.5 pro, as it shows great performance for code understanding
# # def call_llm(prompt: str, use_cache: bool = True) -> str:
# #     # Log the prompt
# #     logger.info(f"PROMPT: {prompt}")

# #     # Check cache if enabled
# #     if use_cache:
# #         # Load cache from disk
# #         cache = {}
# #         if os.path.exists(cache_file):
# #             try:
# #                 with open(cache_file, "r", encoding="utf-8") as f:
# #                     cache = json.load(f)
# #             except:
# #                 logger.warning(f"Failed to load cache, starting with empty cache")

# #         # Return from cache if exists
# #         if prompt in cache:
# #             logger.info(f"RESPONSE: {cache[prompt]}")
# #             return cache[prompt]

# #     # # Call the LLM if not in cache or cache disabled
# #     # client = genai.Client(
# #     #     vertexai=True,
# #     #     # TODO: change to your own project id and location
# #     #     project=os.getenv("GEMINI_PROJECT_ID", "your-project-id"),
# #     #     location=os.getenv("GEMINI_LOCATION", "us-central1")
# #     # )

# #     # Use a module-level client and avoid calling close() to prevent
# #     # AttributeError in some google-genai builds.
# #     model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# #     try:
# #         client = _get_genai_client()
# #         response = client.models.generate_content(model=model, contents=[prompt])
# #         response_text = response.text
# #     except Exception as e:
# #         logger.error(f"LLM client error: {e}")
# #         raise

# #     # Log the response
# #     logger.info(f"RESPONSE: {response_text}")

# #     # Update cache if enabled
# #     if use_cache:
# #         # Load cache again to avoid overwrites
# #         cache = {}
# #         if os.path.exists(cache_file):
# #             try:
# #                 with open(cache_file, "r", encoding="utf-8") as f:
# #                     cache = json.load(f)
# #             except:
# #                 pass

# #         # Add to cache and save
# #         cache[prompt] = response_text
# #         try:
# #             with open(cache_file, "w", encoding="utf-8") as f:
# #                 json.dump(cache, f)
# #         except Exception as e:
# #             logger.error(f"Failed to save cache: {e}")

# #     return response_text


# # # Use Azure OpenAI
# # def call_llm(prompt, use_cache: bool = True):
# #     from openai import AzureOpenAI

# #     endpoint = "https://<azure openai name>.openai.azure.com/"
# #     deployment = "<deployment name>"

# #     subscription_key = "<azure openai key>"
# #     api_version = "<api version>"

# #     client = AzureOpenAI(
# #         api_version=api_version,
# #         azure_endpoint=endpoint,
# #         api_key=subscription_key,
# #     )

# #     r = client.chat.completions.create(
# #         model=deployment,
# #         messages=[{"role": "user", "content": prompt}],
# #         response_format={
# #             "type": "text"
# #         },
# #         max_completion_tokens=40000,
# #         reasoning_effort="medium",
# #         store=False
# #     )
# #     return r.choices[0].message.content

# # # Use Anthropic Claude 3.7 Sonnet Extended Thinking
# # def call_llm(prompt, use_cache: bool = True):
# #     from anthropic import Anthropic
# #     client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "your-api-key"))
# #     response = client.messages.create(
# #         model="claude-3-7-sonnet-20250219",
# #         max_tokens=21000,
# #         thinking={
# #             "type": "enabled",
# #             "budget_tokens": 20000
# #         },
# #         messages=[
# #             {"role": "user", "content": prompt}
# #         ]
# #     )
# #     return response.content[1].text

# # # Use OpenAI o1
# # def call_llm(prompt, use_cache: bool = True):
# #     from openai import OpenAI
# #     client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "your-api-key"))
# #     r = client.chat.completions.create(
# #         model="o1",
# #         messages=[{"role": "user", "content": prompt}],
# #         response_format={
# #             "type": "text"
# #         },
# #         reasoning_effort="medium",
# #         store=False
# #     )
# #     return r.choices[0].message.content

# # Use OpenRouter API
# # def call_llm(prompt: str, use_cache: bool = True) -> str:
# #     import requests
# #     # Log the prompt
# #     logger.info(f"PROMPT: {prompt}")

# #     # Check cache if enabled
# #     if use_cache:
# #         # Load cache from disk
# #         cache = {}
# #         if os.path.exists(cache_file):
# #             try:
# #                 with open(cache_file, "r", encoding="utf-8") as f:
# #                     cache = json.load(f)
# #             except:
# #                 logger.warning(f"Failed to load cache, starting with empty cache")

# #         # Return from cache if exists
# #         if prompt in cache:
# #             logger.info(f"RESPONSE: {cache[prompt]}")
# #             return cache[prompt]

# #     # OpenRouter API configuration
# #     api_key = os.getenv("OPENROUTER_API_KEY", "")
# #     model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
    
# #     headers = {
# #         "Authorization": f"Bearer {api_key}",
# #     }

# #     data = {
# #         "model": model,
# #         "messages": [{"role": "user", "content": prompt}]
# #     }

# #     response = requests.post(
# #         "https://openrouter.ai/api/v1/chat/completions",
# #         headers=headers,
# #         json=data
# #     )

# #     if response.status_code != 200:
# #         error_msg = f"OpenRouter API call failed with status {response.status_code}: {response.text}"
# #         logger.error(error_msg)
# #         raise Exception(error_msg)
# #     try:
# #         response_text = response.json()["choices"][0]["message"]["content"]
# #     except Exception as e:
# #         error_msg = f"Failed to parse OpenRouter response: {e}; Response: {response.text}"
# #         logger.error(error_msg)        
# #         raise Exception(error_msg)
    

# #     # Log the response
# #     logger.info(f"RESPONSE: {response_text}")

# #     # Update cache if enabled
# #     if use_cache:
# #         # Load cache again to avoid overwrites
# #         cache = {}
# #         if os.path.exists(cache_file):
# #             try:
# #                 with open(cache_file, "r", encoding="utf-8") as f:
# #                     cache = json.load(f)
# #             except:
# #                 pass

# #         # Add to cache and save
# #         cache[prompt] = response_text
# #         try:
# #             with open(cache_file, "w", encoding="utf-8") as f:
# #                 json.dump(cache, f)
# #         except Exception as e:
# #             logger.error(f"Failed to save cache: {e}")

# #     return response_text

# if __name__ == "__main__":
#     test_prompt = "Hello, how are you?"

#     # First call - should hit the API
#     print("Making call...")
#     response1 = call_llm(test_prompt, use_cache=False)
#     print(f"Response: {response1}")


import os
import logging
import json
from datetime import datetime
from dotenv import load_dotenv   # NEW

# Load environment variables from .env file
load_dotenv()

# Use the modern Google GenAI SDK
import google.generativeai as genai

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

    if use_cache:
        cache = _load_cache()
        if prompt in cache:
            logger.info("Cache hit")
            logger.info(f"RESPONSE: {cache[prompt]}")
            return cache[prompt]

    if not _API_KEY:
        error_msg = "GEMINI_API_KEY is not set in .env file or environment."
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(contents=prompt)

        response_text = getattr(response, "text", None) or str(response)

        logger.info(f"RESPONSE: {response_text}")

        if use_cache:
            cache = _load_cache()
            cache[prompt] = response_text
            _save_cache(cache)

        return response_text

    except Exception as e:
        logger.exception("LLM call failed")
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