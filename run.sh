#!/usr/bin/env bash
# ==============================================================================
# Warehouse Layout & Order Picking Optimizer - Startup Script
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
PORT="${PORT:-5001}"
HOST="${HOST:-0.0.0.0}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASS="${DB_PASS:-}"
DB_NAME="${DB_NAME:-wareopt}"

# Virtual environment resolution (.venv or venv)
if [ -d "$SCRIPT_DIR/.venv" ]; then
    VENV_DIR="$SCRIPT_DIR/.venv"
elif [ -d "$SCRIPT_DIR/venv" ]; then
    VENV_DIR="$SCRIPT_DIR/venv"
else
    VENV_DIR="$SCRIPT_DIR/.venv"
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
    echo -e "${BOLD}Commands:${RESET}"
    echo -e "  ${GREEN}(default)${RESET}        Start the Flask web application and frontend"
    echo -e "  ${GREEN}start${RESET}            Start the Flask web application"
    echo -e "  ${GREEN}seed${RESET}             Seed the MySQL database (schema + sample data)"
    echo -e "  ${GREEN}--seed | all${RESET}     Seed the database and then launch the web application"
    echo -e "  ${GREEN}help | --help${RESET}    Display this help message"
    echo ""
    echo -e "${BOLD}Environment Variables:${RESET}"
    echo -e "  PORT             Port for Flask server (default: 5001)"
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
        echo -e "${GREEN}Virtual environment created successfully.${RESET}"
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
        echo -e "${GREEN}Dependencies installed successfully.${RESET}"
    fi
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
        echo -e "${RED}⚠️  Could not connect to MySQL at 127.0.0.1:3306 (Connection refused).${RESET}"
        echo -e "${YELLOW}Please make sure MySQL is started: sudo /usr/local/mysql/support-files/mysql.server start${RESET}"
        exit 1
    fi
}

seed_db() {
    ensure_db_auth
    echo -e "${BLUE}▶ Initializing and seeding MySQL database...${RESET}"
    "$PYTHON_BIN" database/seed.py
    echo -e "${GREEN}✔ Database seeded successfully!${RESET}"
}

check_and_prepare_db() {
    ensure_db_auth
    local status
    status=$("$PYTHON_BIN" -c "
import os, sys, pymysql

try:
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASS', '')
    )
    cur = conn.cursor()
    cur.execute(\"SHOW DATABASES LIKE 'wareopt'\")
    if not cur.fetchone():
        print('NEED_SEED')
        sys.exit(0)
    conn.select_db('wareopt')
    cur.execute(\"SELECT COUNT(*) FROM shelves\")
    count = cur.fetchone()[0]
    if count == 0:
        print('NEED_SEED')
    else:
        print('READY')
    conn.close()
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)

    if [[ "$status" == "NEED_SEED" ]]; then
        echo -e "${YELLOW}Database 'wareopt' is empty or not yet seeded. Auto-seeding now...${RESET}"
        seed_db
    elif [[ "$status" == "READY" ]]; then
        echo -e "${GREEN}✔ MySQL database 'wareopt' connected and verified.${RESET}"
    fi
}

start_server() {
    print_banner
    echo -e "${GREEN}✔ Python environment ready!${RESET}"
    check_and_prepare_db
    echo -e "${BOLD}Starting Flask server on:${RESET} ${CYAN}http://127.0.0.1:${PORT}${RESET}"
    echo ""
    echo -e "${BOLD}Available Web Pages:${RESET}"
    echo -e "  • Dashboard:        ${CYAN}http://127.0.0.1:${PORT}/${RESET}"
    echo -e "  • Products Catalog: ${CYAN}http://127.0.0.1:${PORT}/products.html${RESET}"
    echo -e "  • Layout Optimizer: ${CYAN}http://127.0.0.1:${PORT}/layout.html${RESET}"
    echo -e "  • Warehouse Graph:  ${CYAN}http://127.0.0.1:${PORT}/graph.html${RESET}"
    echo -e "  • Order Picking:    ${CYAN}http://127.0.0.1:${PORT}/order-picking.html${RESET}"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop the server.${RESET}"
    echo "------------------------------------------------------------------"

    export PORT="$PORT"
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
