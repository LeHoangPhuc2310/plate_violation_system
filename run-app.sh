#!/bin/bash
# Script để chạy app với config đúng

# Set environment variables
export FLASK_DEBUG=0
export FLASK_ENV=production
export PORT=${PORT:-5001}

# Unset any conflicting variables
unset FLASK_APP

echo "Environment:"
echo "  PORT=$PORT"
echo "  FLASK_DEBUG=$FLASK_DEBUG"
echo "  FLASK_ENV=$FLASK_ENV"
echo ""

# Run app
python3 app.py

