#!/bin/bash
# Setup script for Polymarket V6

set -e

echo "🚀 Setting up Polymarket V6..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create data directory
mkdir -p data

# Test import
echo "Testing imports..."
python -c "from src.scanner import Scanner; print('✓ All imports OK')"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Usage:"
echo "  source venv/bin/activate"
echo "  python -m src.scanner --full --limit 100   # Test with 100 markets"
echo "  python -m src.scanner --incremental        # Process new markets only"
echo "  python -m src.scanner --opportunities      # Show opportunities"
