#!/bin/bash

# Smart Terminal macOS App Installation Script

set -e

APP_NAME="SmartTerminal"
BUNDLE_NAME="SmartTerminal.app"
INSTALL_DIR="/Applications"
BUILD_DIR="build"

echo "🚀 Installing Smart Terminal macOS app..."
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This script is designed for macOS only."
    exit 1
fi

# Check macOS version
MACOS_VERSION=$(sw_vers -productVersion)
REQUIRED_VERSION="13.0"

if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$MACOS_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
    echo "❌ macOS $REQUIRED_VERSION or later is required. You have $MACOS_VERSION"
    exit 1
fi

echo "✅ macOS version check passed: $MACOS_VERSION"

# Check if Xcode Command Line Tools are installed
if ! command -v swift &> /dev/null; then
    echo "📦 Installing Xcode Command Line Tools..."
    xcode-select --install
    echo "⏳ Please wait for Xcode Command Line Tools to install, then run this script again."
    exit 0
fi

echo "✅ Xcode Command Line Tools found"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    echo "Please install Python 3 from https://www.python.org/downloads/"
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Build the app if needed
if [ ! -d "$BUILD_DIR/$BUNDLE_NAME" ]; then
    echo "🔨 Building the app..."
    if [ -f "build.sh" ]; then
        ./build.sh
    else
        git submodule update --init --recursive
        swift build --package-path . -c release --product SmartTerminalApp
        
        # Manual app bundle creation
        mkdir -p "$BUILD_DIR/$BUNDLE_NAME/Contents/MacOS"
        mkdir -p "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources"
        
        cp "../.build/release/SmartTerminalApp" "$BUILD_DIR/$BUNDLE_NAME/Contents/MacOS/"
        cp Info.plist "$BUILD_DIR/$BUNDLE_NAME/Contents/"
        cp -r Resources/* "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources/"
        
        # Copy web server files
        echo "🌐 Copying web server files..."
        mkdir -p "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources/web"
        cp -r ../web_app.py ../templates ../static ../smart_terminal "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources/web/"
        cp ../requirements.txt "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources/web/"
        
        # Create the macOS-specific web server launcher
        cat > "$BUILD_DIR/$BUNDLE_NAME/Contents/Resources/web/web_app_macos.py" << 'EOF'
import os
import sys

# Add the web resources to Python path
web_resources = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, web_resources)

# Set working directory to web resources
os.chdir(os.path.dirname(__file__))

# Import and run the web app
exec(open('web_app.py').read())
EOF
    fi
fi

if [ ! -d "$BUILD_DIR/$BUNDLE_NAME" ]; then
    echo "❌ Build failed. App bundle not found."
    exit 1
fi

echo "✅ App built successfully"

# Stop any existing instance
echo "🔄 Stopping any existing instances..."
pkill -f "$APP_NAME" || true
sleep 2

# Install the app
echo "📦 Installing to Applications folder..."
if [ -d "$INSTALL_DIR/$BUNDLE_NAME" ]; then
    echo "🗑️  Removing existing installation..."
    sudo rm -rf "$INSTALL_DIR/$BUNDLE_NAME"
fi

sudo cp -R "$BUILD_DIR/$BUNDLE_NAME" "$INSTALL_DIR/"
echo "✅ App installed to $INSTALL_DIR"

# Set up local domain
echo "🌐 Setting up local domain..."
DOMAIN_MAPPING="127.0.0.1\tsmartterminal"
HOSTS_FILE="/etc/hosts"

if ! grep -q "smartterminal" "$HOSTS_FILE"; then
    echo "📝 Adding smartterminal to /etc/hosts..."
    echo "# Smart Terminal Local Domain" | sudo tee -a "$HOSTS_FILE"
    echo -e "$DOMAIN_MAPPING" | sudo tee -a "$HOSTS_FILE"
    echo "✅ Local domain configured"
else
    echo "✅ Local domain already configured"
fi

# Set permissions
echo "🔒 Setting permissions..."
sudo chmod -R 755 "$INSTALL_DIR/$BUNDLE_NAME"
sudo chown -R "$(whoami):staff" "$INSTALL_DIR/$BUNDLE_NAME"

# Install Python dependencies for the web server
echo "🐍 Installing Python dependencies..."
pip3 install --user -r "$INSTALL_DIR/$BUNDLE_NAME/Contents/Resources/web/requirements.txt"

# Create startup agent (optional)
CREATE_LAUNCH_AGENT=${CREATE_LAUNCH_AGENT:-false}
if [ "$CREATE_LAUNCH_AGENT" = true ]; then
    echo "🚀 Creating launch agent for auto-startup..."
    AGENT_DIR="$HOME/Library/LaunchAgents"
    AGENT_FILE="com.smartterminal.app.plist"
    
    mkdir -p "$AGENT_DIR"
    
    cat > "$AGENT_DIR/$AGENT_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.smartterminal.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>open</string>
        <string>$INSTALL_DIR/$BUNDLE_NAME</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF
    
    launchctl load "$AGENT_DIR/$AGENT_FILE"
    echo "✅ Launch agent installed"
fi

# Open the app
echo "🎉 Launching Smart Terminal..."
open "$INSTALL_DIR/$BUNDLE_NAME"

echo ""
echo "✅ Installation complete!"
echo ""
echo "📍 App location: $INSTALL_DIR/$BUNDLE_NAME"
echo "🌐 Web interface: http://smartterminal:5001"
echo "🌐 Alternative: http://localhost:5001"
echo ""
echo "📋 Quick Start:"
echo "   1. Look for the terminal icon in your menu bar"
echo "   2. Click to open the Smart Terminal interface"
echo "   3. The app will auto-start with your Mac"
echo ""
echo "🔧 Uninstall:"
echo "   sudo rm -rf '$INSTALL_DIR/$BUNDLE_NAME'"
echo "   sudo sed -i '' '/smartterminal/d' /etc/hosts"
echo ""
echo "🎉 Enjoy Smart Terminal!"