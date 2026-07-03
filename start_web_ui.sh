#!/bin/bash

# Smart Terminal Web UI Launcher
# This script starts the web UI for managing Smart Terminal conversations

echo "🚀 Starting Smart Terminal Web UI..."
echo "📍 Web UI will be available at: http://localhost:5001"
echo "📍 API endpoints: http://localhost:5001/api"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is required but not installed."
    exit 1
fi

# Check if required packages are installed
echo "📦 Checking dependencies..."
if ! python3 -c "import flask, flask_cors" 2>/dev/null; then
    echo "📦 Installing required packages..."
    pip3 install flask flask-cors
fi

# Start the web application
echo "🌐 Starting Flask development server..."
python3 web_app.py