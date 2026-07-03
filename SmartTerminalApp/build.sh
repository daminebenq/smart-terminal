#!/bin/bash

# SmartTerminal macOS Build Script

set -e

APP_NAME="SmartTerminalApp"
BUILD_DIR="build"
APP_BUNDLE="SmartTerminal.app"

echo "🚀 Building SmartTerminal macOS app..."

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$BUILD_DIR"
rm -rf "$APP_BUNDLE"

# Create app bundle structure
echo "📦 Creating app bundle..."
mkdir -p "$BUILD_DIR/$APP_BUNDLE/Contents/MacOS"
mkdir -p "$BUILD_DIR/$APP_BUNDLE/Contents/Resources"
mkdir -p "$BUILD_DIR/$APP_BUNDLE/Contents/Frameworks"

# Copy resources
echo "📋 Copying resources..."
cp Resources/*.entitlements "$BUILD_DIR/$APP_BUNDLE/Contents/"
cp Info.plist "$BUILD_DIR/$APP_BUNDLE/Contents/"
cp -r Resources/Assets.xcassets "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/"

# Build the Swift app
echo "🔨 Building Swift app..."
cd ../
swift build --package-path SmartTerminalApp -c release --product SmartTerminalApp

# Copy the built binary
echo "📋 Copying binary..."
cp ".build/release/$APP_NAME" "SmartTerminalApp/$BUILD_DIR/$APP_BUNDLE/Contents/MacOS/"

# Create symbolic link for Resources
echo "🔗 Creating symbolic links..."
cd "SmartTerminalApp/$BUILD_DIR/$APP_BUNDLE/Contents/"
ln -sf Resources Resources

# Set executable permissions
echo "🔒 Setting permissions..."
chmod +x MacOS/SmartTerminalApp

# Go back to project root
cd ../../

# Copy web server files
echo "🌐 Copying web server files..."
mkdir -p "../$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web"
cp -r ../templates "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp -r ../static "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp ../web_app.py "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp ../requirements.txt "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp -r ../smart_terminal "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp -r ../scripts "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/"
cp *.sh "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/" 2>/dev/null || true

# Modify the app to find web files in the bundle
echo "🔧 Updating web server paths..."
cat > "$BUILD_DIR/$APP_BUNDLE/Contents/Resources/web/web_app_macos.py" << 'EOF'
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

echo "✅ Build complete!"
echo "📁 App bundle location: $(pwd)/$BUILD_DIR/$APP_BUNDLE"
echo ""
echo "To run the app:"
echo "open $BUILD_DIR/$APP_BUNDLE"
echo ""
echo "To install the app:"
echo "sudo cp -R $BUILD_DIR/$APP_BUNDLE /Applications/"
echo ""

# Optional: Create installer
CREATE_INSTALLER=${CREATE_INSTALLER:-false}
if [ "$CREATE_INSTALLER" = true ]; then
    echo "📦 Creating installer..."
    pkgbuild --root "$BUILD_DIR/$APP_BUNDLE" \
             --identifier com.smartterminal.app \
             --version 1.0 \
             --install-location "/Applications" \
             --sign "Developer ID Installer: Your Name (TEAM_ID)" \
             "$APP_NAME.pkg"
    echo "📦 Installer created: $APP_NAME.pkg"
fi