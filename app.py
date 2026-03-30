# import os
# import time         
# import json
# import subprocess
# import markdown
# import re
# from pathlib import Path
# from flask import Flask, render_template, request, jsonify, send_from_directory
# from werkzeug.utils import secure_filename
# import shutil
# import tempfile
# from prometheus_client import REGISTRY
# from utils.metrics import MetricsCollector   
# from flow import create_tutorial_flow

# # Configuration
# APP_FOLDER   = Path(__file__).parent
# OUTPUT_DIR   = APP_FOLDER / "output"
# UPLOAD_DIR   = APP_FOLDER / "uploads"
# TEMPLATE_DIR = APP_FOLDER / "templates"
# STATIC_DIR   = APP_FOLDER / "static"
# OUTPUT_DIR.mkdir(exist_ok=True)
# UPLOAD_DIR.mkdir(exist_ok=True)
# TEMPLATE_DIR.mkdir(exist_ok=True)
# STATIC_DIR.mkdir(exist_ok=True)

# app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
# app.config['UPLOAD_FOLDER']        = str(UPLOAD_DIR)
# app.config['MAX_CONTENT_LENGTH']   = 100 * 1024 * 1024  # 100 MB

# DEFAULT_INCLUDE_PATTERNS = [
#     "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.java", "*.pyi", "*.pyx",
#     "*.c", "*.cc", "*.cpp", "*.h", "*.md", "*.rst", "*Dockerfile",
#     "*Makefile", "*.yaml", "*.yml"
# ]

# DEFAULT_EXCLUDE_PATTERNS = [
#     "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*",
#     "*docs/*", "*venv/*", "*.venv/*", "*test*", "*tests/*", "*examples/*",
#     "v1/*", "*dist/*", "*build/*", "*experimental/*", "*deprecated/*",
#     "*misc/*", "*legacy/*", ".git/*", ".github/*", ".next/*", ".vscode/*",
#     "*obj/*", "*bin/*", "*node_modules/*", "*.log"
# ]


# def extract_and_process_mermaid(markdown_content):
#     """
#     Extract mermaid blocks BEFORE markdown processing using HTML comments.
#     This survives markdown processing better than plain text placeholders.
#     """
#     mermaid_blocks       = {}
#     placeholder_counter  = [0]
#     mermaid_pattern      = r'```mermaid\s*\n(.*?)\n```'

#     def extract_block(match):
#         code = match.group(1).strip()
#         placeholder_counter[0] += 1
#         block_id                  = placeholder_counter[0]
#         mermaid_blocks[block_id]  = code
#         return f'<!-- MERMAID_BLOCK_{block_id} -->'

#     modified_content = re.sub(mermaid_pattern, extract_block, markdown_content, flags=re.DOTALL)

#     print(f"[DEBUG] Extracted {len(mermaid_blocks)} mermaid blocks")
#     for block_id, code in mermaid_blocks.items():
#         print(f"[DEBUG] Block {block_id}: {code[:50]}...")

#     return modified_content, mermaid_blocks


# def reinject_mermaid_divs(html_content, mermaid_blocks):
#     """
#     Replace HTML comment placeholders with proper mermaid div elements.
#     """
#     if not mermaid_blocks:
#         print("[DEBUG] No mermaid blocks to reinject")
#         return html_content

#     print(f"[DEBUG] Reinjecting {len(mermaid_blocks)} mermaid blocks")

#     for block_id, code in mermaid_blocks.items():
#         placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
#         if placeholder in html_content:
#             print(f"[DEBUG] Found placeholder {block_id}, replacing it")
#             html_content = html_content.replace(placeholder, f'<div class="mermaid">\n{code}\n</div>')
#         else:
#             print(f"[DEBUG] WARNING: Placeholder {block_id} NOT FOUND in HTML!")
#             print(f"[DEBUG] Looking for: {placeholder}")
#             print(f"[DEBUG] HTML content preview: {html_content[:500]}")

#     return html_content


# @app.route('/')
# def index():
#     return render_template('index.html',
#                            default_include=DEFAULT_INCLUDE_PATTERNS,
#                            default_exclude=DEFAULT_EXCLUDE_PATTERNS)


# @app.route('/metrics')
# def metrics():
#     """Prometheus metrics endpoint"""
#     from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
#     # region agent log
#     try:
#         import json as _json, time as _time
#         with open("debug-785079.log", "a", encoding="utf-8") as _f:
#             _payload = {
#                 "sessionId":    "785079",
#                 "runId":        "initial",
#                 "hypothesisId": "H1",
#                 "location":     "app.py:/metrics",
#                 "message":      "metrics_endpoint_called",
#                 "data":         {},
#                 "timestamp":    int(_time.time() * 1000),
#             }
#             _f.write(_json.dumps(_payload) + "\n")
#     except Exception:
#         pass
#     # endregion
#     return generate_latest(REGISTRY), 200, {'Content-Type': CONTENT_TYPE_LATEST}


# @app.route('/api/process', methods=['POST'])
# def process_repository():
#     """Process a repository or local directory"""
#     try:
#         data = request.json

#         if not data.get('source'):
#             return jsonify({'error': 'No source provided'}), 400

#         source_type = data.get('sourceType')

#         repo_url  = None
#         local_dir = None
#         if source_type == 'github':
#             repo_url = data.get('source')
#             if not repo_url.startswith('http'):
#                 repo_url = f'https://{repo_url}'
#         else:
#             local_path = data.get('source')
#             if not os.path.exists(local_path):
#                 return jsonify({'error': f'Local path does not exist: {local_path}'}), 400
#             local_dir = local_path

#         include_patterns = set(DEFAULT_INCLUDE_PATTERNS)
#         if data.get('include'):
#             include_patterns = {p.strip() for p in data['include'].split(',') if p.strip()}

#         exclude_patterns = set(DEFAULT_EXCLUDE_PATTERNS)
#         if data.get('exclude'):
#             exclude_patterns = {p.strip() for p in data['exclude'].split(',') if p.strip()}

#         max_size    = int(data.get('maxSize') or 100000)
#         language    = data.get('language') or 'english'
#         use_cache   = not data.get('disableCache', False)

#         shared = {
#             "repo_url":           repo_url,
#             "local_dir":          local_dir,
#             "project_name":       None,
#             "github_token":       None,
#             "output_dir":         "output",
#             "include_patterns":   include_patterns,
#             "exclude_patterns":   exclude_patterns,
#             "max_file_size":      max_size,
#             "language":           language,
#             "use_cache":          use_cache,
#             "max_abstraction_num": 10,
#             "files":              [],
#             "abstractions":       [],
#             "relationships":      {},
#             "chapter_order":      [],
#             "chapters":           [],
#             "final_output_dir":   None,
            
#             # record the true end-to-end wall time via MetricsCollector.record_total_generation_time
#             "_pipeline_start_time": time.perf_counter(),
            
#         }

#         tutorial_flow = create_tutorial_flow()
#         tutorial_flow.run(shared)

#         tutorials = list_tutorials()

#         return jsonify({
#             'success': True,
#             'message': 'Processing completed successfully',
#             'tutorials': tutorials,
#             'output':   f"Output directory: {shared.get('final_output_dir')}"
#         })

#     except subprocess.TimeoutExpired:
#         return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# @app.route('/api/tutorials')
# def get_tutorials():
#     try:
#         tutorials = list_tutorials()
#         return jsonify({'tutorials': tutorials})
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# def list_tutorials():
#     tutorials = []
#     if not OUTPUT_DIR.exists():
#         return tutorials

#     for project_dir in OUTPUT_DIR.iterdir():
#         if not project_dir.is_dir():
#             continue

#         project_name   = project_dir.name
#         markdown_files = []

#         for md_file in project_dir.rglob('*.md'):
#             rel_path = md_file.relative_to(project_dir)
#             markdown_files.append({
#                 'name':         md_file.stem,
#                 'path':         str(rel_path).replace('\\', '/'),
#                 'display_name': md_file.stem.replace('_', ' ').title()
#             })

#         if markdown_files:
#             tutorials.append({
#                 'name':         project_name,
#                 'display_name': project_name.replace('_', ' ').replace('-', ' ').title(),
#                 'files':        sorted(markdown_files, key=lambda x: x['name']),
#                 'file_count':   len(markdown_files)
#             })

#     return sorted(tutorials, key=lambda x: x['name'])


# @app.route('/tutorial/<tutorial_name>/<file_path>')
# def view_tutorial(tutorial_name, file_path):
#     try:
#         tutorial_dir = OUTPUT_DIR / tutorial_name
#         if not tutorial_dir.exists():
#             return f"<h1>Tutorial not found: {tutorial_name}</h1>", 404

#         file_name = secure_filename(file_path)
#         md_file   = tutorial_dir / f"{file_name}.md"

#         if not md_file.exists():
#             md_file = tutorial_dir / file_path
#             if not md_file.exists() or not md_file.name.endswith('.md'):
#                 return f"<h1>File not found: {file_path}</h1>", 404

#         with open(md_file, 'r', encoding='utf-8') as f:
#             content = f.read()

#         modified_content, mermaid_blocks = extract_and_process_mermaid(content)
#         html_content                     = markdown.markdown(modified_content, extensions=['extra', 'codehilite', 'toc'])
#         html_content                     = reinject_mermaid_divs(html_content, mermaid_blocks)

#         return render_template('viewer.html',
#                                content=html_content,
#                                title=md_file.stem.replace('_', ' ').title(),
#                                tutorial_name=tutorial_name)

#     except Exception as e:
#         return f"<h1>Error loading tutorial</h1><p>{str(e)}</p>", 500


# @app.route('/api/process-upload', methods=['POST'])
# def process_upload():
#     try:
#         if 'directory' not in request.files:
#             return jsonify({'error': 'No directory provided'}), 400

#         include      = request.form.get('include', '')
#         exclude      = request.form.get('exclude', '')
#         max_size     = request.form.get('maxSize', 100000)
#         language     = request.form.get('language', 'english')
#         disable_cache = request.form.get('disableCache') == 'true'

#         files = request.files.getlist('directory')
#         if not files:
#             return jsonify({'error': 'No files uploaded'}), 400

#         temp_dir = tempfile.mkdtemp()

#         try:
#             for file in files:
#                 if file.filename:
#                     file_path = Path(temp_dir) / secure_filename(file.filename)
#                     file_path.parent.mkdir(parents=True, exist_ok=True)
#                     file.save(file_path)

#             cmd = ['python', 'main.py', '--dir', temp_dir]

#             if include:
#                 cmd.extend(['--include'] + [p.strip() for p in include.split(',') if p.strip()])
#             if exclude:
#                 cmd.extend(['--exclude'] + [p.strip() for p in exclude.split(',') if p.strip()])

#             cmd.extend(['--max-size', str(max_size)])
#             cmd.extend(['--language', language])

#             if disable_cache:
#                 cmd.append('--no-cache')

#             result = subprocess.run(cmd, cwd=str(APP_FOLDER), capture_output=True, text=True, timeout=300)

#             if result.returncode != 0:
#                 return jsonify({'error': f'Processing failed: {result.stderr}'}), 500

#             tutorials = list_tutorials()
#             return jsonify({
#                 'success': True,
#                 'message': 'Processing completed successfully',
#                 'tutorials': tutorials,
#                 'output':   result.stdout
#             })

#         finally:
#             shutil.rmtree(temp_dir, ignore_errors=True)

#     except subprocess.TimeoutExpired:
#         return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# @app.route('/downloads/<path:filename>')
# def download_file(filename):
#     return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5000)

import os
import time
import json
import subprocess
import markdown
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import shutil
import tempfile
from prometheus_client import REGISTRY
from utils.metrics import MetricsCollector
from flow import get_flow   # ← changed from "create_tutorial_flow" import

# ── Configuration ──────────────────────────────────────────────────────────────
# APP_MODE controls which pipeline is used:
#   "sync"  (default) → WriteChapters (sequential BatchNode)  — production
#   "async"           → AsyncWriteChapters (ThreadPoolExecutor) — v2/research
# Set via environment variable; both containers read the same app.py.
APP_MODE = os.getenv("APP_MODE", "sync")

APP_FOLDER   = Path(__file__).parent
OUTPUT_DIR   = APP_FOLDER / "output"
UPLOAD_DIR   = APP_FOLDER / "uploads"
TEMPLATE_DIR = APP_FOLDER / "templates"
STATIC_DIR   = APP_FOLDER / "static"
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config['UPLOAD_FOLDER']        = str(UPLOAD_DIR)
app.config['MAX_CONTENT_LENGTH']   = 100 * 1024 * 1024  # 100 MB

DEFAULT_INCLUDE_PATTERNS = [
    "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.go", "*.java", "*.pyi", "*.pyx",
    "*.c", "*.cc", "*.cpp", "*.h", "*.md", "*.rst", "*Dockerfile",
    "*Makefile", "*.yaml", "*.yml"
]

DEFAULT_EXCLUDE_PATTERNS = [
    "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*",
    "*docs/*", "*venv/*", "*.venv/*", "*test*", "*tests/*", "*examples/*",
    "v1/*", "*dist/*", "*build/*", "*experimental/*", "*deprecated/*",
    "*misc/*", "*legacy/*", ".git/*", ".github/*", ".next/*", ".vscode/*",
    "*obj/*", "*bin/*", "*node_modules/*", "*.log"
]


def extract_and_process_mermaid(markdown_content):
    """
    Extract mermaid blocks BEFORE markdown processing using HTML comments.
    HTML comments survive markdown processing; plain text placeholders don't.
    """
    mermaid_blocks      = {}
    placeholder_counter = [0]
    mermaid_pattern     = r'```mermaid\s*\n(.*?)\n```'

    def extract_block(match):
        code = match.group(1).strip()
        placeholder_counter[0] += 1
        block_id               = placeholder_counter[0]
        mermaid_blocks[block_id] = code
        return f'<!-- MERMAID_BLOCK_{block_id} -->'

    modified_content = re.sub(mermaid_pattern, extract_block, markdown_content, flags=re.DOTALL)
    print(f"[DEBUG] Extracted {len(mermaid_blocks)} mermaid blocks")
    return modified_content, mermaid_blocks


def reinject_mermaid_divs(html_content, mermaid_blocks):
    """Replace HTML comment placeholders with mermaid div elements."""
    if not mermaid_blocks:
        return html_content
    for block_id, code in mermaid_blocks.items():
        placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
        if placeholder in html_content:
            html_content = html_content.replace(
                placeholder, f'<div class="mermaid">\n{code}\n</div>'
            )
        else:
            print(f"[DEBUG] WARNING: Placeholder {block_id} NOT FOUND in HTML!")
    return html_content


@app.route('/')
def index():
    return render_template('index.html',
                           default_include=DEFAULT_INCLUDE_PATTERNS,
                           default_exclude=DEFAULT_EXCLUDE_PATTERNS)


@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), 200, {'Content-Type': CONTENT_TYPE_LATEST}


@app.route('/api/process', methods=['POST'])
def process_repository():
    """
    Process a repository or local directory.

    The pipeline used depends on APP_MODE environment variable:
      sync  → WriteChapters   (production default)
      async → AsyncWriteChapters (v2 research container)
    """
    try:
        data = request.json

        if not data.get('source'):
            return jsonify({'error': 'No source provided'}), 400

        source_type = data.get('sourceType')
        repo_url    = None
        local_dir   = None

        if source_type == 'github':
            repo_url = data.get('source')
            if not repo_url.startswith('http'):
                repo_url = f'https://{repo_url}'
        else:
            local_path = data.get('source')
            if not os.path.exists(local_path):
                return jsonify({'error': f'Local path does not exist: {local_path}'}), 400
            local_dir = local_path

        include_patterns = set(DEFAULT_INCLUDE_PATTERNS)
        if data.get('include'):
            include_patterns = {p.strip() for p in data['include'].split(',') if p.strip()}

        exclude_patterns = set(DEFAULT_EXCLUDE_PATTERNS)
        if data.get('exclude'):
            exclude_patterns = {p.strip() for p in data['exclude'].split(',') if p.strip()}

        max_size  = int(data.get('maxSize') or 100000)
        language  = data.get('language') or 'english'
        use_cache = not data.get('disableCache', False)

        shared = {
            "repo_url":           repo_url,
            "local_dir":          local_dir,
            "project_name":       None,
            "github_token":       None,
            "output_dir":         "output",
            "include_patterns":   include_patterns,
            "exclude_patterns":   exclude_patterns,
            "max_file_size":      max_size,
            "language":           language,
            "use_cache":          use_cache,
            "max_abstraction_num": 10,
            # Research gap settings (read by nodes.py research version)
            "async_max_workers":          int(os.getenv("ASYNC_MAX_WORKERS", "4")),
            "enable_divergence_tracking": APP_MODE != "sync",  # Gap 3: enable for v2
            # Pipeline timing
            "_pipeline_start_time": time.perf_counter(),
            # Outputs
            "files":           [],
            "abstractions":    [],
            "relationships":   {},
            "chapter_order":   [],
            "chapters":        [],
            "final_output_dir": None,
        }

        # ── Pick the flow based on APP_MODE ──────────────────────────────────
        tutorial_flow = get_flow(APP_MODE)
        tutorial_flow.run(shared)

        tutorials = list_tutorials()
        return jsonify({
            'success':   True,
            'mode':      APP_MODE,
            'message':   f'Processing completed successfully ({APP_MODE} mode)',
            'tutorials': tutorials,
            'output':    f"Output directory: {shared.get('final_output_dir')}",
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tutorials')
def get_tutorials():
    try:
        tutorials = list_tutorials()
        return jsonify({'tutorials': tutorials})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def list_tutorials():
    tutorials = []
    if not OUTPUT_DIR.exists():
        return tutorials

    for project_dir in OUTPUT_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        project_name   = project_dir.name
        markdown_files = []

        for md_file in project_dir.rglob('*.md'):
            rel_path = md_file.relative_to(project_dir)
            markdown_files.append({
                'name':         md_file.stem,
                'path':         str(rel_path).replace('\\', '/'),
                'display_name': md_file.stem.replace('_', ' ').title()
            })

        if markdown_files:
            tutorials.append({
                'name':         project_name,
                'display_name': project_name.replace('_', ' ').replace('-', ' ').title(),
                'files':        sorted(markdown_files, key=lambda x: x['name']),
                'file_count':   len(markdown_files)
            })

    return sorted(tutorials, key=lambda x: x['name'])


@app.route('/tutorial/<tutorial_name>/<file_path>')
def view_tutorial(tutorial_name, file_path):
    try:
        tutorial_dir = OUTPUT_DIR / tutorial_name
        if not tutorial_dir.exists():
            return f"<h1>Tutorial not found: {tutorial_name}</h1>", 404

        file_name = secure_filename(file_path)
        md_file   = tutorial_dir / f"{file_name}.md"

        if not md_file.exists():
            md_file = tutorial_dir / file_path
            if not md_file.exists() or not md_file.name.endswith('.md'):
                return f"<h1>File not found: {file_path}</h1>", 404

        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        modified_content, mermaid_blocks = extract_and_process_mermaid(content)
        html_content                     = markdown.markdown(
            modified_content, extensions=['extra', 'codehilite', 'toc']
        )
        html_content = reinject_mermaid_divs(html_content, mermaid_blocks)

        return render_template('viewer.html',
                               content=html_content,
                               title=md_file.stem.replace('_', ' ').title(),
                               tutorial_name=tutorial_name)

    except Exception as e:
        return f"<h1>Error loading tutorial</h1><p>{str(e)}</p>", 500


@app.route('/api/process-upload', methods=['POST'])
def process_upload():
    try:
        if 'directory' not in request.files:
            return jsonify({'error': 'No directory provided'}), 400

        include       = request.form.get('include', '')
        exclude       = request.form.get('exclude', '')
        max_size      = request.form.get('maxSize', 100000)
        language      = request.form.get('language', 'english')
        disable_cache = request.form.get('disableCache') == 'true'

        files = request.files.getlist('directory')
        if not files:
            return jsonify({'error': 'No files uploaded'}), 400

        temp_dir = tempfile.mkdtemp()

        try:
            for file in files:
                if file.filename:
                    file_path = Path(temp_dir) / secure_filename(file.filename)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file.save(file_path)

            cmd = ['python', 'main.py', '--dir', temp_dir]

            if include:
                cmd.extend(['--include'] + [p.strip() for p in include.split(',') if p.strip()])
            if exclude:
                cmd.extend(['--exclude'] + [p.strip() for p in exclude.split(',') if p.strip()])

            cmd.extend(['--max-size', str(max_size)])
            cmd.extend(['--language', language])

            if disable_cache:
                cmd.append('--no-cache')

            result = subprocess.run(cmd, cwd=str(APP_FOLDER), capture_output=True,
                                    text=True, timeout=300)

            if result.returncode != 0:
                return jsonify({'error': f'Processing failed: {result.stderr}'}), 500

            tutorials = list_tutorials()
            return jsonify({
                'success':   True,
                'message':   'Processing completed successfully',
                'tutorials': tutorials,
                'output':    result.stdout
            })

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/downloads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    print(f"Starting Code Tutorial Generator — APP_MODE={APP_MODE}")
    app.run(debug=True, host='0.0.0.0', port=5000)