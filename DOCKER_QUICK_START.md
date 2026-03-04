# 🐳 Code Tutorial Generator - Docker Quick Start (SIMPLEST WAY)

If you have **Docker installed**, this is the easiest way to run the app. You don't need Python, virtual environments, or any other setup!

## Requirements

- Docker (https://www.docker.com/products/docker-desktop)
- Docker Compose (usually included with Docker Desktop)

## Quick Start (3 Steps)

### 1. Copy `.env.example` to `.env` (Optional)

```bash
cp .env.example .env
```

Then edit `.env` if you want to add GitHub token:
```
GITHUB_TOKEN=your_github_token_here
```

### 2. Start the Application

```bash
docker-compose up --build
```

**That's it!** The application will start automatically.

### 3. Open in Browser

```
http://localhost:5000
```

## Common Docker Commands

### Start the app
```bash
docker-compose up --build
```

### Stop the app
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f web
```

### Restart the app
```bash
docker-compose restart web
```

### View running containers
```bash
docker ps
```

### Remove the container and rebuild
```bash
docker-compose down --rmi all
docker-compose up --build
```

## File Structure for Docker

```
├── Dockerfile              # Docker build instructions
├── docker-compose.yml      # Docker orchestration
├── .env.example            # Configuration template
├── .env                    # Your configuration (git-ignored)
├── app.py                  # Flask app
├── main.py                 # CLI tool
├── flow.py                 # Flow engine
├── requirements.txt        # Dependencies
├── requirements-app.txt    # Web app dependencies
├── templates/              # HTML templates
├── static/                 # CSS/JS files
├── output/                 # Generated tutorials (persistent)
└── uploads/                # Uploaded files (persistent)
```

## How It Works

1. **Docker builds an image** with Python 3.11 + all dependencies
2. **Docker Compose** orchestrates the container
3. **Volumes** mount `output/` and `uploads/` directories to persist data
4. **Health checks** monitor the app
5. Access at `http://localhost:5000`

## Configuration via `.env` File

Copy `.env.example` to `.env` and customize:

```bash
# GitHub API Configuration
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Flask Configuration (optional)
FLASK_ENV=production
FLASK_DEBUG=0

# Other options...
```

## Data Persistence

- **output/** - Saved tutorials (survives container restart)
- **uploads/** - Temporary uploads (survives container restart)

All data in `output/` is preserved even if you delete the container.

## Troubleshooting

### Port 5000 Already in Use

Edit `docker-compose.yml`:
```yaml
ports:
  - "5001:5000"  # Use port 5001 instead
```

Then access at `http://localhost:5001`

### Container Won't Start

Check logs:
```bash
docker-compose logs web
```

Look for error messages. Common issues:
- Port conflicts: Change in docker-compose.yml
- Disk space: Docker needs space to build image
- Missing .env: Not required, but creates verbosity

### "Cannot find requirements.txt"

Ensure you're in the project root directory:
```bash
ls docker-compose.yml requirements.txt  # Should both exist
```

### "Docker daemon not running"

- **Windows/Mac**: Start Docker Desktop
- **Linux**: `sudo systemctl start docker`

### Remove Everything and Start Fresh

```bash
docker-compose down --rmi all --volumes
docker-compose up --build
```

## Network Access

### From Your Machine
```
http://localhost:5000
```

### From Another Machine on Same Network
```
http://your-machine-ip:5000
```

Replace `your-machine-ip` with your computer's IP address (run `ipconfig` on Windows or `ifconfig` on Mac/Linux).

To make it fully accessible (NOT recommended for production):
Edit `docker-compose.yml`:
```yaml
ports:
  - "0.0.0.0:5000:5000"  # Accessible from anywhere
```

## Performance

Docker is efficient. The image is ~500MB with all dependencies. Container starts in ~5-10 seconds.

## Production Deployment

For production, use Gunicorn instead of Flask dev server:

```bash
# In docker-compose.yml, change:
# command: gunicorn --bind 0.0.0.0:5000 --workers 4 app:app

# Or in Dockerfile, change:
# CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
```

## That's It!

You now have a complete, isolated, reproducible environment. No Python version conflicts, no dependency issues, no virtual environment headaches. Just Docker! 🎉

---

**Note:** The `run.sh`, `run.bat`, and `run_app.py` files are alternatives for native Python setups. You don't need them if you use Docker.
