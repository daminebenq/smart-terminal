#!/usr/bin/env python3
"""Web UI for managing Smart Terminal conversations."""

from __future__ import annotations
import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

from smart_terminal.conversation import Conversation, SESSIONS_DIR
from smart_terminal.agent import TerminalAgent
from smart_terminal.settings import SettingsManager

app = Flask(__name__)
CORS(app)

# Global agent instance
_agent: Optional[TerminalAgent] = None

def get_agent() -> TerminalAgent:
    """Get or create the global agent instance."""
    global _agent
    if _agent is None:
        settings = SettingsManager()
        api_base = settings.get('OLLAMA_API_BASE', 'http://localhost:11434')
        model = settings.get('OLLAMA_MODEL', 'llama3.2:3b')
        _agent = TerminalAgent(api_base, model)
    return _agent

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')

@app.route('/api/sessions')
def list_sessions():
    """Get all saved sessions."""
    try:
        sessions = Conversation.list_sessions()
        # Format timestamps and add human-readable dates
        for session in sessions:
            # Convert PosixPath to string for JSON serialization
            if 'path' in session:
                session['path'] = str(session['path'])
            session['updated_at_formatted'] = datetime.fromtimestamp(session['updated_at']).strftime('%Y-%m-%d %H:%M:%S')
            session['created_at_formatted'] = datetime.fromtimestamp(session.get('created_at', session['updated_at'])).strftime('%Y-%m-%d %H:%M:%S')
        return jsonify({'sessions': sessions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>')
def get_session(session_id: str):
    """Get a specific conversation session."""
    try:
        session_path = SESSIONS_DIR / f"{session_id}.json"
        if not session_path.exists():
            return jsonify({'error': 'Session not found'}), 404
        
        conversation = Conversation.load(session_path)
        
        # Format timestamps
        for msg in conversation.messages:
            msg['timestamp_formatted'] = datetime.fromtimestamp(msg['ts']).strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'session_id': conversation.session_id,
            'system_prompt': conversation.system_prompt,
            'messages': conversation.messages,
            'compacted_summary': conversation.compacted_summary,
            'created_at': conversation.created_at,
            'updated_at': conversation.updated_at,
            'created_at_formatted': datetime.fromtimestamp(conversation.created_at).strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at_formatted': datetime.fromtimestamp(conversation.updated_at).strftime('%Y-%m-%d %H:%M:%S'),
            'token_count': conversation.estimate_total_tokens()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """Delete a conversation session."""
    try:
        session_path = SESSIONS_DIR / f"{session_id}.json"
        if not session_path.exists():
            return jsonify({'error': 'Session not found'}), 404
        
        session_path.unlink()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>/rename', methods=['POST'])
def rename_session(session_id: str):
    """Rename a conversation session."""
    try:
        data = request.get_json()
        new_name = data.get('name')
        if not new_name:
            return jsonify({'error': 'Name is required'}), 400
        
        # Sanitize name
        new_id = ''.join(c if c.isalnum() or c in '-._' else '-' for c in new_name).strip('-')
        if not new_id:
            return jsonify({'error': 'Invalid name'}), 400
        
        session_path = SESSIONS_DIR / f"{session_id}.json"
        new_path = SESSIONS_DIR / f"{new_id}.json"
        
        if not session_path.exists():
            return jsonify({'error': 'Session not found'}), 404
        
        if new_path.exists() and new_id != session_id:
            return jsonify({'error': 'Session with this name already exists'}), 409
        
        conversation = Conversation.load(session_path)
        conversation.session_id = new_id
        conversation.save(new_path)
        
        # Remove old file if renamed
        if new_id != session_id:
            session_path.unlink()
        
        return jsonify({'success': True, 'new_id': new_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/new', methods=['POST'])
def create_session():
    """Create a new conversation session."""
    try:
        data = request.get_json() or {}
        system_prompt = data.get('system_prompt', '')
        
        conversation = Conversation(system_prompt=system_prompt)
        conversation.save()
        
        return jsonify({
            'success': True,
            'session_id': conversation.session_id,
            'session_url': url_for('chat_page', session_id=conversation.session_id)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/chat/<session_id>')
def chat_page(session_id: str):
    """Chat interface for a specific session."""
    return render_template('chat.html', session_id=session_id)

@app.route('/api/chat/<session_id>/message', methods=['POST'])
def send_message(session_id: str):
    """Send a message to the conversation."""
    try:
        data = request.get_json()
        message = data.get('message')
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        session_path = SESSIONS_DIR / f"{session_id}.json"
        if not session_path.exists():
            conversation = Conversation()
            conversation.session_id = session_id
        else:
            conversation = Conversation.load(session_path)
        
        conversation.add_user(message)
        
        # Get agent response
        agent = get_agent()
        response = agent.chat_with_history(conversation.to_api_messages(), stream=False)
        
        conversation.add_assistant(response)
        conversation.save()
        
        return jsonify({
            'success': True,
            'response': response,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/<session_id>/export')
def export_session(session_id: str):
    """Export a session to markdown."""
    try:
        session_path = SESSIONS_DIR / f"{session_id}.json"
        if not session_path.exists():
            return jsonify({'error': 'Session not found'}), 404
        
        conversation = Conversation.load(session_path)
        
        # Generate markdown
        lines = [
            f"# {conversation.session_id}",
            f"*Created: {datetime.fromtimestamp(conversation.created_at).strftime('%Y-%m-%d %H:%M:%S')}*",
            f"*Updated: {datetime.fromtimestamp(conversation.updated_at).strftime('%Y-%m-%d %H:%M:%S')}*",
            f"*Messages: {len(conversation.messages)}*",
            "",
            "## System Prompt",
            "",
            conversation.system_prompt,
            ""
        ]
        
        if conversation.compacted_summary:
            lines.extend([
                "## Compacted Summary",
                "",
                conversation.compacted_summary,
                ""
            ])
        
        lines.append("## Conversation")
        lines.append("")
        
        for msg in conversation.messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            timestamp = datetime.fromtimestamp(msg.get('ts', 0)).strftime('%Y-%m-%d %H:%M:%S')
            
            lines.append(f"### {role.title()} - {timestamp}")
            lines.append("")
            lines.append(content)
            lines.append("")
        
        return '\n'.join(lines), 200, {
            'Content-Type': 'text/markdown',
            'Content-Disposition': f'inline; filename="{session_id}.md"'
        }
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sessions/search')
def search_sessions():
    """Search sessions by content."""
    try:
        query = request.args.get('q', '').strip().lower()
        if not query:
            return jsonify({'error': 'Search query is required'}), 400
        
        sessions = Conversation.list_sessions()
        results = []
        
        for session in sessions:
            try:
                conversation = Conversation.load(session['path'])
                
                # Check if query matches preview, messages, or session_id
                matches = (
                    query in session['preview'].lower() or
                    query in conversation.session_id.lower() or
                    any(query in msg.get('content', '').lower() for msg in conversation.messages)
                )
                
                if matches:
                    # Convert PosixPath to string for JSON serialization
                    if 'path' in session:
                        session['path'] = str(session['path'])
                    session['updated_at_formatted'] = datetime.fromtimestamp(session['updated_at']).strftime('%Y-%m-%d %H:%M:%S')
                    results.append(session)
            except Exception:
                continue
        
        return jsonify({'sessions': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/models')
def list_models():
    """List available models."""
    try:
        agent = get_agent()
        import requests
        
        url = f'{agent.api_base}/api/tags'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        models = data.get('models', [])
        
        return jsonify({
            'models': models,
            'current': agent.model,
            'api_base': agent.api_base
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Global task storage (in production, use Redis or database)
background_tasks = {
    # 'task-id': {
    #     'id': 'task-id',
    #     'command': 'ls -la',
    #     'status': 'running|completed|failed',
    #     'output': '...',
    #     'start_time': timestamp
    # }
}

@app.route('/api/execute', methods=['POST'])
def execute_command():
    """Execute shell commands with optional background execution."""
    try:
        data = request.get_json()
        command = data.get('command')
        background = data.get('background', False)
        task_id = data.get('task_id')
        
        if not command:
            return jsonify({'error': 'Command is required'}), 400
        
        import subprocess
        import threading
        import shlex
        from datetime import datetime
        
        def execute_async(task_id, command):
            try:
                # Parse command safely
                args = shlex.split(command)
                
                # Execute command
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    cwd=os.getcwd()
                )
                
                output = result.stdout
                if result.stderr:
                    output += f'\nSTDERR: {result.stderr}'
                
                # Update task status
                background_tasks[task_id].update({
                    'status': 'completed' if result.returncode == 0 else 'failed',
                    'output': output,
                    'end_time': datetime.now().timestamp()
                })
            except subprocess.TimeoutExpired:
                background_tasks[task_id].update({
                    'status': 'failed',
                    'output': 'Command timed out after 5 minutes',
                    'end_time': datetime.now().timestamp()
                })
            except Exception as e:
                background_tasks[task_id].update({
                    'status': 'failed',
                    'output': f'Error: {str(e)}',
                    'end_time': datetime.now().timestamp()
                })
        
        if background:
            # Background execution
            if not task_id:
                return jsonify({'error': 'Task ID is required for background execution'}), 400
            
            background_tasks[task_id] = {
                'id': task_id,
                'command': command,
                'status': 'running',
                'output': '',
                'start_time': datetime.now().timestamp()
            }
            
            # Start background thread
            thread = threading.Thread(target=execute_async, args=(task_id, command))
            thread.daemon = True
            thread.start()
            
            return jsonify({
                'success': True,
                'task_id': task_id,
                'message': 'Background task started'
            })
        else:
            # Synchronous execution
            try:
                args = shlex.split(command)
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=60,  # 1 minute timeout for sync commands
                    cwd=os.getcwd()
                )
                
                output = result.stdout
                if result.stderr:
                    output += f'\nSTDERR: {result.stderr}'
                
                return jsonify({
                    'success': True,
                    'output': output,
                    'return_code': result.returncode
                })
                
            except subprocess.TimeoutExpired:
                return jsonify({'error': 'Command timed out after 1 minute'}), 408
            except Exception as e:
                return jsonify({'error': f'Command execution failed: {str(e)}'}), 500
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/task/<task_id>')
def get_task_status(task_id):
    """Get status of a background task."""
    try:
        if task_id not in background_tasks:
            return jsonify({'error': 'Task not found'}), 404
        
        task = background_tasks[task_id]
        
        # Clean up old completed tasks (older than 1 hour)
        import time
        current_time = time.time()
        tasks_to_remove = []
        
        for tid, t in background_tasks.items():
            if (t['status'] in ['completed', 'failed'] and 
                'end_time' in t and 
                current_time - t['end_time'] > 3600):
                tasks_to_remove.append(tid)
        
        for tid in tasks_to_remove:
            del background_tasks[tid]
        
        return jsonify(task)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks')
def list_tasks():
    """List all active background tasks."""
    try:
        active_tasks = [
            task for task in background_tasks.values()
            if task['status'] == 'running'
        ]
        
        return jsonify({
            'tasks': active_tasks,
            'total': len(active_tasks)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Ensure templates directory exists
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Ensure static directory exists
    static_dir = Path(__file__).parent / 'static'
    static_dir.mkdir(exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5001)