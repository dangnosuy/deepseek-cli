#!/usr/bin/env python3
"""
UI Helper Module for DeepSeek CLI
==================================

Cung cấp các hàm trợ giúp để tạo giao diện đẹp và thân thiện với người dùng.

Pattern lấy từ: copilot_chat.py
- Rich library cho formatting
- Spinner cho loading
- Tables cho hiển thị dữ liệu
- Panels cho highlights
- Syntax highlighting cho code
"""

import sys
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.text import Text
    from rich.rule import Rule
    from rich.markdown import Markdown
    import time
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None

# ═══════════════════════════════════════════════════════════════
# HEADER & BANNER
# ═══════════════════════════════════════════════════════════════

def print_header():
    """In header banner khi bắt đầu chương trình"""
    if not HAS_RICH:
        print("\n🤖 DeepSeek Chat CLI + MCP\n")
        return
    
    console.print()
    console.print(Panel(
        "[bold cyan]🤖 DeepSeek Chat CLI + MCP[/]\n"
        "[dim]Agent Mode - Interactive Chat with Tools[/]",
        border_style="cyan",
        padding=(1, 2)
    ))
    console.print()


def print_footer():
    """In footer khi thoát chương trình"""
    if not HAS_RICH:
        print("\n👋 Goodbye!\n")
        return
    
    console.print()
    console.print("[dim]👋 Thank you for using DeepSeek CLI![/]")
    console.print()


# ═══════════════════════════════════════════════════════════════
# STATUS & INFO DISPLAYS
# ═══════════════════════════════════════════════════════════════

def print_success(message: str, prefix: str = "✓"):
    """In thông báo thành công"""
    if not HAS_RICH:
        print(f"[✓] {message}")
        return
    console.print(f"  [bold green]{prefix}[/] {message}")


def print_error(message: str, prefix: str = "✗"):
    """In thông báo lỗi"""
    if not HAS_RICH:
        print(f"[✗] {message}")
        return
    console.print(f"  [bold red]{prefix}[/] {message}")


def print_info(message: str, prefix: str = "ℹ"):
    """In thông báo thông tin"""
    if not HAS_RICH:
        print(f"[ℹ] {message}")
        return
    console.print(f"  [bold blue]{prefix}[/] {message}")


def print_warning(message: str, prefix: str = "⚠"):
    """In cảnh báo"""
    if not HAS_RICH:
        print(f"[⚠] {message}")
        return
    console.print(f"  [bold yellow]{prefix}[/] {message}")


def print_dim(message: str):
    """In tin nhắn mầm"""
    if not HAS_RICH:
        print(f"   {message}")
        return
    console.print(f"  [dim]{message}[/]")


# ═══════════════════════════════════════════════════════════════
# LOADING SPINNER
# ═══════════════════════════════════════════════════════════════

def print_loading(message: str = "Loading..."):
    """In spinner loading"""
    if not HAS_RICH:
        print(f"⏳ {message}")
        return None
    
    spinner_obj = Spinner("dots", text=Text(message, style="cyan"))
    live = Live(spinner_obj, console=console, refresh_per_second=12.5)
    live.start()
    return live


def stop_loading(live_obj):
    """Dừng spinner"""
    if live_obj:
        live_obj.stop()


# ═══════════════════════════════════════════════════════════════
# TABLES & DATA DISPLAY
# ═══════════════════════════════════════════════════════════════

def print_models_table(models: list):
    """In bảng danh sách models"""
    if not HAS_RICH:
        for i, m in enumerate(models):
            print(f"{i+1}. {m.get('id', 'Unknown')}")
        return
    
    table = Table(show_header=True, header_style="bold cyan", border_style="cyan", padding=(0, 1))
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Model ID", style="bold white")
    table.add_column("Vendor", style="dim", width=15)
    table.add_column("Status", style="green", width=10)
    
    for idx, model in enumerate(models, 1):
        model_id = model.get('id', 'Unknown')
        vendor = model.get('vendor', 'Unknown')
        status = "✓ Ready"
        
        table.add_row(str(idx), model_id, vendor, status)
    
    console.print(Panel(table, title="[bold cyan] AVAILABLE MODELS [/]", border_style="cyan"))
    console.print("  [dim]Use /select <number> to choose model[/]")


def print_mcp_status(mcp_servers: dict):
    """In trạng thái MCP servers"""
    if not HAS_RICH:
        for name, status in mcp_servers.items():
            print(f"  {name}: {'Active' if status else 'Inactive'}")
        return
    
    table = Table(show_header=True, header_style="bold cyan", border_style="cyan", padding=(0, 1))
    table.add_column("Server", style="bold white")
    table.add_column("Status", style="green")
    
    for name, status in mcp_servers.items():
        status_str = "[bold green]✓ Active[/]" if status else "[dim]✗ Inactive[/]"
        table.add_row(name, status_str)
    
    console.print(Panel(table, title="[bold cyan] MCP SERVERS [/]", border_style="cyan"))


def print_commands_help():
    """In danh sách lệnh"""
    if not HAS_RICH:
        print("""
Commands:
  /help          - Show this help
  /mcp auto      - Initialize all MCP servers
  /mcp list      - List MCP servers status
  /search on|off - Toggle web search
  /think on|off  - Toggle R1 thinking
  /model [name]  - Switch model
  /clear         - Clear history
  /exit          - Exit
        """)
        return
    
    commands = [
        ("/help", "Show all commands"),
        ("/init", "Initialize & analyze workspace (generates strategy)"),
        ("/remember <text>", "Remember something for future context"),
        ("/memory list", "Show all memories"),
        ("/memory stats", "Show memory statistics"),
        ("/memory clear", "Clear all project memories"),
        ("/mcp auto", "Initialize all MCP servers (Shell, Web, Fetch, Playwright, Filesystem)"),
        ("/mcp list", "List active MCP servers and their status"),
        ("/search on|off", "Toggle web search mode"),
        ("/think on|off", "Toggle R1 thinking mode (deepseek-reasoner)"),
        ("/model [name]", "Switch to different model"),
        ("/select [num]", "Select model from the /models list"),
        ("/models", "Show available models"),
        ("/clear", "Clear conversation history"),
        ("/exit", "Exit the CLI"),
    ]
    
    table = Table(show_header=True, header_style="bold cyan", border_style="cyan", padding=(0, 1))
    table.add_column("Command", style="bold white", min_width=20)
    table.add_column("Description", style="dim")
    
    for cmd, desc in commands:
        table.add_row(f"[green]{cmd}[/]", desc)
    
    console.print(Panel(table, title="[bold cyan] COMMANDS [/]", border_style="cyan"))


# ═══════════════════════════════════════════════════════════════
# CODE & SYNTAX
# ═══════════════════════════════════════════════════════════════

def print_code_block(code: str, language: str = "python", title: str = None):
    """In code block với syntax highlighting"""
    if not HAS_RICH:
        print(f"\n```{language}\n{code}\n```\n")
        return
    
    try:
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        if title:
            console.print(Panel(syntax, title=f"[bold]{title}[/]", border_style="cyan"))
        else:
            console.print(Panel(syntax, border_style="cyan"))
    except:
        console.print(f"```{language}\n{code}\n```")


# ═══════════════════════════════════════════════════════════════
# RESPONSE DISPLAY
# ═══════════════════════════════════════════════════════════════

def print_response(response: str, title: str = "Response"):
    """In response từ LLM"""
    if not HAS_RICH:
        print(f"\n[{title}]\n{response}\n")
        return
    
    # Nếu response có markdown, sử dụng Markdown rendering
    try:
        md = Markdown(response)
        console.print(Panel(md, title=f"[bold cyan]{title}[/]", border_style="cyan"))
    except:
        console.print(Panel(response, title=f"[bold cyan]{title}[/]", border_style="cyan"))


def print_tool_result(tool_name: str, result: str):
    """In kết quả từ MCP tool"""
    if not HAS_RICH:
        print(f"\n[Tool: {tool_name}]\n{result}\n")
        return
    
    console.print()
    console.print(f"  [dim]→ Tool: [bold green]{tool_name}[/][/]")
    
    # Nếu result quá dài, cắt ngắn
    if len(result) > 500:
        console.print(f"  [dim]{result[:500]}... (truncated)[/]")
    else:
        console.print(f"  [dim]{result}[/]")


# ═══════════════════════════════════════════════════════════════
# PROMPT DISPLAY
# ═══════════════════════════════════════════════════════════════

def print_prompt():
    """In prompt cho người dùng"""
    if not HAS_RICH:
        sys.stdout.write("> ")
        sys.stdout.flush()
        return
    
    console.print("[bold green]>[/] ", end="")


def print_rule(title: str = ""):
    """In horizontal rule"""
    if not HAS_RICH:
        print("─" * 50)
        return
    
    console.print(Rule(title, style="cyan"))


# ═══════════════════════════════════════════════════════════════
# ERROR HANDLING
# ═══════════════════════════════════════════════════════════════

def print_error_panel(error: str, details: str = None):
    """In error panel với chi tiết"""
    if not HAS_RICH:
        print(f"\n[ERROR] {error}")
        if details:
            print(f"{details}\n")
        return
    
    content = error
    if details:
        content += f"\n\n[dim]{details}[/]"
    
    console.print(Panel(
        content,
        title="[bold red] ERROR [/]",
        border_style="red",
        padding=(1, 2)
    ))


# ═══════════════════════════════════════════════════════════════
# INTERACTIVE DISPLAYS
# ═══════════════════════════════════════════════════════════════

def print_menu(options: list, title: str = "Menu") -> int:
    """
    In menu interaktif dan return lựa chọn của người dùng
    
    Options format: [("Option 1", "description"), ("Option 2", "description"), ...]
    """
    if not HAS_RICH:
        for i, opt in enumerate(options, 1):
            print(f"{i}. {opt[0]}")
        choice = input("Select: ")
        return int(choice) - 1
    
    table = Table(show_header=False, border_style="cyan", padding=(0, 1))
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Option", style="white")
    table.add_column("", style="dim")
    
    for idx, (name, desc) in enumerate(options, 1):
        table.add_row(str(idx), name, desc if desc else "")
    
    console.print(Panel(table, title=f"[bold cyan] {title} [/]", border_style="cyan"))
    
    while True:
        try:
            choice = console.input("[cyan]Select option (number)[/]: ")
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
            print_warning(f"Invalid choice. Please select 1-{len(options)}")
        except ValueError:
            print_warning("Please enter a number")


# ═══════════════════════════════════════════════════════════════
# SUMMARY & STATS
# ═══════════════════════════════════════════════════════════════

def print_stats(stats: dict):
    """In thống kê"""
    if not HAS_RICH:
        for key, value in stats.items():
            print(f"{key}: {value}")
        return
    
    table = Table(show_header=False, border_style="cyan", padding=(0, 2))
    
    for key, value in stats.items():
        table.add_row(f"[bold cyan]{key}[/]", str(value))
    
    console.print(Panel(table, title="[bold cyan] STATS [/]", border_style="cyan"))


# ═══════════════════════════════════════════════════════════════
# TESTING
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print_header()
    
    print_success("This is a success message")
    print_error("This is an error message")
    print_info("This is an info message")
    print_warning("This is a warning message")
    print_dim("This is a dim message")
    
    print_rule("DEMO")
    
    # Demo models table
    models = [
        {"id": "deepseek-chat", "vendor": "DeepSeek"},
        {"id": "deepseek-reasoner", "vendor": "DeepSeek"},
        {"id": "deepseek-chat-search", "vendor": "DeepSeek"},
    ]
    print_models_table(models)
    
    # Demo MCP status
    mcp_servers = {
        "Shell": True,
        "Web Search": True,
        "Fetch": False,
        "Playwright": False,
    }
    print_mcp_status(mcp_servers)
    
    # Demo code
    print_code_block('print("Hello World")', "python", "Example Code")
    
    # Demo response
    print_response("This is a sample response from the LLM model.")
    
    # Demo error
    print_error_panel("Connection failed", "Unable to connect to the proxy server on localhost:8787")
    
    print_footer()
