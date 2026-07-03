# Smart Terminal Web UI

A modern web interface for managing Smart Terminal conversations with enhanced AI response formatting, background task execution, and comprehensive shell command support.

## 🚀 Quick Start

### Prerequisites
```bash
# Install the required dependencies
pip3 install -r requirements.txt
```

### Starting the Web UI

#### Option 1: Using the launcher script (recommended)
```bash
./start_web_ui.sh
```

#### Option 2: Direct Python execution
```bash
python3 web_app.py
```

#### Option 3: Using Flask development server
```bash
flask run --host=0.0.0.0 --port=5001
```

The web UI will be available at: **http://localhost:5001**

## 🎯 Features

### Dashboard
- 📋 **View all conversations** with previews and metadata
- 🔍 **Search conversations** by content, title, or messages
- 📊 **Session statistics** (message count, token usage, timestamps)
- 🗂️ **Bulk operations** (rename, delete, export)

### Chat Interface
- 💬 **Real-time messaging** with the AI assistant
- 🎨 **Syntax highlighting** with Prism.js for code blocks
- 📝 **Markdown support** with full formatting (headers, lists, tables, etc.)
- 🔄 **Streaming responses** with typing indicators
- 🔧 **Command execution** directly from code blocks
- ⏰ **Background tasks** for long-running commands
- 📋 **Code copy functionality** with one-click copying
- 📱 **Responsive design** that works on mobile devices
- ⌨️ **Keyboard shortcuts** (Ctrl+Enter to send, Ctrl+/ for command template)
- 🔄 **Message history** with timestamps and token counting

### Command Execution & Background Tasks
- 🖥️ **Bash command support**: Execute shell commands from ` ```bash` blocks
- ⚡ **Direct execution**: Click run button to execute commands immediately
- 🔄 **Background execution**: Use ` ```bash --bg` for async task execution
- 📊 **Task monitoring**: Real-time status updates for background tasks
- 📝 **Output display**: View command output in real-time
- ⏱️ **Timeout handling**: Automatic timeouts for long-running commands
- 🔒 **Safe execution**: Command parsing with shlex to prevent injection

### Session Management
- ➕ **Create new conversations** with custom system prompts
- ✏️ **Rename sessions** with meaningful names
- 🗑️ **Delete conversations** (with confirmation)
- 📄 **Export to markdown** for documentation or archiving
- 🔍 **Advanced search** across all conversation content

## 🛠️ API Endpoints

The web UI provides a RESTful API that can be used for programmatic access:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sessions` | List all conversations |
| GET | `/api/sessions/<id>` | Get specific conversation details |
| POST | `/api/sessions/new` | Create new conversation |
| DELETE | `/api/sessions/<id>` | Delete a conversation |
| POST | `/api/sessions/<id>/rename` | Rename a conversation |
| POST | `/api/chat/<id>/message` | Send a message to conversation |
| GET | `/api/sessions/<id>/export` | Export conversation as markdown |
| GET | `/api/sessions/search?q=query` | Search conversations |
| GET | `/api/models` | List available models |
| POST | `/api/execute` | Execute shell commands (sync/async) |
| GET | `/api/task/<task_id>` | Get background task status |
| GET | `/api/tasks` | List all active background tasks |

## 🎨 UI Components

### Message Types
- **User Messages** (blue): Your input and questions
- **Assistant Messages** (purple): AI responses and code suggestions
- **System Messages** (orange): System prompts and configurations
- **Summary Messages** (green): Compacted conversation summaries

### Interactive Elements
- **Dropdown Menus**: Session management options
- **Modal Dialogs**: Create, rename, and confirmations
- **Search Bar**: Real-time conversation search
- **Toast Notifications**: Success/error feedback
- **Loading States**: Progress indicators for async operations

## 🔧 Configuration

### Environment Variables
The web UI respects the same configuration as the CLI:

```bash
# Model configuration
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_API_KEY=your_api_key

# Optional settings
DRY_RUN=false
AUTO_APPROVE_ZERO_RISK=true
AUTO_APPROVE_LOW_RISK_THRESHOLD=20
LOG_LEVEL=INFO
```

### Customization
- **Templates**: Modify HTML templates in `templates/`
- **Styles**: Adjust CSS in `static/style.css`
- **Scripts**: Enhance JavaScript in `static/app.js`

## 📱 Mobile Support

The web UI is fully responsive and works on:
- 📱 **Smartphones** (iOS/Android)
- 📟 **Tablets** (iPad, Android tablets)
- 💻 **Desktop browsers** (Chrome, Firefox, Safari, Edge)

## 🔒 Security Notes

- The web UI runs in **development mode** by default
- No authentication is implemented (add as needed)
- Sessions are stored in `~/.smart-terminal-config/sessions/`
- Use HTTPS in production environments
- Consider adding rate limiting for production use

## 🚀 Production Deployment

### Using Gunicorn
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 web_app:app
```

### Using Docker
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 5001

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5001", "web_app:app"]
```

### Using Docker Compose
```yaml
version: '3.8'
services:
  smart-terminal-web:
    build: .
    ports:
      - "5001:5001"
    volumes:
      - ~/.smart-terminal-config:/app/.smart-terminal-config
    environment:
      - OLLAMA_API_BASE=http://ollama:11434
    depends_on:
      - ollama
  
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  ollama_data:
```

## 🐛 Troubleshooting

### Common Issues

**Port already in use**
```bash
# Kill processes using port 5001
lsof -ti:5001 | xargs kill -9
# Or use a different port
python3 web_app.py --port 5002
```

**Dependencies missing**
```bash
# Reinstall dependencies
pip3 install -r requirements.txt --force-reinstall
```

**Can't access from other devices**
```bash
# Ensure binding to all interfaces
python3 web_app.py --host 0.0.0.0
```

**Session files not found**
```bash
# Check session directory
ls -la ~/.smart-terminal-config/sessions/
# Create if missing
mkdir -p ~/.smart-terminal-config/sessions/
```

### Debug Mode
Enable debug mode for development:
```bash
export FLASK_ENV=development
export FLASK_DEBUG=1
python3 web_app.py
```

## 🤝 Contributing

To contribute to the web UI:

1. **Frontend**: Modify templates in `templates/` and assets in `static/`
2. **Backend**: Extend `web_app.py` with new endpoints
3. **API**: Follow RESTful conventions for new features
4. **Testing**: Add tests in `tests/` directory

## 📝 License

This web UI is part of the Smart Terminal project and follows the same MIT license.