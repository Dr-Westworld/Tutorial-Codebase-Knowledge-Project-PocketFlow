# Code Tutorial Generator - Frontend Web App

A modern, interactive web application for generating and displaying code tutorials from GitHub repositories and local directories.

## Features

- 🎨 **Modern UI**: Beautiful, responsive design with dark and light themes
- 📚 **Markdown Preview**: Display generated tutorials with rich formatting
- 🔗 **Smart URL Structure**: Direct links to specific tutorials using `localhost:5000/tutorial/{repo-name}/{filename}`
- 🐙 **GitHub Integration**: Process public GitHub repositories directly
- 📁 **Local Support**: Upload and process local directories
- ⚙️ **Advanced Options**: Include/exclude patterns, file size limits, LLM caching
- 🌍 **Multi-language**: Generate tutorials in multiple languages
- ⏱️ **Real-time Updates**: Auto-refresh tutorial list

## Getting Started

### Prerequisites

- **Option 1 (Virtual Environment)**: Python 3.8+
- **Option 2 (Docker)**: Docker and Docker Compose installed

### Installation & Running

Choose your preferred method:

## Method 1: Using Virtual Environment (Recommended for Development)

### Windows

1. Open Command Prompt or PowerShell
2. Navigate to the project directory
3. Run the batch script:
```bash
run.bat
```

This script will automatically:
- Create a virtual environment if it doesn't exist
- Activate the virtual environment
- Install all dependencies
- Start the Flask server

The app will be available at `http://localhost:5000`

### macOS / Linux

1. Open Terminal
2. Navigate to the project directory
3. Make the script executable and run it:
```bash
chmod +x run.sh
./run.sh
```

This script will automatically:
- Create a virtual environment if it doesn't exist
- Activate the virtual environment
- Upgrade pip
- Install all dependencies
- Start the Flask server

The app will be available at `http://localhost:5000`

### Manual Virtual Environment Setup

If you prefer manual setup:

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-app.txt
python app.py
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-app.txt
python app.py
```

## Method 2: Using Docker (Recommended for Production)

### Prerequisites
- Docker installed
- Docker Compose installed (optional, but recommended)

### Quick Start with Docker Compose

1. Navigate to the project directory
2. Run:
```bash
docker-compose up --build
```

The app will start and be available at `http://localhost:5000`

To stop the container:
```bash
docker-compose down
```

### Docker Commands

**Build the image:**
```bash
docker build -t code-tutorial-generator .
```

**Run the container:**
```bash
docker run -d \
  --name code-tutorial-generator \
  -p 5000:5000 \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/uploads:/app/uploads \
  code-tutorial-generator
```

**View logs:**
```bash
docker logs -f code-tutorial-generator
```

**Stop the container:**
```bash
docker stop code-tutorial-generator
```

**Remove the container:**
```bash
docker rm code-tutorial-generator
```

### Docker Compose Configuration

The `docker-compose.yml` file includes:
- Volume mounts for persistent data
- Health checks
- Environment variables
- Port mapping

### Using run_app.py (Advanced Virtual Environment Management)

For automated virtual environment management via Python:

```bash
python run_app.py
```

This script will:
- Create venv if needed
- Activate it
- Install requirements
- Start the Flask app

## Environment Variables

You can set these environment variables for customization:

```bash
# Docker Compose
export FLASK_ENV=production
export FLASK_DEBUG=0
export PYTHONUNBUFFERED=1
```

Or in `docker-compose.yml`:
```yaml
environment:
  - FLASK_ENV=production
  - FLASK_DEBUG=0
```

## Usage

### Creating a Tutorial from GitHub

1. **Select Source Type**: Choose "GitHub Repository"
2. **Enter Repository URL**: `github.com/username/repo` or `https://github.com/username/repo`
3. **(Optional) Configure Filters**:
   - **Include Patterns**: Comma-separated patterns (e.g., `*.py, *.js`)
   - **Exclude Patterns**: Comma-separated patterns (e.g., `tests/*, node_modules/*`)
   - **Maximum File Size**: Size limit in bytes (default: 100KB)
4. **Select Language**: Choose tutorial language
5. **Disable Cache** (optional): For fresh LLM analysis
6. Click **"Generate Tutorial"** button

Keyboard shortcut: `Ctrl+Enter` (or `Cmd+Enter` on Mac)

### Creating a Tutorial from Local Directory

1. **Select Source Type**: Choose "Local Directory"
2. **Enter Path**: Full path to your directory (e.g., `/Users/user/projects/myapp`)
3. **Configure Options**: Same as GitHub tutorials
4. Click **"Generate Tutorial"**

### Viewing Tutorials

Once generated, tutorials appear in the right panel with:
- Tutorial name
- Number of markdown files
- Links to each markdown file

Click any tutorial link to view it in a dedicated, beautified viewer.

## URL Structure

Generated tutorials are accessible at:

```
localhost:5000/tutorial/{github_repo_name_or_project_name}/{markdown_file_name}
```

### Examples

- `localhost:5000/tutorial/gpt2/overview`
- `localhost:5000/tutorial/my-project/getting-started`
- `localhost:5000/tutorial/awesome-repo/main`

## Project Structure

```
├── app.py                    # Flask application backend
├── main.py                   # Original CLI tool
├── run.sh                    # Linux/macOS startup script
├── run.bat                   # Windows startup script
├── run_app.py                # Python venv manager
├── Dockerfile                # Docker container definition
├── docker-compose.yml        # Docker Compose orchestration
├── requirements.txt          # Main project dependencies
├── requirements-app.txt      # Frontend dependencies
├── templates/
│   ├── index.html           # Main dashboard
│   └── viewer.html          # Markdown viewer
├── static/
│   ├── style.css            # Modern CSS styling
│   └── script.js            # Frontend interactivity
├── venv/                    # Virtual environment (created at runtime)
├── output/                  # Generated tutorials (created at runtime)
│   └── {repo_name}/
│       ├── chapter_1.md
│       ├── chapter_2.md
│       └── ...
└── uploads/                 # Uploaded files (created at runtime)
```

## API Endpoints

### Process Repository/Directory
- **POST** `/api/process`
- Body:
  ```json
  {
    "sourceType": "github|local",
    "source": "url or path",
    "include": "*.py, *.js",
    "exclude": "tests/*, node_modules/*",
    "maxSize": 100000,
    "language": "english",
    "disableCache": false
  }
  ```

### Get Tutorials
- **GET** `/api/tutorials`
- Response:
  ```json
  {
    "tutorials": [
      {
        "name": "repo_name",
        "display_name": "Repo Name",
        "file_count": 5,
        "files": [
          {
            "name": "chapter_1",
            "path": "chapter_1.md",
            "display_name": "Chapter 1"
          }
        ]
      }
    ]
  }
  ```

### View Tutorial
- **GET** `/tutorial/{tutorial_name}/{file_path}`
- Returns: HTML-rendered markdown

## Features Explained

### Include/Exclude Patterns

**Default Include Patterns:**
```
*.py, *.js, *.jsx, *.ts, *.tsx, *.go, *.java, *.pyi, *.pyx,
*.c, *.cc, *.cpp, *.h, *.md, *.rst, *Dockerfile, *Makefile,
*.yaml, *.yml
```

**Default Exclude Patterns:**
```
assets/*, data/*, images/*, public/*, static/*, temp/*,
*docs/*, *venv/*, *.venv/*, *test*, *tests/*, *examples/*,
v1/*, *dist/*, *build/*, *experimental/*, *deprecated/*,
*misc/*, *legacy/*, .git/*, .github/*, .next/*, .vscode/*,
*obj/*, *bin/*, *node_modules/*, *.log
```

### File Size Limits

The `maxSize` parameter controls the maximum file size to include in analysis:
- Default: 100KB (100000 bytes)
- Prevents processing extremely large files
- Affects tutorial quality and generation time

### LLM Caching

- **Enabled by default**: Uses cached responses for faster processing
- **Disable caching**: Uncheck "Disable LLM Caching" for fresh analysis
- Useful when regenerating tutorials with different parameters

## Keyboard Shortcuts

- **Ctrl+Enter** / **Cmd+Enter**: Generate tutorial
- **Ctrl+L** / **Cmd+L**: Clear form
- **Tab**: Navigate between form fields

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Responsive Design

The application is fully responsive:
- **Desktop**: Two-panel layout (form + results)
- **Tablet**: Stacked layout with full-width panels
- **Mobile**: Single column with optimized sizing

## Troubleshooting

### Virtual Environment Issues

#### Script not executing on macOS/Linux
```bash
chmod +x run.sh
./run.sh
```

#### Python 3 not found
Ensure Python 3 is installed:
```bash
python3 --version
```

#### Pip install fails
Try upgrading pip:
```bash
python -m pip install --upgrade pip
```

#### Virtual environment not activating (Windows)
Try the full path:
```bash
.\venv\Scripts\activate.bat
```

#### Port 5000 already in use
Change the port in `app.py`:
```python
if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5001)  # Change 5000 to 5001
```

### Docker Issues

#### Docker daemon not running
Start Docker Desktop or the Docker service

#### Permission denied when running Docker
On Linux, add your user to the docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

#### Container exits immediately
Check logs:
```bash
docker-compose logs -f web
```

#### Port 5000 already in use
Change the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "5001:5000"  # Change 5000 to 5001
```

#### Cannot find `requirements-app.txt`
Ensure you're in the project root directory where all files exist

#### Build fails - missing dependencies
Rebuild without cache:
```bash
docker-compose build --no-cache
```

### General Troubleshooting

**Flask is not loading at http://localhost:5000**
- Check if Flask process is running
- Try accessing from different browser
- Clear browser cache (Ctrl+Shift+Delete)
- Check firewall settings

**main.py not found**
- Ensure main.py exists in project root
- Verify file permissions

**Output directory empty**
- Check that main.py executed successfully
- Verify GitHub token (if using GitHub repos)
- Check console output for errors

**Markdown not rendering**
- Verify markdown package is installed: `pip list | grep -i markdown`
- Check file permissions in output directory
- Clear browser cache

**Process Times Out**
- Use more restrictive include patterns
- Reduce max file size
- Exclude large directories
- Try with smaller repositories first

**GitHub API Rate Limiting**
Set your GitHub token:
```bash
export GITHUB_TOKEN=your_token_here
```

Or in Docker Compose:
```yaml
environment:
  - GITHUB_TOKEN=your_token_here
```

## Performance Tips

1. **Use specific include patterns** for faster processing
2. **Exclude large directories** (e.g., `node_modules/*`, `.git/*`)
3. **Lower max file size** for massive codebases
4. **Enable caching** for repeated generation
5. **Use GitHub token** to avoid rate limiting

## Deployment Guide

### Deploying with Docker Compose (Recommended)

**Production Deployment:**

1. Update `docker-compose.yml`:
```yaml
environment:
  - FLASK_ENV=production
  - FLASK_DEBUG=0
```

2. Build and run:
```bash
docker-compose up -d --build
```

3. View logs:
```bash
docker-compose logs -f web
```

### Deploying with Gunicorn (Production WSGI)

For production, you may want to use Gunicorn instead of Flask's development server:

1. Install Gunicorn:
```bash
pip install gunicorn
```

2. Modify Dockerfile or run:
```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

Or update `docker-compose.yml`:
```yaml
command: gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

### Reverse Proxy Setup (Nginx)

For production deployments with Nginx:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Environment Variables for Production

```bash
export FLASK_ENV=production
export FLASK_DEBUG=0
export GITHUB_TOKEN=your_token
export OUTPUT_DIR=/var/tutorials/output
```

Or in `.env` file:
```
FLASK_ENV=production
FLASK_DEBUG=0
GITHUB_TOKEN=your_token
OUTPUT_DIR=/var/tutorials/output
```

## Customization

### Change Port
Edit `app.py`:
```python
if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5001)  # Change port here
```

### Change Tutorial Language
Modify language options in `templates/index.html`:
```html
<option value="your_language">Your Language</option>
```

### Customize Styling
Edit `static/style.css` to modify colors, fonts, and layout.

## Limitations

- Local directory uploads processed via temp directory
- Processing limited to 5 minutes timeout
- Files larger than `maxSize` are skipped
- Requires `main.py` in the project root

## Future Enhancements

- Search across tutorials
- Export tutorials as PDF
- Tutorial versioning
- Collaborative annotations
- Custom styling templates
- Advanced code syntax highlighting
- Tutorial sharing links

## License

Same as the main Code Tutorial Generator project.

## Support

For issues or feature requests for the web app specifically, refer to the main project repository.
