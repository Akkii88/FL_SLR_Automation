#!/usr/bin/env bash
# ============================================================
# FL-SLR Automation - Run Script
# ============================================================
# Usage:
#   ./run.sh              # Start the API server
#   ./run.sh init-db      # Initialize the database
#   ./run.sh test         # Run tests
#   ./run.sh demo         # Load demo/test data
# ============================================================

# Detect Python command
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo -e "${RED}[ERROR]${NC} Python not found. Install Python 3.11+."
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║           FL-SLR: Federated Learning SLR Tool           ║"
    echo "║  \"Is 'Best' Really Best?\"                               ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

init_db() {
    echo -e "${GREEN}[INIT]${NC} Initializing database..."
    $PYTHON -m app.db.init_db
    echo -e "${GREEN}[INIT]${NC} Database initialized successfully."
}

run_tests() {
    echo -e "${YELLOW}[TEST]${NC} Running tests..."
    $PYTHON -m pytest tests/ -v --tb=short
}

run_server() {
    echo -e "${GREEN}[SERVER]${NC} Starting FL-SLR API server..."
    echo -e "${GREEN}[SERVER]${NC} URL: http://127.0.0.1:8000"
    echo -e "${GREEN}[SERVER]${NC} Docs: http://127.0.0.1:8000/docs"
    echo ""
    $PYTHON -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
}

load_demo() {
    echo -e "${YELLOW}[DEMO]${NC} Loading demo data..."
    $PYTHON -m app.utils.demo_data
}

# Main
print_header

case "${1:-serve}" in
    init-db)
        init_db
        ;;
    test)
        run_tests
        ;;
    demo)
        load_demo
        ;;
    serve)
        run_server
        ;;
    *)
        echo -e "${RED}[ERROR]${NC} Unknown command: $1"
        echo "Usage: ./run.sh [serve|init-db|test|demo]"
        exit 1
        ;;
esac
