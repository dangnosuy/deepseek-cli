# DeepSeek CLI + MCP

CLI tool để chat với DeepSeek AI + 4 MCP servers (Shell, Web Search, Fetch, Playwright).

## 🚀 Chạy Ngay - 3 Bước

**Terminal 1:**
```bash
cd /home/dangnosuy/DeepSeek/deepseek-cli-mcp
export DS_TOKEN=''
export DS_SESSION=''
node ./server-simple.js
```

- Tìm DS_SESSION bằng cách mở F12 > Application > Cookie > Trường ds_session_id bỏ vào DS_SESSION
- Tìm DS_TOKEN bằng cách mở F12 > Application > Local Storage > Trường value trong userToken bỏ vào DS_TOKEN.
- Export xong có thể chạy chương trình.

**Terminal 2:**
```bash
cd /home/dangnosuy/DeepSeek/deepseek-cli-mcp
python3 deepseek_chat.py
```

**Trong CLI:**
```
> /mcp auto
> What is 2+2?
```

## 📋 Lệnh Chính

- `/help` - Xem tất cả
- `/mcp auto` - Khởi tạo MCP
- `/search on` - Bật web search
- `/think on` - Bật R1 thinking
- `/model [name]` - Đổi model
- `/exit` - Thoát

## 📁 Files

| File | Mục đích |
|------|---------|
| `server-simple.js` | Proxy server (OpenAI-compatible) |
| `deepseek_chat.py` | CLI client |
| `mcp_client.py` | MCP manager (4 servers) |
| `test_suite.py` | 10 integration tests |
| `verify.py` | 25 pre-deployment checks |

## 🧪 Tests

```bash
python3 test_suite.py     # Run 10 tests
python3 verify.py         # Run 25 checks
```

## ✨ Features

✅ OpenAI-compatible API (localhost:8787)
✅ 4 MCP servers (Shell, Web Search, Fetch, Playwright)
✅ Agent loop với auto tool detection
✅ Multi-model: deepseek-chat, deepseek-reasoner (R1), deepseek-chat-search
✅ Web search không cần API key
✅ Streaming responses
✅ Rich terminal UI

## 📚 Documentation

- **RUN.txt** - Cách chạy nhanh (5 phút)
- **HOW_TO_RUN.md** - Chi tiết

## ✅ Status

- Proxy: ✅ Running (localhost:8787)
- Tests: ✅ 35/35 passing
- Models: ✅ 4 models
- MCP: ✅ 4 servers
- Agent loop rounds: Each adds 5-15 seconds
- Streaming chunks: Every ~100ms

## License

MIT - Feel free to modify and distribute
