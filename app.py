import os
import json
import subprocess
import markdown
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import shutil
import tempfile

# Prometheus metrics
from prometheus_client import make_wsgi_app, REGISTRY
from utils.metrics import MetricsCollector

# Configuration
APP_FOLDER = Path(__file__).parent
OUTPUT_DIR = APP_FOLDER / "output"
UPLOAD_DIR = APP_FOLDER / "uploads"
TEMPLATE_DIR = APP_FOLDER / "templates"
STATIC_DIR = APP_FOLDER / "static"

# Create necessary directories
OUTPUT_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config['UPLOAD_FOLDER'] = str(UPLOAD_DIR)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload

# Default patterns from main.py
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
    This survives markdown processing better than plain text placeholders.
    """
    # Store mermaid blocks with unique identifiers
    mermaid_blocks = {}
    placeholder_counter = [0]

    # Pattern to match mermaid code blocks in markdown (with or without blank lines)
    mermaid_pattern = r'```mermaid\s*\n(.*?)\n```'

    def extract_block(match):
        code = match.group(1).strip()
        placeholder_counter[0] += 1
        block_id = placeholder_counter[0]
        mermaid_blocks[block_id] = code

        # Use HTML comment format that survives markdown processing
        placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
        return placeholder

    # Extract all mermaid blocks
    modified_content = re.sub(mermaid_pattern, extract_block, markdown_content, flags=re.DOTALL)

    print(f"[DEBUG] Extracted {len(mermaid_blocks)} mermaid blocks")
    for block_id, code in mermaid_blocks.items():
        print(f"[DEBUG] Block {block_id}: {code[:50]}...")

    return modified_content, mermaid_blocks


def reinject_mermaid_divs(html_content, mermaid_blocks):
    """
    Replace HTML comment placeholders with proper mermaid div elements.
    """
    if not mermaid_blocks:
        print("[DEBUG] No mermaid blocks to reinject")
        return html_content

    print(f"[DEBUG] Reinjecting {len(mermaid_blocks)} mermaid blocks")

    for block_id, code in mermaid_blocks.items():
        placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'

        if placeholder in html_content:
            print(f"[DEBUG] Found placeholder {block_id}, replacing it")
            # Create the mermaid div with the raw code (don't escape for div content)
            mermaid_div = f'<div class="mermaid">\n{code}\n</div>'
            html_content = html_content.replace(placeholder, mermaid_div)
        else:
            print(f"[DEBUG] WARNING: Placeholder {block_id} NOT FOUND in HTML!")
            print(f"[DEBUG] Looking for: {placeholder}")
            print(f"[DEBUG] HTML content preview: {html_content[:500]}")

    return html_content


@app.route('/')
def index():
    """Serve the main page"""
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
    """Process a repository or local directory"""
    try:
        data = request.json

        # Validate input
        if not data.get('source'):
            return jsonify({'error': 'No source provided'}), 400

        source_type = data.get('sourceType')  # 'github' or 'local'

        # Build command
        cmd = ['python', 'main.py']

        if source_type == 'github':
            repo_url = data.get('source')
            if not repo_url.startswith('http'):
                repo_url = f'https://{repo_url}'
            cmd.extend(['--repo', repo_url])
        else:
            local_path = data.get('source')
            if not os.path.exists(local_path):
                return jsonify({'error': f'Local path does not exist: {local_path}'}), 400
            cmd.extend(['--dir', local_path])

        # Add optional parameters
        if data.get('include'):
            include_patterns = [p.strip() for p in data['include'].split(',') if p.strip()]
            cmd.extend(['--include'] + include_patterns)

        if data.get('exclude'):
            exclude_patterns = [p.strip() for p in data['exclude'].split(',') if p.strip()]
            cmd.extend(['--exclude'] + exclude_patterns)

        if data.get('maxSize'):
            cmd.extend(['--max-size', str(data['maxSize'])])

        if data.get('language'):
            cmd.extend(['--language', data['language']])

        if data.get('disableCache'):
            cmd.append('--no-cache')

        # Run the main.py script
        result = subprocess.run(cmd, cwd=str(APP_FOLDER), capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            return jsonify({'error': f'Processing failed: {result.stderr}'}), 500

        # Get the list of tutorials
        tutorials = list_tutorials()

        return jsonify({
            'success': True,
            'message': 'Processing completed successfully',
            'tutorials': tutorials,
            'output': result.stdout
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tutorials')
def get_tutorials():
    """Get list of all tutorials"""
    try:
        tutorials = list_tutorials()
        return jsonify({'tutorials': tutorials})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def list_tutorials():
    """List all available tutorials in the output directory"""
    tutorials = []

    if not OUTPUT_DIR.exists():
        return tutorials

    for project_dir in OUTPUT_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        markdown_files = []

        # Find all markdown files
        for md_file in project_dir.rglob('*.md'):
            rel_path = md_file.relative_to(project_dir)
            markdown_files.append({
                'name': md_file.stem,
                'path': str(rel_path).replace('\\', '/'),
                'display_name': md_file.stem.replace('_', ' ').title()
            })

        if markdown_files:
            tutorials.append({
                'name': project_name,
                'display_name': project_name.replace('_', ' ').replace('-', ' ').title(),
                'files': sorted(markdown_files, key=lambda x: x['name']),
                'file_count': len(markdown_files)
            })

    return sorted(tutorials, key=lambda x: x['name'])


@app.route('/tutorial/<tutorial_name>/<file_path>')
def view_tutorial(tutorial_name, file_path):
    """Display a tutorial markdown file as HTML"""
    try:
        tutorial_dir = OUTPUT_DIR / tutorial_name

        if not tutorial_dir.exists():
            return f"<h1>Tutorial not found: {tutorial_name}</h1>", 404

        # Secure the file path
        file_name = secure_filename(file_path)
        md_file = tutorial_dir / f"{file_name}.md"

        if not md_file.exists():
            # Try without extension
            md_file = tutorial_dir / file_path
            if not md_file.exists() or not md_file.name.endswith('.md'):
                return f"<h1>File not found: {file_path}</h1>", 404

        # Read markdown file
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract mermaid blocks BEFORE markdown processing
        modified_content, mermaid_blocks = extract_and_process_mermaid(content)

        # Convert markdown to HTML (mermaid blocks are now placeholders)
        html_content = markdown.markdown(modified_content, extensions=['extra', 'codehilite', 'toc'])

        # Reinsert mermaid diagrams as proper divs
        html_content = reinject_mermaid_divs(html_content, mermaid_blocks)

        return render_template('viewer.html',
                             content=html_content,
                             title=md_file.stem.replace('_', ' ').title(),
                             tutorial_name=tutorial_name)

    except Exception as e:
        return f"<h1>Error loading tutorial</h1><p>{str(e)}</p>", 500


@app.route('/api/process-upload', methods=['POST'])
def process_upload():
    """Handle directory upload processing"""
    try:
        if 'directory' not in request.files:
            return jsonify({'error': 'No directory provided'}), 400

        # Get other form data
        include = request.form.get('include', '')
        exclude = request.form.get('exclude', '')
        max_size = request.form.get('maxSize', 100000)
        language = request.form.get('language', 'english')
        disable_cache = request.form.get('disableCache') == 'true'

        # Process uploaded files
        files = request.files.getlist('directory')

        if not files:
            return jsonify({'error': 'No files uploaded'}), 400

        # Create temporary directory for uploaded files
        temp_dir = tempfile.mkdtemp()

        try:
            # Save uploaded files maintaining structure
            for file in files:
                if file.filename:
                    file_path = Path(temp_dir) / secure_filename(file.filename)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file.save(file_path)

            # Build command
            cmd = ['python', 'main.py', '--dir', temp_dir]

            if include:
                include_patterns = [p.strip() for p in include.split(',') if p.strip()]
                cmd.extend(['--include'] + include_patterns)

            if exclude:
                exclude_patterns = [p.strip() for p in exclude.split(',') if p.strip()]
                cmd.extend(['--exclude'] + exclude_patterns)

            cmd.extend(['--max-size', str(max_size)])
            cmd.extend(['--language', language])

            if disable_cache:
                cmd.append('--no-cache')

            # Run the main.py script
            result = subprocess.run(cmd, cwd=str(APP_FOLDER), capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                return jsonify({'error': f'Processing failed: {result.stderr}'}), 500

            tutorials = list_tutorials()

            return jsonify({
                'success': True,
                'message': 'Processing completed successfully',
                'tutorials': tutorials,
                'output': result.stdout
            })

        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Processing timed out (exceeded 5 minutes)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/downloads/<path:filename>')
def download_file(filename):
    """Download a file"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    # app.run(debug=True, host='localhost', port=5000)
    app.run(debug=True, host='0.0.0.0', port=5000)