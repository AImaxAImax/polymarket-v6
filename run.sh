#!/bin/bash

# V6 Alpha Hunter — Quick Start Script
# =====================================
#
# Usage:
#   ./run.sh scan          # Scan for opportunities
#   ./run.sh paper         # Start paper trading
#   ./run.sh live          # Start live trading (requires confirmation)
#   ./run.sh status        # Show current status
#   ./run.sh report        # Show learning report
#   ./run.sh dashboard     # Start web dashboard
#   ./run.sh help          # Show this help

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           🎯 V6 Alpha Hunter — Polymarket Bot                 ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_help() {
    print_header
    echo "Usage: ./run.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  scan              Scan all markets for alpha opportunities"
    echo "  paper             Start paper trading (simulated)"
    echo "  live              Start live trading (real money!)"
    echo "  status            Show current positions and P&L"
    echo "  report            Show learning/performance report"
    echo "  dashboard         Start web dashboard on port 8898"
    echo "  test              Run tests"
    echo "  help              Show this help message"
    echo ""
    echo "Options for 'scan':"
    echo "  --max-markets N   Limit scan to N markets"
    echo "  --top N           Research top N opportunities (default: 50)"
    echo ""
    echo "Options for 'paper' / 'live':"
    echo "  --capital N       Initial capital in USD (default: 10000)"
    echo "  --interval H      Hours between scans (default: 1)"
    echo ""
    echo "Examples:"
    echo "  ./run.sh scan --max-markets 100 --top 20"
    echo "  ./run.sh paper --capital 5000 --interval 0.5"
    echo "  ./run.sh live --confirm"
    echo ""
}

case "${1:-help}" in
    scan)
        print_header
        echo -e "${GREEN}🔍 Starting market scan...${NC}"
        shift
        python -m src.bot scan "$@"
        ;;
    
    paper)
        print_header
        echo -e "${YELLOW}📄 Starting PAPER trading mode...${NC}"
        echo -e "${YELLOW}   This is simulated trading - no real money involved${NC}"
        echo ""
        shift
        python -m src.bot run --paper "$@"
        ;;
    
    live)
        print_header
        echo -e "${RED}💰 LIVE TRADING MODE${NC}"
        echo -e "${RED}   ⚠️  WARNING: This uses REAL MONEY!${NC}"
        echo ""
        
        if [[ "$*" != *"--confirm"* ]]; then
            echo -e "${RED}   You must add --confirm to acknowledge live trading${NC}"
            echo -e "${RED}   Example: ./run.sh live --confirm${NC}"
            exit 1
        fi
        
        shift
        python -m src.bot run --live "$@"
        ;;
    
    status)
        print_header
        python -m src.bot status
        ;;
    
    report)
        print_header
        python -m src.bot report
        ;;
    
    dashboard)
        print_header
        echo -e "${GREEN}🌐 Starting dashboard on http://localhost:8898${NC}"
        echo ""
        python -m src.dashboard
        ;;
    
    test)
        print_header
        echo -e "${GREEN}🧪 Running tests...${NC}"
        pytest tests/ -v
        ;;
    
    help|--help|-h)
        print_help
        ;;
    
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        print_help
        exit 1
        ;;
esac
