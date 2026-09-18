#!/bin/bash
# Restart CorkJobHunter (data persists in data.db)
cd "$(dirname "$0")"
pip install -q flask requests beautifulsoup4 lxml 2>/dev/null
python3 app.py
