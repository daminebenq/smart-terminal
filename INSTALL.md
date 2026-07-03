# Smart Terminal Installation Guide

## 🚀 Quick Start - Native macOS App (Recommended)

For macOS users, the native app provides the best experience with auto-startup and system integration:

```bash
# Clone the repository
git clone https://github.com/daminebenq/smart-terminal.git
cd smart-terminal/SmartTerminalApp

# Run the installation script
./install.sh

# The app will auto-start and be available from Applications folder
# Access at: http://smartterminal:5001
```

### What the Installation Does

1. ✅ **Builds native SwiftUI app** with proper dependencies
2. ✅ **Installs to `/Applications`** as a proper macOS app
3. ✅ **Sets up local domain** `smartterminal` in `/etc/hosts`
4. ✅ **Installs Python dependencies** for the web server
5. ✅ **Configures permissions** and app sandbox
6. ✅ **Adds menu bar integration** with quick controls
7. ✅ **Enables auto-startup** (default behavior)

## 🌐 Cross-Platform Web UI

For non-macOS users or if you prefer browser-based access:

```bash
# Clone the repository
git clone https://github.com/daminebenq/smart-terminal.git
cd smart-terminal

# Install dependencies
pip3 install -r requirements.txt

# Start the web UI
./start_web_ui.sh
# Or: python3 web_app.py

# Open browser to: http://localhost:5001
```

## 💻 Command Line Interface

For traditional CLI usage:

```bash
# Clone the repository
git clone https://github.com/daminebenq/smart-terminal.git
cd smart-terminal

# Install dependencies
pip3 install -r requirements.txt

# Install CLI tool
pip3 install -e .

# Run configuration wizard
smart-term configure

# Start using the CLI
smart-term 'list all running processes'
```

### Installation Options

| Method | Platform | Best For | Features |
|--------|----------|----------|----------|
| **Native macOS App** | macOS 13+ | Desktop integration | Auto-start, menu bar, local domain |
| **Web UI** | Linux, macOS, Windows | Browser access | Full-featured interface, mobile-friendly |
| **CLI** | All platforms | Terminal users | Lightweight, keyboard-driven |

## 📋 Prerequisites

### For All Installations
- **Python 3.8+** required
- **Git** for cloning the repository

### For Native macOS App
- **macOS 13.0 (Ventura) or later**
- **Xcode Command Line Tools** (auto-installed if missing)

### For Web UI
- **Modern web browser** (Chrome, Firefox, Safari, Edge)

### For CLI
- **-terminal** or **Terminal.app**

## 🔧 Manual Installation Steps

If the automated scripts don't work, here are the manual steps:

### Native macOS App

```bash
# 1. Navigate to the app directory
cd SmartTerminalApp

# 2. Resolve Swift dependencies
swift package resolve

# 3. Build the app
swift build -c release

# 4. Create app bundle
mkdir -p build/SmartTerminal.app/Contents/{MacOS,Resources}
cp .build/release/SmartTerminalApp build/SmartTerminal.app/Contents/MacOS/
cp Info.plist build/SmartTerminal.app/Contents/
cp -r Resources/* build/SmartTerminal.app/Contents/Resources/

# 5. Install to Applications
sudo cp -R build/SmartTerminal.app /Applications/

# 6. Setup local domain
echo "127.0.0.1 smartterminal" | sudo tee -a /etc/hosts

# 7. Install Python dependencies
pip3 install --user -r requirements.txt

# 8. Launch the app
open /Applications/SmartTerminal.app
```

### Web UI

```bash
# 1. Install dependencies
pip3 install flask requests beautifulsoup4 trafilatura

# 2. Start the server
python3 web_app.py

# 3. Open browser to http://localhost:5001
```

### CLI

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Install the CLI in development mode
pip3 install -e .

# 3. Configure the tool
smart-term configure

# 4. Test the installation
smart-term 'echo "Hello World"'
```

## ⚙️ Configuration

After installation, you can configure Smart Terminal:

### First-Time Configuration

```bash
# For CLI
smart-term configure

# For Web UI - visit http://localhost:5001 and configure via web interface
# For Native App - use the settings in the web interface
```

### Environment Variables

Create a `.env` file in the project root:

```bash
# Model configuration
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_API_KEY=

# Optional settings
DRY_RUN=false
AUTO_APPROVE_ZERO_RISK=true
AUTO_APPROVE_LOW_RISK_THRESHOLD=20
LOG_LEVEL=INFO
```

### Supported Providers

| Provider | Setup |
|----------|-------|
| **Ollama** | `ollama pull llama3.2:3b` |
| **OpenAI** | Set `OPENAI_API_KEY` |
| **Anthropic** | Set `ANTHROPIC_API_KEY` |
| **Groq** | Set `GROQ_API_KEY` |
| **Custom** | Provide API URL and key |

## 🧪 Testing Your Installation

### Native macOS App

```bash
# Check if app is running
ps aux | grep SmartTerminal

# Test web server
curl http://smartterminal:5001/api/models

# Check logs
Console.app → filter for "SmartTerminal"
```

### Web UI

```bash
# Test server is running
curl http://localhost:5001/api/models

# Check web interface
open http://localhost:5001
```

### CLI

```bash
# Test basic functionality
smart-term 'echo "Installation test successful"'

# Test configuration
smart-term --help

# Test web search
smart-term web_search "what is Smart Terminal"
```

## 🔍 Troubleshooting

### Common Issues

#### macOS App Won't Start
```bash
# Check macOS version - must be 13.0+
sw_vers -productVersion

# Check permissions
ls -la /Applications/SmartTerminal.app

# Check logs
Console.app
```

#### Local Domain Not Working
```bash
# Check hosts file
cat /etc/hosts | grep smartterminal

# Flush DNS cache
sudo dscacheutil -flushcache

# Test manually
ping smartterminal
```

#### Port Already in Use
```bash
# Find process using port 5001
lsof -i :5001

# Kill the process
kill -9 <PID>

# Or use different port
export PORT=5002
python3 web_app.py
```

#### Python Dependencies Missing
```bash
# Reinstall dependencies
pip3 install -r requirements.txt --force-reinstall

# Check Python version
python3 --version
```

#### Permission Denied
```bash
# Fix file permissions
sudo chown -R $USER:staff /Applications/SmartTerminal.app

# Fix hosts file permission (may be required)
sudo vim /etc/hosts
```

### Getting Help

1. **Check the logs** in Console.app (macOS) or terminal output
2. **Review the configuration** - ensure API keys and URLs are correct
3. **Test connectivity** - verify you can reach your AI provider
4. **Check dependencies** - ensure all required packages are installed

## 🗑️ Uninstallation

### Native macOS App

```bash
# Remove app
sudo rm -rf /Applications/SmartTerminal.app

# Remove hosts entry
sudo sed -i '' '/smartterminal/d' /etc/hosts

# Remove launch agent (if created)
rm -f ~/Library/LaunchAgents/com.smartterminal.app.plist

# Flush DNS
sudo dscacheutil -flushcache
```

### Web UI/CLI

```bash
# Uninstall CLI package
pip3 uninstall smart-terminal

# Remove cloned repository
rm -rf smart-terminal

# No system-wide changes required for web UI
```

## 🆙 Updates

### Native macOS App

```bash
# Pull latest changes
cd smart-terminal
git pull origin main

# Rebuild and reinstall
cd SmartTerminalApp
./install.sh
```

### Web UI / CLI

```bash
# Pull latest changes
cd smart-terminal
git pull origin main

# Update dependencies
pip3 install -r requirements.txt --upgrade

# Restart the service if running
```

---

**Installation Complete! 🎉**

Enjoy using Smart Terminal:

- **Native App**: Look for the terminal icon in your Applications folder or menu bar
- **Web UI**: Open http://smartterminal:5001 (macOS) or http://localhost:5001 (others)
- **CLI**: Use `smart-term` command in your terminal

For support, visit: https://github.com/daminebenq/smart-terminal/issues