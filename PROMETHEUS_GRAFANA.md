# Prometheus + Grafana (What they are, what they fetch)

This repo exposes **Prometheus metrics** at the Flask endpoint `GET /metrics` (see `app.py`) and ships a **Grafana** setup with pre-provisioned dashboards (see `monitoring/grafana/provisioning/dashboards/`).

If you want the full setup instructions (Docker compose, URLs, troubleshooting), see `MONITORING.md`.

---

## What Prometheus is used for

**Prometheus** is a time-series metrics database that **scrapes** (pulls) numeric measurements from your app on a schedule.

In this project, Prometheus is used to collect operational/performance metrics about tutorial generation, including:

- **Time**: how long nodes/functions/LLM calls take (histograms)
- **CPU**: average CPU utilization during work (gauges)
- **Memory**: peak/average memory usage (gauges)
- **Throughput / counts**: how many files were processed, how many API calls, cache hits (counters)
- **Per-repo dimensions**: metrics are labeled with `repo_name` (and often `node_name`, `function_name`, `status`, etc.)

Prometheus does **not** store logs or traces here—only metrics.

---

## What Grafana is used for

**Grafana** is the visualization layer: it queries Prometheus and renders charts/tables/gauges.

In this project, Grafana is used to answer questions like:

- “Which node is slowest for a given repo?”
- “Are we CPU-bound, memory-bound, or waiting on LLM latency?”
- “Is caching helping (cache hit rate)? Which model is slow?”
- “How does repo A compare to repo B?”

---

## What metrics this app exports (high level)

Metrics are defined in `utils/metrics.py` and exported via the default Prometheus registry.

- **Node performance**
  - `node_execution_time_seconds` (Histogram; labels: `node_name`, `repo_name`, `status`)
  - `node_memory_peak_bytes` (Gauge; labels: `node_name`, `repo_name`)
  - `node_memory_average_bytes` (Gauge; labels: `node_name`, `repo_name`)
  - `node_cpu_percent` (Gauge; labels: `node_name`, `repo_name`)
- **Function performance**
  - `function_execution_time_seconds` (Histogram; labels: `function_name`, `node`, `status`)
  - `function_memory_usage_bytes` / `function_memory_average_bytes` (Gauge; labels: `function_name`, `node`)
  - `function_cpu_percent` (Gauge; labels: `function_name`, `node`)
- **End-to-end & content counters**
  - `total_tutorial_generation_time_seconds` (Gauge; labels: `repo_name`)
  - `files_processed_total` (Counter; labels: `source`, `repo_name`, `status`)
  - `abstractions_identified_total` (Gauge; labels: `repo_name`)
  - `relationships_found_total` (Gauge; labels: `repo_name`)
  - `chapters_written_total` (Gauge; labels: `repo_name`)
- **LLM**
  - `llm_api_call_duration_seconds` (Histogram; labels: `model`, `use_cache`, `cache_hit`)
  - `llm_api_calls_total` (Counter; labels: `model`, `status`)
  - `llm_cache_hits_total` (Counter; labels: `model`)

---

## Grafana dashboards and what they fetch

Dashboards live in `monitoring/grafana/provisioning/dashboards/`.

### 1) Overview Dashboard (`01-overview.json`)

**What it shows**: “at a glance” health/perf numbers.

**What it queries (PromQL)**:

- **Total execution time (seconds)**: `max(total_tutorial_generation_time_seconds)`
- **Peak memory usage (GB)**: `max(node_memory_peak_bytes) / 1024 / 1024 / 1024`
- **Average CPU (%)**: `avg(node_cpu_percent)`
- **Total files processed (last hour)**: `sum(increase(files_processed_total[1h]))`
- **Abstractions identified**: `max(abstractions_identified_total)`
- **Chapters written**: `max(chapters_written_total)`
- **Node execution time summary table**: `node_execution_time_seconds_sum` (instant query)

**Data type**:
- Mostly **aggregated gauges/counters** (global view across repos and nodes), plus a table based on histogram `_sum`.

---

### 2) Per-Node Metrics (`02-node-metrics.json`)

**What it shows**: which nodes are expensive (time/memory/cpu).

**What it queries (PromQL)**:

- **Node execution time over time**: `node_execution_time_seconds_sum{node_name=~".*"}`
- **Node peak memory (MB)**: `max(node_memory_peak_bytes) by (node_name) / 1024 / 1024` (instant)
- **Node average CPU (%)**: `avg(node_cpu_percent) by (node_name)` (instant)
- **Top 20 node executions by time**: `topk(20, node_execution_time_seconds_sum)` (instant)

**Data type**:
- Mostly histogram `_sum` (total time accumulated) + gauges for memory/CPU.

---

### 3) Function Deep Dive (`03-function-metrics.json`)

**What it shows**: which *functions* are expensive (useful when you want to optimize a hot path inside a node).

**What it queries (PromQL)**:

- **Function execution times**: `sum by (function_name, node) (function_execution_time_seconds_sum)`
- **Function peak memory (MB)**: `max(function_memory_usage_bytes) by (function_name) / 1024 / 1024` (instant)
- **Function average CPU (%)**: `avg(function_cpu_percent) by (function_name)` (instant)
- **Top 15 functions by execution time**: `topk(15, function_execution_time_seconds_sum)` (instant)

**Data type**:
- Histogram `_sum` for time + gauges for memory/CPU.

---

### 4) Repository Comparison (`04-repo-comparison.json`)

**What it shows**: side-by-side repo performance and throughput.

**What it queries (PromQL)**:

- **Total time by repository**: `total_tutorial_generation_time_seconds` (instant)
- **Peak memory by repository (GB)**: `max(node_memory_peak_bytes) by (repo_name) / 1024 / 1024 / 1024` (instant)
- **Files processed by repository (last hour)**: `sum by (repo_name) (increase(files_processed_total[1h]))`

**Data type**:
- Gauges keyed by `repo_name` + counter increases for throughput.

---

### 5) LLM Performance (`05-llm-metrics.json`)

**What it shows**: API volume, cache effectiveness, and latency (especially tail latency).

**What it queries (PromQL)**:

- **API call rate (5 min)**: `rate(llm_api_calls_total[5m])`
- **Cache hit rate (last hour)**: `rate(llm_cache_hits_total[1h]) / (rate(llm_api_calls_total[1h]) + 1)` (instant)
- **P95 latency (seconds)**: `histogram_quantile(0.95, rate(llm_api_call_duration_seconds_bucket[5m]))` (instant)
- **API calls by model (last hour)**: `sum by (model) (increase(llm_api_calls_total[1h]))`
- **Average API duration by model**:
  - `sum by (model) (llm_api_call_duration_seconds_sum) / sum by (model) (llm_api_call_duration_seconds_count)`

**Data type**:
- Counter rates for volume + histogram quantiles for tail latency.

---

### 6) Resource Efficiency (`06-efficiency.json`)

**What it shows**: “efficiency ratios” to compare runs and repos (memory/time per unit of work).

**What it queries (PromQL)**:

- **Memory per abstraction (MB)**:
  - `max by (repo_name) (node_memory_peak_bytes) / sum by (repo_name) (abstractions_identified_total) / 1024 / 1024` (instant)
- **Time per chapter (seconds)**:
  - `sum by (repo_name) (total_tutorial_generation_time_seconds) / sum by (repo_name) (chapters_written_total)` (instant)
- **CPU efficiency trend by repository**:
  - `avg(node_cpu_percent) by (repo_name)`

**Data type**:
- Derived ratios from gauges + repo-level CPU averages.

---

## Where the data comes from (in code)

- **Metrics endpoint**: `app.py` exposes `GET /metrics` using `prometheus_client`’s default `REGISTRY`.
- **Metric definitions**: `utils/metrics.py`
- **Instrumentation**: code uses a performance tracker/decorator (see `MONITORING.md` for the full list of instrumented components).

