# PocketFlow Monitoring & Visualization Guide

## Overview

This guide explains how to set up and use Prometheus and Grafana to monitor and visualize CPU, memory, and execution time metrics for the PocketFlow tutorial generation system.

---

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- The monitoring stack configuration files already in place
- `prometheus-client>=0.17.0` and `psutil>=5.9.0` in requirements.txt

### Starting the Monitoring Stack

```bash
docker-compose up -d
```

This command will start three services:
- **Web App** (Flask): http://localhost:5000
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

### Initial Grafana Setup

1. Access Grafana at `http://localhost:3000`
2. Log in with default credentials:
   - Username: `admin`
   - Password: `admin`
3. You should see 6 dashboards auto-provisioned:
   - **Overview Dashboard**: Summary metrics across all operations
   - **Per-Node Metrics**: Individual node execution metrics
   - **Function Deep Dive**: Detailed function-level metrics
   - **Repository Comparison**: Multi-repo analysis
   - **LLM Performance**: API call and cache metrics
   - **Resource Efficiency**: Efficiency ratios and statistics

---

## Architecture

### Metrics Collection Layer

**Files**: `utils/metrics.py`, `utils/performance_tracker.py`

The system uses Prometheus client library to collect metrics:

1. **Function-level tracking**: `@track_performance` decorator automatically captures:
   - Execution time (histogram with buckets)
   - Memory usage (peak and average)
   - CPU utilization percentage

2. **Instrumented Components**:
   - `nodes.py`: All exec() methods (FetchRepo, IdentifyAbstractions, AnalyzeRelationships, OrderChapters, WriteChapters, CombineTutorial)
   - `crawl_github_files.py`: Repository crawling
   - `crawl_local_files.py`: Local directory crawling
   - `call_llm.py`: LLM API calls with cache hit tracking
   - `app.py`: Flask HTTP endpoints

### Prometheus Configuration

**File**: `monitoring/prometheus.yml`

- Scrapes metrics from Flask app at `/metrics` endpoint
- 10-second scrape interval for detailed metrics
- 15-day data retention

### Grafana Dashboards

**Location**: `monitoring/grafana/provisioning/dashboards/`

#### Dashboard 1: Overview Dashboard (`01-overview.json`)
Shows system-wide metrics:
- Total execution time (gauge)
- Peak memory usage (gauge)
- Average CPU utilization (gauge)
- Total files processed
- Abstractions identified
- Chapters written
- Node execution times table

#### Dashboard 2: Per-Node Metrics (`02-node-metrics.json`)
Breaks down metrics by node:
- Execution time timeline for each node
- Peak memory by node (MB)
- Average CPU by node (%)
- Top 20 node executions by time

#### Dashboard 3: Function Deep Dive (`03-function-metrics.json`)
Function-level performance analysis:
- Function execution times over time
- Peak memory per function (MB)
- Average CPU per function (%)
- Top 15 functions by execution time

#### Dashboard 4: Repository Comparison (`04-repo-comparison.json`)
Multi-repository performance analysis:
- Repository metrics summary table
- Total time by repository
- Peak memory by repository (GB)
- Files processed per repository (last hour)

#### Dashboard 5: LLM Performance (`05-llm-metrics.json`)
LLM API and cache metrics:
- API calls rate (5-minute)
- Cache hit rate (last hour)
- P95 latency (seconds)
- API calls by model (1 hour)
- Average API duration by model

#### Dashboard 6: Resource Efficiency (`06-efficiency.json`)
Efficiency calculations:
- Memory per abstraction (MB)
- Time per chapter (seconds)
- CPU efficiency trend by repository
- Time per file (Top 10 slowest)

---

## Metrics Reference

### Function Metrics

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `function_execution_time_seconds` | Histogram | function_name, node, status | Execution duration in seconds |
| `function_memory_usage_bytes` | Gauge | function_name, node | Peak memory in bytes |
| `function_memory_average_bytes` | Gauge | function_name, node | Average memory in bytes |
| `function_cpu_percent` | Gauge | function_name, node | CPU usage percentage |

### Node Metrics

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `node_execution_time_seconds` | Histogram | node_name, repo_name, status | Execution duration in seconds |
| `node_memory_peak_bytes` | Gauge | node_name, repo_name | Peak memory in bytes |
| `node_memory_average_bytes` | Gauge | node_name, repo_name | Average memory in bytes |
| `node_cpu_percent` | Gauge | node_name, repo_name | CPU usage percentage |

### Repository Metadata

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `repository_metrics` | Info | repo_name | Contains: repo_size_mb, file_count, language |
| `total_tutorial_generation_time_seconds` | Gauge | repo_name | End-to-end generation time |
| `abstractions_identified_total` | Gauge | repo_name | Number of abstractions |
| `chapters_written_total` | Gauge | repo_name | Number of chapters |

### File Processing

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `files_processed_total` | Counter | source, repo_name, status | Total files processed |
| `file_processing_duration_seconds` | Histogram | source, repo_name | Per-file processing time |

### LLM Metrics

| Metric | Type | Labels | Notes |
|--------|------|--------|-------|
| `llm_api_call_duration_seconds` | Histogram | model, use_cache, cache_hit | API call duration |
| `llm_cache_hits_total` | Counter | model | Cache hits |
| `llm_api_calls_total` | Counter | model, status | Total API calls |

---

## Accessing Prometheus

### Prometheus UI

Access at `http://localhost:9090`

**Key Pages**:
- **Graph**: Real-time query and visualization
- **Alerts**: Active alerts
- **Status**: Target scraping status

### Example PromQL Queries

```promql
# Average execution time per node
avg(rate(node_execution_time_seconds_sum[5m])) by (node_name)

# Peak memory by node
max(node_memory_peak_bytes) by (node_name)

# CPU utilization trend
avg(node_cpu_percent) by (node_name)

# LLM cache hit rate
rate(llm_cache_hits_total[1h]) / rate(llm_api_calls_total[1h])

# Memory efficiency (MB per abstraction)
max(node_memory_peak_bytes) by (repo_name) / abstractions_identified_total by (repo_name) / 1024 / 1024

# Files processed per second
rate(files_processed_total[5m])
```

---

## Using Grafana Dashboards

### Dashboard Navigation

1. **Home**: View all dashboards
2. **Dashboards**: Click any dashboard to view
3. **Time Range**: Adjust using top-right selector
4. **Auto-Refresh**: Enable auto-refresh for live monitoring

### Common Tasks

#### Monitor Active Tutorial Generation
1. Open "Overview Dashboard"
2. Watch metrics update in real-time
3. Check "Per-Node Metrics" to see which node is active

#### Compare Repository Performance
1. Open "Repository Comparison" dashboard
2. View tables showing metrics per repository
3. Compare time, memory, and file counts

#### Optimize LLM Usage
1. Open "LLM Performance" dashboard
2. Monitor cache hit rate
3. Check P95 latency to identify slow calls
4. Compare API call counts by model

#### Find Resource Bottlenecks
1. Open "Function Deep Dive" dashboard
2. Identify top functions by execution time or memory
3. Scroll to "Top 15 Functions" table
4. Cross-reference with node breakdown in "Per-Node Metrics"

#### Track Efficiency Improvements
1. Open "Resource Efficiency" dashboard
2. Monitor "Time per Chapter" metric
3. Compare "Memory per Abstraction" across runs
4. Use "Time per File" to identify large repositories

---

## Data Export & Retention

### Prometheus Data

- **Location**: `prometheus-storage/` volume
- **Retention**: 15 days (configurable in docker-compose.yml)
- **Export**: Use Prometheus Export feature or query API

### Grafana Dashboards & Data

- **Dashboards**: Stored in `grafana-storage/` volume
- **Datasource**: Configured to use Prometheus
- **Backups**: Regular Docker volume backups recommended

---

## Troubleshooting

### Metrics Not Appearing

1. **Check Flask app is running**:
   ```bash
   curl http://localhost:5000/metrics
   ```

2. **Verify Prometheus scraping**:
   - Go to http://localhost:9090/targets
   - Check if `pocketflow-app` target is `UP`

3. **Check for errors in app logs**:
   ```bash
   docker logs code-tutorial-generator
   ```

### High Memory Usage

1. Check `Max memory` metric in Overview
2. Identify problematic nodes in "Per-Node Metrics"
3. Examine function details in "Function Deep Dive"

### Slow Performance

1. Check `Total Execution Time` in Overview
2. Identify slow nodes in "Per-Node Metrics"
3. Optimize LLM calls using "LLM Performance" metrics

### Prometheus Storage Full

1. Reduce retention in `prometheus.yml`:
   ```yaml
   command:
     - '--storage.tsdb.retention.time=7d'  # Reduce from 15d to 7d
   ```

2. Restart containers:
   ```bash
   docker-compose up -d prometheus
   ```

---

## Advanced Configuration

### Change Prometheus Scrape Interval

Edit `monitoring/prometheus.yml`:
```yaml
global:
  scrape_interval: 5s  # More frequent scraping
```

Restart Prometheus:
```bash
docker-compose up -d prometheus
```

### Customize Grafana Dashboard

1. Open a dashboard in Grafana
2. Click **Edit** (top-right)
3. Modify panels, queries, or layout
4. Click **Save**

### Add Custom Metrics

In your code:
```python
from utils.metrics import MetricsCollector

MetricsCollector.record_custom_metric(
    name="my_metric_name",
    value=some_value,
    labels={"key": "value"}
)
```

---

## Performance Tips

### Optimize Monitoring Overhead

- Reduce scrape frequency if metrics are delayed
- Use higher interval for stable metrics
- Filter unnecessary labels to reduce cardinality

### Reduce Memory Usage

- Shorter Prometheus retention (7 days instead of 15)
- Clean up old volumes regularly
- Archive metrics to external storage

### Improve Query Performance

- Use rate() and avg_over_time() for trend analysis
- Add label filters to narrow down results
- Use recording rules for frequently-used queries

---

## Integration with CI/CD

### GitHub Actions Example

```yaml
- name: Run PocketFlow with Monitoring
  run: |
    docker-compose up -d
    python main.py --repo <URL>
    sleep 10

- name: Export Metrics
  run: |
    curl http://localhost:9090/api/v1/query?query=total_tutorial_generation_time_seconds > metrics.json
```

---

## Support & Documentation

For more information:
- **Prometheus Docs**: https://prometheus.io/docs/
- **Grafana Docs**: https://grafana.com/docs/grafana/latest/
- **PromQL Guide**: https://prometheus.io/docs/prometheus/latest/querying/basics/

---

## Checklist: First-Time Setup

- [ ] Docker Compose file updated with Prometheus and Grafana
- [ ] `monitoring/prometheus.yml` configured
- [ ] Grafana datasource provisioning configured
- [ ] 6 dashboards provisioned and visible
- [ ] Flask app metrics endpoint accessible at `/metrics`
- [ ] First tutorial generation run completed
- [ ] Metrics appearing in Grafana dashboards
- [ ] All 6 dashboards displaying data correctly
- [ ] CPU/Memory/Time metrics validated
- [ ] Repository comparison working with multiple runs

---

**Last Updated**: 2024
**Monitoring Stack Version**: Prometheus 2.x + Grafana 10.x
