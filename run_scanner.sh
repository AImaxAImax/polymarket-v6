#!/bin/bash
cd /home/max/projects/polymarket-v6
source venv/bin/activate
export PYTHONUNBUFFERED=1
python full_scan.py 2>&1 | tee /tmp/scanner.log
