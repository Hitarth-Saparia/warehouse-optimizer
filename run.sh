#!/usr/bin/env bash
# ==============================================================================
# Warehouse Layout & Order Picking Optimizer - Central Management Script
# ==============================================================================

set -e

# Change directory to the root of the project
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure root directory is on PYTHONPATH for module imports
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Load .env file if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Colors for terminal styling
BOLD="\033[1m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
RED="\033[0;31m"
RESET="\033[0m"

# Default configuration
PORT="${PORT:-5050}"
HOST="${HOST:-0.0.0.0}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASS="${DB_PASS:-}"
DB_NAME="${DB_NAME:-wareopt}"

# Virtual environment resolution (.venv or venv)
if [ -d "$SCRIPT_DIR/venv" ]; then
    VENV_DIR="$SCRIPT_DIR/venv"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"
else
    VENV_DIR="$SCRIPT_DIR/venv"
fi

print_banner() {
    echo -e "${CYAN}${BOLD}"
    echo "=================================================================="
    echo "       WAREHOUSE LAYOUT & ORDER PICKING OPTIMIZER                 "
    echo "=================================================================="
    echo -e "${RESET}"
}

print_help() {
    print_banner
    echo -e "${BOLD}Usage:${RESET} ./run.sh [command]"
    echo ""
    echo -e "${BOLD}Available Commands:${RESET}"
    echo -e "  ${GREEN}start | (default)${RESET}  Start the Flask web application server"
    echo -e "  ${GREEN}seed${RESET}             Seed the database (MySQL schema + sample data or SQLite)"
    echo -e "  ${GREEN}--seed | all${RESET}     Seed the database and launch the web application server"
    echo -e "  ${GREEN}test | tests${RESET}     Run complete unit & integration test suites (27 tests)"
    echo -e "  ${GREEN}install | deps${RESET}   Install or update Python dependencies in virtualenv"
    echo -e "  ${GREEN}mysql-start${RESET}      Start the local MySQL daemon service"
    echo -e "  ${GREEN}mysql-stop${RESET}       Stop the local MySQL daemon service"
    echo -e "  ${GREEN}mysql-status${RESET}     Check status of the local MySQL service"
    echo -e "  ${GREEN}clean${RESET}            Clean build caches, __pycache__, and temporary files"
    echo -e "  ${GREEN}help | --help | -h${RESET} Display this help menu"
    echo ""
    echo -e "${BOLD}Environment Variables:${RESET}"
    echo -e "  PORT             Port for Flask server (default: 5050)"
    echo -e "  DB_HOST          MySQL host (default: 127.0.0.1)"
    echo -e "  DB_PORT          MySQL port (default: 3306)"
    echo -e "  DB_USER          MySQL user (default: root)"
    echo -e "  DB_PASS          MySQL password (saved in .env)"
    echo -e "  DB_NAME          MySQL database name (default: wareopt)"
    echo ""
}

ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Virtual environment not found. Creating at $VENV_DIR...${RESET}"
        python3 -m venv "$VENV_DIR"
        echo -e "${GREEN}✔ Virtual environment created successfully.${RESET}"
    fi

    # Explicitly point to the virtualenv binaries
    PYTHON_BIN="$VENV_DIR/bin/python"
    export PATH="$VENV_DIR/bin:$PATH"
    export VIRTUAL_ENV="$VENV_DIR"

    # Verify python binary exists
    if [ ! -f "$PYTHON_BIN" ]; then
        echo -e "${RED}Error: Python executable not found at $PYTHON_BIN${RESET}"
        exit 1
    fi

    # Check if required packages are installed
    if ! "$PYTHON_BIN" -c "import flask, flask_cors, pymysql" 2>/dev/null; then
        echo -e "${YELLOW}Installing dependencies from backend/requirements.txt...${RESET}"
        "$PYTHON_BIN" -m pip install -r backend/requirements.txt
        echo -e "${GREEN}✔ Dependencies installed successfully.${RESET}"
    fi
}

install_dependencies() {
    ensure_venv
    echo -e "${BLUE}▶ Installing / updating dependencies from backend/requirements.txt...${RESET}"
    "$PYTHON_BIN" -m pip install -r backend/requirements.txt
    echo -e "${GREEN}✔ All dependencies installed successfully!${RESET}"
}

ensure_db_auth() {
    # Test connection and ask for password if Access Denied (1045)
    local test_code
    test_code=$("$PYTHON_BIN" -c "
import os, sys, pymysql
try:
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASS', '')
    )
    conn.close()
    print('OK')
except pymysql.OperationalError as e:
    if e.args[0] == 1045:
        print('AUTH_FAILED')
    elif e.args[0] == 2003:
        print('REFUSED')
    else:
        print(f'ERROR:{e.args[0]}')
except Exception as e:
    print(f'EXC:{e}')
" 2>/dev/null || echo "FAIL")

    if [ "$test_code" = "AUTH_FAILED" ]; then
        echo -e "${YELLOW}MySQL authentication required for user '${BOLD}${DB_USER:-root}${RESET}${YELLOW}'.${RESET}"
        read -s -p "Enter MySQL password: " entered_password
        echo ""
        export DB_PASS="$entered_password"

        # Verify password
        local verify_code
        verify_code=$("$PYTHON_BIN" -c "
import os, pymysql
try:
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASS', '')
    )
    conn.close()
    print('OK')
except Exception:
    print('FAIL')
" 2>/dev/null || echo "FAIL")

        if [ "$verify_code" = "OK" ]; then
            echo -e "${GREEN}✔ Password verified!${RESET}"
            echo "DB_PASS=\"$entered_password\"" > "$SCRIPT_DIR/.env"
            chmod 600 "$SCRIPT_DIR/.env"
            echo -e "${CYAN}Saved to .env (you won't have to enter it again).${RESET}"
        else
            echo -e "${RED}❌ Incorrect MySQL password. Please try again.${RESET}"
            exit 1
        fi
    elif [ "$test_code" = "REFUSED" ]; then
        echo -e "${YELLOW}⚠️  MySQL server is not running at 127.0.0.1:3306.${RESET}"
        echo -e "${CYAN}ℹ️  Falling back to local SQLite database (database/wareopt.sqlite)...${RESET}"
        echo -e "${YELLOW}Tip: To start MySQL instead, run: ./run.sh mysql-start${RESET}"
        return 0
    fi
}

seed_db() {
    ensure_db_auth
    echo -e "${BLUE}▶ Initializing and seeding database...${RESET}"
    "$PYTHON_BIN" database/seed.py
    echo -e "${GREEN}✔ Database seeded successfully!${RESET}"
}

check_and_prepare_db() {
    ensure_db_auth
    local status
    status=$("$PYTHON_BIN" -c "
import sys
try:
    from backend.db import get_db_connection, ACTIVE_DB_TYPE
    conn = get_db_connection()
    conn.close()
    print(f'READY_{ACTIVE_DB_TYPE.upper()}')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)

    if [[ "$status" == *"READY_MYSQL"* ]]; then
        echo -e "${GREEN}✔ MySQL database 'wareopt' connected and verified.${RESET}"
    elif [[ "$status" == *"READY_SQLITE"* ]]; then
        echo -e "${GREEN}✔ Resilient SQLite database active and ready (zero setup required).${RESET}"
    fi
}

run_tests() {
    ensure_venv
    echo -e "${BLUE}▶ Running unit and integration test suite...${RESET}"
    "$PYTHON_BIN" -m pytest tests/ -v
    echo -e "${GREEN}✔ All tests executed successfully!${RESET}"
}

mysql_control() {
    local action="$1"
    if [ -f "/usr/local/mysql/support-files/mysql.server" ]; then
        echo -e "${BLUE}▶ Executing: sudo /usr/local/mysql/support-files/mysql.server $action${RESET}"
        sudo /usr/local/mysql/support-files/mysql.server "$action"
    else
        echo -e "${RED}Error: MySQL support-files script not found at /usr/local/mysql/support-files/mysql.server${RESET}"
        exit 1
    fi
}

clean_cache() {
    echo -e "${BLUE}▶ Cleaning temporary Python build caches and bytecode...${RESET}"
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    echo -e "${GREEN}✔ Caches cleaned successfully!${RESET}"
}

open_in_chrome() {
    local url="http://127.0.0.1:${PORT}"
    (
        # Wait up to 6 seconds for Flask server to start responding
        for i in {1..20}; do
            if curl -s -o /dev/null "$url" 2>/dev/null; then
                break
            fi
            sleep 0.3
        done

        # Open in Chrome directly
        if [ "$(uname)" = "Darwin" ]; then
            if open -a "Google Chrome" "$url" 2>/dev/null; then
                :
            else
                open "$url" 2>/dev/null || true
            fi
        elif command -v google-chrome >/dev/null 2>&1; then
            google-chrome "$url" >/dev/null 2>&1 &
        elif command -v google-chrome-stable >/dev/null 2>&1; then
            google-chrome-stable "$url" >/dev/null 2>&1 &
        elif command -v chromium >/dev/null 2>&1; then
            chromium "$url" >/dev/null 2>&1 &
        elif command -v chromium-browser >/dev/null 2>&1; then
            chromium-browser "$url" >/dev/null 2>&1 &
        elif command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$url" >/dev/null 2>&1 &
        fi
    ) >/dev/null 2>&1 &
}

start_server() {
    print_banner
    echo -e "${GREEN}✔ Python environment ready!${RESET}"
    check_and_prepare_db
    echo -e "${BOLD}Starting Flask server on:${RESET} ${CYAN}http://127.0.0.1:${PORT}${RESET}"
    echo ""
    echo -e "${BOLD}Available Web Pages:${RESET}"
    echo -e "  • Landing Page:     ${CYAN}http://127.0.0.1:${PORT}/${RESET}"
    echo -e "  • Dashboard:        ${CYAN}http://127.0.0.1:${PORT}/index.html${RESET}"
    echo -e "  • Products Catalog: ${CYAN}http://127.0.0.1:${PORT}/products.html${RESET}"
    echo -e "  • Layout Optimizer: ${CYAN}http://127.0.0.1:${PORT}/layout.html${RESET}"
    echo -e "  • Warehouse Graph:  ${CYAN}http://127.0.0.1:${PORT}/graph.html${RESET}"
    echo -e "  • Order Picking:    ${CYAN}http://127.0.0.1:${PORT}/order-picking.html${RESET}"
    echo ""
    echo -e "${GREEN}🚀 Opening application in Google Chrome...${RESET}"
    echo -e "${YELLOW}Press Ctrl+C to stop the server.${RESET}"
    echo "------------------------------------------------------------------"

    export PORT="$PORT"
    open_in_chrome
    "$PYTHON_BIN" backend/app.py
}

# Main routing logic
case "$1" in
    help|--help|-h)
        print_help
        exit 0
        ;;
    seed)
        ensure_venv
        seed_db
        ;;
    --seed|all)
        ensure_venv
        seed_db
        echo ""
        start_server
        ;;
    test|tests)
        run_tests
        ;;
    install|deps)
        install_dependencies
        ;;
    mysql-start)
        mysql_control "start"
        ;;
    mysql-stop)
        mysql_control "stop"
        ;;
    mysql-status)
        mysql_control "status"
        ;;
    clean)
        clean_cache
        ;;
    start|"")
        ensure_venv
        start_server
        ;;
    *)
        echo -e "${RED}Unknown argument: $1${RESET}"
        print_help
        exit 1
        ;;
esac
