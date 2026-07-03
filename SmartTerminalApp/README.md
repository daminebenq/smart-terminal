# Smart Terminal macOS App

A native macOS application wrapper for the Smart Terminal web interface, providing seamless integration with macOS and auto-startup capabilities.

## 🚀 Features

- **Native macOS Integration**: SwiftUI-based app with system tray integration
- **Auto-Startup**: Automatically launches at system startup
- **Local Domain**: Configures `smartterminal` local domain for easy access
- **Background Service**: Runs the web server silently in the background
- **Status Bar Menu**: Quick access controls from the system menu bar
- **WebView Wrapper**: Full-featured web interface in native macOS window
- **Sandbox Support**: Secure macOS app sandbox with appropriate permissions

## 📦 Installation

### Option 1: Building from Source

```bash
# Clone the repository
git clone https://github.com/daminebenq/smart-terminal.git
cd smart-terminal/SmartTerminalApp

# Build the app (requires Xcode 14+ and macOS 13+)
./build.sh

# Install the app
sudo cp -R build/SmartTerminal.app /Applications/

# Launch the app
open /Applications/SmartTerminal.app
```

### Option 2: Direct Binary Distribution

1. Download the latest `SmartTerminal.app` from releases
2. Drag to `/Applications` folder
3. Launch from Launchpad or Applications folder

## ⚙️ Configuration

### Local Domain Setup

The app automatically configures the `smartterminal` local domain by adding to `/etc/hosts`:

```bash
127.0.0.1 smartterminal
```

**Note**: This requires admin privileges. The app will prompt for password if needed.

### Auto-Startup

The app enables "Launch at Login" by default. You can manage this via:

1. **System Bar Menu**: Right-click the terminal icon in the menu bar
2. **System Preferences** → **Login Items**
3. In-app toggle in the menu bar dropdown

### Web Server Configuration

The embedded Flask web server runs on:
- **Host**: `0.0.0.0` (all interfaces)
- **Port**: `5001`
- **URLs**: 
  - `http://localhost:5001` (local access)
  - `http://smartterminal:5001` (domain access)

## 🔧 Development

### Prerequisites

- macOS 13.0 or later
- Xcode 14.0 or later
- Swift 5.9 or later
- Python 3.8+ (for web server)

### Development Setup

```bash
# Install Swift dependencies
cd SmartTerminalApp
swift package resolve

# Build in development mode
swift build

# Run directly
swift run SmartTerminalApp

# Or open in Xcode
open SmartTerminalApp.xcodeproj
```

### Project Structure

```
SmartTerminalApp/
├── Sources/
│   └── SmartTerminalApp.swift      # Main SwiftUI app
├── Resources/
│   ├── Info.plist                  # App metadata
│   ├── SmartTerminalApp.entitlements # Sandbox permissions
│   └── Assets.xcassets/            # App icons and assets
├── Package.swift                   # Swift package config
├── build.sh                        # Build script
└── SmartTerminalApp.xcodeproj/     # Xcode project
```

## 🔐 Security & Permissions

The app requests the following permissions via sandbox:

- **Network Client**: Access localhost for web server
- **Network Server**: Run the embedded web server
- **File Access**: Read/write to downloads and user-selected files
- **App Sandbox**: Run in secure macOS sandbox

### Entitlements

```xml
<key>com.apple.security.app-sandbox</key>
<true/>
<key>com.apple.security.network.server</key>
<true/>
<key>com.apple.security.network.client</key>
<true/>
<key>com.apple.security.files.user-selected.read-write</key>
<true/>
```

## 🐛 Troubleshooting

### App Won't Start

1. **Check macOS Version**: Ensure you're running macOS 13.0+
2. **Verify Permissions**: Allow any security prompts that appear
3. **Check Console App**: Look for crash reports in Console.app

### Local Domain Not Working

1. **Hosts File**: Check if `smartterminal` is in `/etc/hosts`
2. **DNS Flush**: Run `sudo dscacheutil -flushcache`
3. **Manual Setup**: Add manually to `/etc/hosts` and lock the file

### Web Server Issues

1. **Port Conflict**: Check if port 5001 is in use
2. **Python Dependencies**: Ensure Python and required modules are installed
3. **Check Logs**: Use Console.app to see web server output

### Common Solutions

```bash
# Reset hosts file
sudo vim /etc/hosts
# Add: 127.0.0.1 smartterminal

# Kill processes on port 5001
lsof -ti:5001 | xargs kill -9

# Flush DNS cache
sudo dscacheutil -flushcache
```

## 🔄 Updates

The app checks for updates automatically. You can also:

1. **Manual Check**: Menu bar → Check for Updates
2. **GitHub Releases**: Download latest from [releases page](https://github.com/daminebenq/smart-terminal/releases)

## 📱 System Integration

### Menu Bar Features

- **Quick Access**: Open Smart Terminal window
- **Server Control**: Start/stop background service
- **Launch Settings**: Toggle auto-startup
- **Quit**: Exit the application

### Keyboard Shortcuts

- **⌘+Shift+N**: New chat session
- **⌘+Shift+U**: Check for updates
- **⌘+Q**: Quit app (from main window)

### System Integration

- **Spotlight Search**: Find "Smart Terminal" in Spotlight
- **Touch Bar**: Support on compatible MacBooks
- **Dark Mode**: Full dark mode support
- **Notifications**: System notifications for important events

## 🔍 Logging & Debugging

### Location of Logs

- ** Console App**: Filter for "SmartTerminalApp"
- **App Logs**: `~/Library/Logs/com.smartterminal.app/`
- **Server Logs**: Console app output

### Debug Mode

For development builds, the app includes additional debugging:

1. **Developer Extras**: WebView developer tools
2. **Verbose Logging**: Detailed console output
3. **Debug Menu**: Additional options in debug builds

## 🚢 Distribution

### Building for Release

```bash
# Build release version
./build.sh

# Optionally create installer
CREATE_INSTALLER=true ./build.sh
```

### Code Signing

For distribution outside the Mac App Store:

1. **Apple Developer Account**: Required for code signing
2. **Certificate**: "Developer ID Application" certificate
3. **Notarization**: Submit to Apple for notarization

### Package Contents

```
SmartTerminal.app/
├── Contents/
│   ├── Info.plist
│   ├── MacOS/
│   │   └── SmartTerminalApp       # Main binary
│   ├── Resources/
│   │   ├── Assets.xcassets/       # Icons
│   │   ├── web/                   # Web server files
│   │   │   ├── templates/
│   │   │   ├── static/
│   │   │   ├── web_app.py
│   │   │   └── ...
│   │   └── SmartTerminalApp.entitlements
│   └── Frameworks/                # Dependencies
```

## 🤝 Contributing

To contribute to the macOS app:

1. **Fork the repository** on GitHub
2. **Create a feature branch**
3. **Make changes** and test thoroughly
4. **Submit a pull request** with detailed description

## 📄 License

This macOS wrapper is part of the Smart Terminal project and follows the same MIT license.

## 🙋‍♂️ Support

- **Issues**: [GitHub Issues](https://github.com/daminebenq/smart-terminal/issues)
- **Discussions**: [GitHub Discussions](https://github.com/daminebenq/smart-terminal/discussions)
- **Documentation**: [Smart Terminal Docs](https://github.com/daminebenq/smart-terminal/blob/main/README.md)