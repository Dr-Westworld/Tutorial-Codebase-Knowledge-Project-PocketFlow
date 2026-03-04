#!/bin/bash

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"
VENV_PATH="$PROJECT_ROOT/venv"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Code Tutorial Generator - Web App${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

# Step 1: Create virtual environment if it doesn't exist
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv "$VENV_PATH"
    if [ $? -ne 0 ]; then
        echo -e "${RED}Error: Failed to create virtual environment${NC}"
        exit 1
    fi
    echo -e "${GREEN}Virtual environment created successfully!${NC}"
else
    echo -e "${GREEN}Virtual environment already exists${NC}"
fi

# Step 2: Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source "$VENV_PATH/bin/activate"

# Step 3: Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip

# Step 4: Install requirements
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    echo -e "${YELLOW}Installing main requirements...${NC}"
    pip install -r "$PROJECT_ROOT/requirements.txt"
fi

if [ -f "$PROJECT_ROOT/requirements-app.txt" ]; then
    echo -e "${YELLOW}Installing app requirements...${NC}"
    pip install -r "$PROJECT_ROOT/requirements-app.txt"
fi

# Step 5: Run the Flask app
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Starting Flask Application${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}URL: http://localhost:5000${NC}"
echo -e "${GREEN}Press Ctrl+C to stop the server${NC}"
echo -e "${GREEN}========================================${NC}\n"

cd "$PROJECT_ROOT"
python app.py
