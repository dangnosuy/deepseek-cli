# DeepSeek Project Context

Generated at: deepseek-cli-mcp
Last Updated: 2026-04-15T21:25:45.633322

# 📋 Project Analysis: DeepSeek CLI + MCP

## 1. Project Summary
This is a **CLI chat interface for DeepSeek AI** integrated with multiple MCP (Model Context Protocol) servers. It acts as an AI agent that can execute shell commands, search the web, fetch URLs, and control a browser via Playwright - all through a natural language interface. The project uses a proxy server to bridge between the DeepSeek API and local MCP tools.

## 2. Tech Stack

| Category | Technologies |
|----------|-------------|
| **Backend** | Python 3, Node.js |
| **AI/LLM** | DeepSeek API (deepseek-chat, deepseek-reasoner) |
| **Protocol** | MCP (Model Context Protocol), OpenAI-compatible API |
| **MCP Servers** | Shell, Web Search, Fetch, Playwright |
| **Python Libraries** | asyncio, websockets, httpx, rich (terminal UI) |
| **Node.js** | Express (proxy server) |
| **Testing** | pytest-style test suite |
| **Other** | WebAssembly (sha3_wasm_bg.wasm) |

## 3. Project Structure

```
deepseek-cli-mcp/
├── Core CLI Files
│   ├── deepseek_chat.py      # Main CLI client with rich UI
│   ├── mcp_client.py          # MCP server manager (4 servers)
│   └── ui_helper.py           # Terminal formatting helpers
│
├── Proxy Server
│   └── server-simple.js       # OpenAI-compatible proxy (port 8787)
│
├── Testing
│   ├── test_suite.py          # 10 integration tests
│   └── verify.py              # 25 pre-deployment checks
│
├── Scripts
│   ├── quickstart.sh          # Quick setup script
│   └── start-deepseek-cli.sh  # Launcher script
│
├── Documentation
│   ├── README.md              # Main documentation
│   ├── HOW_TO_RUN.md          # Step-by-step guide
│   ├── RUN.txt                # Quick reference
│   ├── AGENT_UPGRADE_STRATEGY.md  # Agent improvement notes
│   └── FIX_PORT_ERROR.md      # Troubleshooting
│
└── Assets
    └── sha3_wasm_bg.wasm      # WebAssembly module (hashing)
```

## 4. Key Files

| File | Purpose | Priority |
|------|---------|----------|
| `deepseek_chat.py` | **Main entry point** - CLI with streaming, commands, agent loop | 🔴 Critical |
| `server-simple.js` | **Proxy server** - Must run before CLI | 🔴 Critical |
| `mcp_client.py` | **MCP integration** - Manages all 4 tool servers | 🔴 Critical |
| `test_suite.py` | Integration testing - Run after changes | 🟡 Important |
| `verify.py` | Pre-deployment validation | 🟡 Important |
| `README.md` | Complete documentation | 📖 Reference |
| `HOW_TO_RUN.md` | Setup guide | 📖 Reference |

## 5. Development Strategy

### Phase 1: Understanding the Codebase
```bash
# 1. Run verification to understand current state
python3 verify.py

# 2. Run tests to see what works
python3 test_suite.py

# 3. Start the system to experience the workflow
node server-simple.js &  # Terminal 1
python3 deepseek_chat.py  # Terminal 2
```

### Phase 2: Safe Modifications
1. **Start with `mcp_client.py`** - Most self-contained, affects tool behavior
2. **Move to `deepseek_chat.py`** - Main logic, command handlers, agent loop
3. **Update `server-simple.js`** - Only if changing API endpoints or adding routes
4. **Update tests** - Run `test_suite.py` after each change

### Phase 3: Feature Development Pattern
```python
# Pattern for adding new features:
# 1. Add command in deepseek_chat.py
# 2. Implement functionality in appropriate module
# 3. Add test in test_suite.py
# 4. Update documentation in README.md
```

## 6. Potential Improvements

### 🚀 High Priority
- **Error Recovery**: Add retry logic for failed MCP server connections
- **Configuration File**: Move tokens/settings to `.env` or `config.json`
- **Logging System**: Replace print statements with proper logging levels
- **Tool Timeout**: Add configurable timeouts for long-running shell commands

### 🎯 Medium Priority
- **Plugin Architecture**: Make MCP servers dynamically loadable
- **Conversation History**: Save/load chat sessions to disk
- **Multi-turn Agent**: Improve context handling across multiple tool calls
- **Response Caching**: Cache web search results to reduce latency

### ✨ Low Priority / Nice to Have
- **Docker Support**: Containerize the entire stack
- **GUI Alternative**: Build a simple web interface
- **Voice Input**: Add speech-to-text for commands
- **Export Formats**: Save conversations as JSON, Markdown, or PDF

### 🐛 Known Issues (from files)
- Port 8787 conflicts (see `FIX_PORT_ERROR.md`)
- Agent loop adds 5-15 seconds per round
- WebAssembly module required for some operations

## 7. Development Guidelines

### Coding Standards
```python
# Follow existing patterns:
# - Use asyncio for all I/O operations
# - Keep UI logic in ui_helper.py
# - Use Rich for terminal formatting
# - Prefix internal methods with underscore

# Example pattern from codebase:
class MCPClient:
    async def _connect_server(self, name: str, command: list):
        """Internal method for server connection"""
        pass
    
    async def execute_tool(self, tool_name: str, args: dict):
        """Public method for tool execution"""
        pass
```

### Best Practices for This Project

1. **Always test both modes**:
   - Without MCP: `/mcp off` then chat
   - With MCP: `/mcp auto` then test tools

2. **Tool Development**:
   ```python
   # New tools must:
   # 1. Register in mcp_client.py's SERVERS dict
   # 2. Handle async properly
   # 3. Return structured responses
   # 4. Have timeout mechanism
   ```

3. **Command Pattern**:
   ```python
   # Commands follow: /command [args]
   # Implement in deepseek_chat.py's _handle_command()
   # Add help text to /help output
   ```

4. **Error Handling**:
   ```python
   try:
       result = await tool.execute()
   except MCPConnectionError:
       ui.print_error("MCP server not running. Run /mcp auto")
   except TimeoutError:
       ui.print_warning("Tool timeout - try again")
   ```

5. **Testing Discipline**:
   - Run `verify.py` before any commit
   - Run `test_suite.py` after modifying core files
   - Add new tests for new features
   - Keep tests independent (no shared state)

### Configuration Management
```bash
# Current approach (hardcoded):
export DS_TOKEN='your_token_here'
export DS_SESSION='your_session_id'

# Better approach - create config.json:
{
  "deepseek": {
    "token": "${DS_TOKEN}",
    "session": "${DS_SESSION}"
  },
  "mcp": {
    "servers": ["shell", "web_search", "fetch", "playwright"],
    "timeout_seconds": 30
  },
  "ui": {
    "theme": "dark",
    "streaming_chunk_ms": 100
  }
}
```

### Git Workflow for This Project
```bash
# Branch strategy:
main          # Stable releases
├── develop   # Integration branch
├── feature/* # New features
└── hotfix/*  # Emergency fixes

# Commit message format:
type(scope): description

# Types: feat, fix, docs, test, refactor
# Scopes: cli, mcp, proxy, ui, tests

# Example:
feat(mcp): add filesystem server
fix(cli): handle empty tool responses
docs(readme): update setup instructions
```

### Performance Tips
- Cache MCP server connections (they're reused)
- Implement streaming for long operations
- Use connection pooling for web requests
- Add progressive timeout (increase after retries)

### Security Notes
- Tokens are exposed in README (move to environment)
- Shell command execution has risks (add confirmation for dangerous commands)
- Web search without API key may be rate-limited
- Add command whitelist/blacklist for shell MCP

---

**Quick Start for Developers:**
```bash
# Clone and setup
git clone <repo>
cd deepseek-cli-mcp
python3 -m venv venv
source venv/bin/activate
pip install rich httpx websockets

# Set your tokens
export DS_TOKEN='your_token'
export DS_SESSION='your_session'

# Run verification
python3 verify.py

# Start developing!
```