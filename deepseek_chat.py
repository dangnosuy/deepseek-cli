#!/usr/bin/env python3
import sys
import os
import json
import requests
import re
from datetime import datetime
from typing import Optional, Dict, Tuple
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text

# Import UI helper
try:
    from ui_helper import (
        print_header, print_footer, print_success, print_error, 
        print_info, print_warning, print_dim, print_loading, stop_loading,
        print_models_table, print_mcp_status, print_commands_help,
        print_response, print_tool_result, print_rule, print_error_panel,
        print_prompt, print_code_block
    )
except ImportError:
    print("[!] Cannot import ui_helper. Make sure ui_helper.py is in the same directory.")
    sys.exit(1)

# Import workspace analyzer
try:
    from workspace_analyzer import (
        generate_analysis_prompt, save_context_file, load_context_file
    )
except ImportError:
    print_error("Cannot import workspace_analyzer. Make sure workspace_analyzer.py is in the same directory.")
    sys.exit(1)

# Import memory manager
try:
    from memory_manager import MemoryManager
except ImportError:
    print_error("Cannot import memory_manager. Make sure memory_manager.py is in the same directory.")
    sys.exit(1)

# Path fix for mcp_client
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
try:
    from mcp_client import MCPManager
except ImportError:
    print_error("Cannot import mcp_client. Make sure it's copied to the correct path.")
    sys.exit(1)

console = Console()

PROXY_URL = "http://localhost:8787/v1/chat/completions"
MODEL = "deepseek-reasoner"

# Deep reasoning controls (aggressive mode)
FORCE_DEEP_THINKING = True
FORCE_REASONER_FOR_INIT = True
FORCE_REASONER_FOR_CHAT = True
CHAT_REFINE_MAX_ROUNDS = 1
CHAT_REFINE_MIN_LEN = 1200

SYSTEM_PROMPT = """You are DeepSeek CLI, a proactive, highly capable autonomous coding and security engineer.
Your mission is to produce complete, high-quality outcomes with strong reasoning, not just obedient one-step replies.

═══ CORE OPERATING MODE ═══
1. Be proactively useful: infer missing low-risk details from repo context and proceed.
2. Be user-aligned: autonomy does NOT mean surprise side effects; avoid destructive actions unless explicitly requested.
3. Be depth-first: identify root cause, not just surface symptoms.

═══ TONE AND OUTPUT STYLE ═══
1. Concise, direct, and action-oriented.
2. Avoid empty preamble/postamble; focus on decisions, evidence, and outcomes.
3. Prefer structured outputs for complex tasks (checklists, brief sections, compact tables).

═══ CREATIVE INTELLIGENCE PROTOCOL (MANDATORY) ═══
For non-trivial tasks, perform internal multi-pass reasoning:
1) Scope pass: objective, constraints, missing evidence, and success criteria.
2) Divergence pass: generate at least 3 approaches (including 1 unconventional but realistic option).
3) Convergence pass: choose best approach using trade-offs (speed, reliability, maintainability, security).
4) Edge pass: cover failure modes (empty input, scale/perf, permissions, timeouts, partial failures).
5) Verification pass: prove correctness via tests/checks before claiming done.

When user asks for analysis/design, prioritize insight quality:
- explain why one approach wins,
- state assumptions briefly,
- provide practical next actions.

═══ CRITICAL: CONTEXT-FIRST APPROACH ═══
Before acting:
1. Check and read DEEPSEEK.md (if present) to absorb project constraints/conventions.
2. Inspect local code patterns and dependencies before introducing new patterns/libs.
3. Ground claims in evidence from available files/tool results; if uncertain, label uncertainty and gather context.

═══ TOOL USAGE ═══
If you need to use a tool, output a raw JSON block wrapped in <tool_call> tags:
<tool_call>
{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}
</tool_call>

Available tools:
{TOOLS}

Rules:
1. ONLY output ONE <tool_call> block at a time.
2. Wait for <tool_result> before the next step.
3. Use tools proactively to collect enough context before implementation.
4. No markdown code fences around <tool_call>.
5. If no tools are needed, answer directly.

═══ QUALITY BAR ═══
Before final answer on technical tasks, aim to satisfy:
1) Correctness: no obvious logic/type/syntax issues.
2) Verification: run at least one relevant check/test when possible.
3) Practicality: include actionable, repo-aligned output.
4) Security: avoid unsafe patterns and secret exposure.
"""


def get_effective_model(for_init: bool = False) -> str:
    """Choose effective model with deep-thinking overrides."""
    if for_init and FORCE_REASONER_FOR_INIT:
        return "deepseek-reasoner"
    if FORCE_REASONER_FOR_CHAT:
        return "deepseek-reasoner"
    return MODEL


def should_refine_chat_response(user_input: str, response_text: str) -> bool:
    """Heuristic: refine when request implies depth but response is too short/generic."""
    q = (user_input or "").lower()
    r = response_text or ""
    r_lower = r.lower()

    depth_keywords = [
        "phân tích", "chi tiết", "đi sâu", "so sánh", "đánh giá", "chiến lược", "kế hoạch",
        "sáng tạo", "ý tưởng", "creative", "innovation", "deep", "analysis", "detailed", "evaluate", "architecture", "tradeoff", "roadmap",
    ]
    asks_depth = any(k in q for k in depth_keywords) or len(q) >= 60
    too_short = len(r) < CHAT_REFINE_MIN_LEN
    has_structure = any(h in r_lower for h in ["##", "1.", "2.", "- "])
    has_analytical_markers = any(
        m in r_lower
        for m in ["trade-off", "tradeoff", "rủi ro", "risk", "alternative", "ưu tiên", "edge case", "failure mode"]
    )

    # Very rough repetitive-response signal (same non-empty line repeated many times)
    lines = [ln.strip().lower() for ln in r.splitlines() if ln.strip()]
    repeated_ratio = 0.0
    if lines:
        repeated_ratio = 1.0 - (len(set(lines)) / len(lines))
    too_repetitive = repeated_ratio > 0.35

    return asks_depth and (too_short or not has_structure or not has_analytical_markers or too_repetitive)


def refine_chat_response(user_input: str, draft_response: str, deepseek_context: str = "") -> Optional[str]:
    """Run one extra deep pass to expand a shallow response."""
    refine_system_prompt = """You are in Deep Reasoning Mode.
Rewrite and improve the draft answer to be deeper, broader, and more actionable.

Rules:
1) Keep the same factual base; do not invent unsupported facts.
2) Increase analytical depth (tradeoffs, risks, priorities, alternatives).
3) Use clear structure (headings/bullets/tables when helpful).
4) Remove vague language and generic filler.
5) Output final improved answer only.
"""

    user_msg = (
        f"User request:\n{user_input}\n\n"
        f"Current draft answer:\n{draft_response}\n"
    )
    if deepseek_context:
        user_msg += f"\n\nProject context:\n{deepseek_context}"

    payload = {
        "model": get_effective_model(for_init=False),
        "messages": [
            {"role": "system", "content": refine_system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "agent_mode": False,
    }

    try:
        res = requests.post(PROXY_URL, json=payload, timeout=300)
        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"].get("content", "")
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Chat Refine API Error:[/] {e}")
        return None


def load_deepseek_context(project_dir: str) -> str:
    """Load DEEPSEEK.md from a specific directory."""
    deepseek_file = os.path.join(project_dir, "DEEPSEEK.md")
    if os.path.isfile(deepseek_file):
        try:
            with open(deepseek_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ""
    return ""


def score_analysis_quality(analysis_text: str) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    """Score /init analysis quality on a 0-100 scale with simple deterministic heuristics."""
    text = analysis_text or ""
    lower = text.lower()

    section_groups = [
        ["project summary", "executive summary"],
        ["tech stack", "technology stack", "tooling & infrastructure"],
        ["project structure", "workspace structure"],
        ["key files", "high-impact", "security assessment artifacts"],
        ["workflow assessment", "development strategy", "workflow"],
        ["improvement plan", "potential improvements", "recommendations"],
        ["development guidelines", "guidelines", "standards"],
        ["confidence", "confidence & gaps", "limitations"],
    ]
    section_hits = 0
    for group in section_groups:
        if any(k in lower for k in group):
            section_hits += 1
    section_score = min(40, section_hits * 5)

    path_matches = re.findall(r"(?:/|\b)[\w.-]+(?:/[\w.-]+){1,}", text)
    path_score = min(20, len(path_matches))

    table_markers = text.count("|")
    table_score = 10 if table_markers >= 12 else 5 if table_markers >= 4 else 0

    length_score = 10 if len(text) >= 4000 else 7 if len(text) >= 2500 else 4 if len(text) >= 1500 else 0

    action_words = [
        "implement", "standardize", "create", "automate", "add", "migrate", "prioritize",
        "thêm", "tạo", "chuẩn hóa", "tự động", "ưu tiên", "triển khai",
    ]
    action_hits = sum(lower.count(w) for w in action_words)
    action_score = min(20, action_hits)

    hedging_words = ["maybe", "likely", "possibly", "seems", "might", "có thể", "dường như", "có vẻ"]
    hedging_hits = sum(lower.count(w) for w in hedging_words)
    hedge_penalty = min(15, hedging_hits * 2)

    unknown_hits = lower.count("unknown")
    unknown_penalty = min(10, max(0, unknown_hits - 2) * 2)

    base_score = section_score + path_score + table_score + action_score + length_score
    final_score = max(0, min(100, base_score - hedge_penalty - unknown_penalty))

    breakdown = {
        "sections": section_score,
        "evidence_paths": path_score,
        "structured_format": table_score,
        "actionability": action_score,
        "depth_length": length_score,
    }
    penalties = {
        "hedging_penalty": hedge_penalty,
        "unknown_penalty": unknown_penalty,
    }
    return final_score, breakdown, penalties

def get_tools_prompt(mcp: MCPManager) -> str:
    tools_list = []
    try:
        tools = mcp.get_openai_tools()
        for t in tools:
            tools_list.append(json.dumps(t['function']))
    except Exception as e:
        return f"Error loading tools: {e}"
        
    if not tools_list:
        return "No tools currently registered."
    return "\n".join(tools_list)

def attempt_tool_call(mcp: MCPManager, json_str: str) -> str:
    try:
        call_data = json.loads(json_str)
        tool_name = call_data.get("name")
        args = call_data.get("arguments", {})
        console.print(f"[bold yellow]Executing Tool:[/] {tool_name}")
        console.print(f"[dim]{json.dumps(args, indent=2)[:200]}...[/dim]")
        
        result = mcp.execute_tool(tool_name, args)
        short_res = result[:500] + "...(truncated)" if len(result) > 500 else result
        console.print(f"[bold blue]Result:[/] {short_res}")
        return result
    except json.JSONDecodeError:
        return "Error: Invalid JSON format for tool_call."
    except Exception as e:
        return f"Error executing tool: {str(e)}"

def send_chat(messages, mcp: MCPManager, memory: Optional['MemoryManager'] = None, deepseek_context: str = "") -> str:
    # Inject system prompt with tools dynamically
    system_prompt = SYSTEM_PROMPT.replace("{TOOLS}", get_tools_prompt(mcp))
    
    # Use pre-loaded DEEPSEEK.md context (auto-reloaded in main loop)
    if deepseek_context:
        system_prompt += f"\n\n=== PROJECT CONTEXT (DEEPSEEK.md - Auto-Loaded) ===\n{deepseek_context}"
    else:
        # Fallback: try to load DEEPSEEK.md if not already loaded
        deepseek_context = load_deepseek_context(os.getcwd())
        if deepseek_context:
            system_prompt += f"\n\n=== PROJECT CONTEXT (DEEPSEEK.md) ===\n{deepseek_context}"
    
    # Also try legacy context file for backward compatibility
    context = load_context_file(os.getcwd())
    if context and not deepseek_context:  # Only if DEEPSEEK.md doesn't exist
        system_prompt += f"\n\n=== WORKSPACE CONTEXT ===\n{context}"
    
    # Inject memory context (RAG)
    if memory and messages:
        last_user_msg = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), '')
        if last_user_msg:
            memory_context = memory.get_context_for_prompt(last_user_msg, top_k=3)
            if memory_context:
                system_prompt += f"\n\n{memory_context}"
    
    sys_msg = {"role": "system", "content": system_prompt}
    payload = {
        "model": get_effective_model(for_init=False),
        "messages": [sys_msg] + messages,
        "stream": True,
        "agent_mode": False
    }
    
    try:
        # Avoid overriding the whole loading state badly, but we will print inline
        res = requests.post(PROXY_URL, json=payload, timeout=300, stream=True)
        res.raise_for_status()

        full_content = ""
        full_reasoning = ""
        
        def _get_renderable():
            items = []
            if full_reasoning:
                items.append(
                    Panel(Text(full_reasoning, style="dim"), title="Thinking", border_style="dim")
                )
            if full_content:
                items.append(
                    Panel(Markdown(full_content), title="DeepSeek Response", border_style="blue")
                )
            # Nếu chưa có đoạn text nào
            if not items:
                items.append(Text("Connecting...", style="dim"))
            return Group(*items)

        # Clear previous print if needed
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

        with Live(_get_renderable(), console=console, refresh_per_second=12, transient=True) as live:
            for line in res.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                
                                updated = False
                                if "reasoning_content" in delta and delta["reasoning_content"]:
                                    full_reasoning += delta["reasoning_content"]
                                    updated = True

                                if "content" in delta and delta["content"]:
                                    full_content += delta["content"]
                                    updated = True
                                
                                if updated:
                                    live.update(_get_renderable())
                        except json.JSONDecodeError:
                            pass
        
        # In ra màn hình kết quả cuối cùng một lần duy nhất để tránh bị lặp khi chiều dài vượt quá terminal
        console.print(_get_renderable())
        
        # Fallback if the model put its entire response inside the reasoning block (common with R1)
        if not full_content.strip() and full_reasoning.strip():
            full_content = full_reasoning
            
        return full_content

    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]API Error:[/] Could not connect to Proxy at {PROXY_URL}. Is server.js running?\n{e}")
        return None


def send_init_analysis(analysis_prompt: str, project_context: str = "") -> Optional[str]:
    """Run /init analysis with a dedicated prompt that forbids tool-calls and enforces deep reporting."""
    init_system_prompt = """You are a senior security engineering analyst.
Your task is to produce a deep workspace analysis report from provided tree/config data only.

STRICT RULES:
1) Output final report text only (Markdown allowed).
2) Do NOT output any <tool_call> blocks.
3) Do NOT ask to read more files; use only the provided evidence.
4) Avoid hedging words (maybe, likely, có thể) unless clearly marked under Confidence & Gaps.
5) Be specific, actionable, and evidence-based with real paths from the input.

DEEP THINKING (MANDATORY):
- Run a 3-pass internal analysis: evidence extraction, risk synthesis, prioritized action plan.
- Prefer concrete conclusions over tentative phrasing when evidence exists.
"""

    user_content = analysis_prompt
    if project_context:
        user_content += f"\n\n=== EXISTING PROJECT CONTEXT ===\n{project_context}"

    payload = {
        "model": get_effective_model(for_init=True),
        "messages": [
            {"role": "system", "content": init_system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "agent_mode": False,
    }

    try:
        res = requests.post(PROXY_URL, json=payload, timeout=300)
        res.raise_for_status()
        data = res.json()
        content = data["choices"][0]["message"].get("content", "")
        if "<tool_call>" in content:
            content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
        return content
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Init Analysis API Error:[/] {e}")
        return None


def refine_init_analysis(analysis_prompt: str, draft_report: str, score: int, breakdown: Dict[str, int], penalties: Dict[str, int]) -> Optional[str]:
    """Refine a low-quality /init draft into a deeper, less-hedged final report."""
    refine_system_prompt = """You are improving a workspace analysis report.
Return only the improved final report in Markdown.

Constraints:
- Keep claims evidence-based from provided tree/config only.
- Remove vague hedging unless in Confidence & Gaps.
- Add concrete paths and prioritized actions.
- Keep a clear section structure and practical depth.
- Do NOT output <tool_call>.
"""

    refine_user_prompt = (
        f"Original request:\n{analysis_prompt}\n\n"
        f"Current score: {score}/100\n"
        f"Breakdown: {json.dumps(breakdown, ensure_ascii=False)}\n"
        f"Penalties: {json.dumps(penalties, ensure_ascii=False)}\n\n"
        "Improve this draft to increase quality:\n\n"
        f"{draft_report}"
    )

    payload = {
        "model": get_effective_model(for_init=True),
        "messages": [
            {"role": "system", "content": refine_system_prompt},
            {"role": "user", "content": refine_user_prompt},
        ],
        "stream": False,
        "agent_mode": False,
    }

    try:
        res = requests.post(PROXY_URL, json=payload, timeout=300)
        res.raise_for_status()
        data = res.json()
        content = data["choices"][0]["message"].get("content", "")
        if "<tool_call>" in content:
            content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
        return content
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Init Refine API Error:[/] {e}")
        return None

def main():
    global MODEL
    print_header()
    
    mcp = MCPManager()
    messages = []
    model_info = {"current_model": MODEL, "search_enabled": False, "thinking_enabled": False}
    
    # Initialize memory manager
    memory = MemoryManager(project_dir=os.getcwd())
    
    # Track current context for auto-reload
    last_context_path = None
    current_deepseek_context = ""
    
    print_info(f"Connected to proxy: {PROXY_URL.replace('/v1/chat/completions', '')}")
    print_info(f"Current model: {MODEL}")
    print_dim("Type '/help' for commands or start typing to chat")
    print_rule()
    
    while True:
        try:
            # ──── AUTO-LOAD DEEPSEEK.MD (Context-First) ────
            current_path = os.getcwd()
            new_context = load_deepseek_context(current_path)

            if new_context:
                if new_context != current_deepseek_context:
                    current_deepseek_context = new_context
                    last_context_path = current_path
                    print_dim("✓ Project context (DEEPSEEK.md) loaded automatically")
            elif current_path != last_context_path:
                # Directory changed or DEEPSEEK.md was removed
                current_deepseek_context = ""
                last_context_path = current_path
            
            print_prompt()
            user_input = sys.stdin.readline().strip()
            
            if not user_input:
                continue
            
            # ──── COMMANDS ────
            if user_input.lower() == "/exit":
                mcp.stop_all()
                print_success("Stopped all MCP servers")
                print_footer()
                break
            
            if user_input.lower() == "/help":
                print_commands_help()
                continue
            
            if user_input.lower().startswith("/init"):
                # Parse optional path parameter: /init or /init /path/to/project
                parts = user_input.split(maxsplit=1)
                target_dir = parts[1] if len(parts) > 1 else os.getcwd()
                
                # Ensure target_dir exists
                if not os.path.isdir(target_dir):
                    print_error(f"Directory not found: {target_dir}")
                    continue
                
                live = print_loading(f"🔍 Analyzing workspace: {target_dir}")
                try:
                    # Generate analysis prompt
                    analysis_prompt, project_info = generate_analysis_prompt(target_dir)
                    
                    # Show detected info
                    stop_loading(live)
                    print_info(f"Detected: {project_info['type']}")
                    if project_info['languages']:
                        print_info(f"Languages: {', '.join(project_info['languages'])}")
                    if project_info['frameworks']:
                        print_info(f"Frameworks: {', '.join(project_info['frameworks'])}")
                    
                    # Send to AI for analysis
                    live = print_loading("💭 DeepSeek is analyzing project...")
                    target_context = load_deepseek_context(target_dir)
                    analysis_response = send_init_analysis(analysis_prompt, target_context)
                    stop_loading(live)
                    
                    if analysis_response:
                        # Score and optionally refine low-quality draft (iterative improvement)
                        score, breakdown, penalties = score_analysis_quality(analysis_response)
                        max_refine_rounds = 2
                        refine_round = 0

                        while score < 80 and refine_round < max_refine_rounds:
                            refine_round += 1
                            live = print_loading(f"♻️ Refining analysis (round {refine_round}/{max_refine_rounds})...")
                            improved = refine_init_analysis(
                                analysis_prompt=analysis_prompt,
                                draft_report=analysis_response,
                                score=score,
                                breakdown=breakdown,
                                penalties=penalties,
                            )
                            stop_loading(live)
                            if not improved:
                                break

                            new_score, new_breakdown, new_penalties = score_analysis_quality(improved)
                            if new_score >= score:
                                analysis_response = improved
                                score, breakdown, penalties = new_score, new_breakdown, new_penalties

                        # Save to DEEPSEEK.md in target directory
                        deepseek_file = os.path.join(target_dir, "DEEPSEEK.md")
                        with open(deepseek_file, 'w', encoding='utf-8') as f:
                            f.write("# DeepSeek Project Context\n\n")
                            f.write(f"**Project Directory:** {target_dir}\n")
                            f.write(f"**Generated:** {datetime.now().isoformat()}\n")
                            f.write(f"**Project Type:** {project_info['type']}\n\n")
                            f.write(analysis_response)
                        
                        # Update in-memory context if /init runs on current directory
                        if os.path.abspath(target_dir) == os.path.abspath(os.getcwd()):
                            current_deepseek_context = analysis_response

                        print_success(f"✓ Analysis complete! Saved to {deepseek_file}")
                        print_info(f"📊 Analysis quality score: {score}/100")
                        print_dim(
                            "  + Sections: {sections}, Evidence paths: {evidence_paths}, "
                            "Structured format: {structured_format}, Actionability: {actionability}, "
                            "Depth: {depth_length}".format(**breakdown)
                        )
                        print_dim(
                            "  - Hedging penalty: {hedging_penalty}, Unknown penalty: {unknown_penalty}".format(**penalties)
                        )
                        
                        # Display analysis
                        print_rule()
                        print_response(analysis_response, "📋 Project Analysis")
                        print_rule()
                        print_info("Use this context: AI will automatically load DEEPSEEK.md for this project!")
                    else:
                        print_error("Failed to get analysis from AI")
                except Exception as e:
                    stop_loading(live)
                    print_error_panel("Init Error", str(e))
                continue
            
            if user_input.lower() == "/mcp list":
                mcp_status = {
                    "Shell": hasattr(mcp, '_shell_server') and mcp._shell_server is not None,
                    "Web Search": hasattr(mcp, '_web_search_server') and mcp._web_search_server is not None,
                    "Fetch": hasattr(mcp, '_fetch_server') and mcp._fetch_server is not None,
                    "Playwright": hasattr(mcp, '_playwright_server') and mcp._playwright_server is not None,
                    "Filesystem": "filesystem" in mcp.servers if hasattr(mcp, 'servers') else False,
                }
                print_mcp_status(mcp_status)
                continue
            
            if user_input.lower() == "/mcp auto":
                live = print_loading("Initializing MCP servers...")
                try:
                    mcp.add_shell_server()
                    mcp.add_web_search()
                    mcp.add_fetch_server()
                    mcp.add_playwright_server()
                    mcp.add_filesystem_server(["/"])  # Allow accessing the entire filesystem
                    stop_loading(live)
                    print_success("✓ Shell server ready")
                    print_success("✓ Web Search server ready")
                    print_success("✓ Fetch server ready")
                    print_success("✓ Playwright server ready")
                    print_success("✓ Filesystem server ready")
                    print_info("All MCP servers initialized. AI can now use tools automatically!")
                except Exception as e:
                    stop_loading(live)
                    print_error(f"Failed to initialize MCP servers: {e}")
                continue
            
            if user_input.lower() == "/mcp":
                # Show MCP status and available tools
                mcp_status = {
                    "Shell": hasattr(mcp, '_shell_server') and mcp._shell_server is not None,
                    "Web Search": hasattr(mcp, '_web_search_server') and mcp._web_search_server is not None,
                    "Fetch": hasattr(mcp, '_fetch_server') and mcp._fetch_server is not None,
                    "Playwright": hasattr(mcp, '_playwright_server') and mcp._playwright_server is not None,
                    "Filesystem": "filesystem" in mcp.servers if hasattr(mcp, 'servers') else False,
                }
                print_mcp_status(mcp_status)
                if not any(mcp_status.values()):
                    print_warning("No MCP servers initialized. Use /mcp auto to enable them.")
                continue
            
            if user_input.lower() == "/clear":
                messages = []
                print_success("Conversation history cleared")
                continue
            
            if user_input.lower() == "/models":
                models = [
                    {"id": "deepseek-chat", "vendor": "DeepSeek"},
                    {"id": "deepseek-reasoner", "vendor": "DeepSeek"},
                    {"id": "deepseek-chat-search", "vendor": "DeepSeek"},
                ]
                print_models_table(models)
                continue
            
            if user_input.startswith("/select "):
                try:
                    selected_idx = int(user_input.split(" ", 1)[1].strip())
                    models = ["deepseek-chat", "deepseek-reasoner", "deepseek-chat-search"]
                    if 1 <= selected_idx <= len(models):
                        new_model = models[selected_idx - 1]
                        MODEL = new_model
                        model_info["current_model"] = new_model
                        print_success(f"Switched to model: {new_model}")
                    else:
                        print_error(f"Invalid model number. Please choose between 1 and {len(models)}")
                except ValueError:
                    print_error("Invalid format. Use /select <number>")
                continue
            
            if user_input.startswith("/model "):
                new_model = user_input.split(" ", 1)[1].strip()
                MODEL = new_model
                model_info["current_model"] = new_model
                print_success(f"Switched to model: {new_model}")
                continue
            
            if user_input.startswith("/search "):
                mode = user_input.split(" ", 1)[1].strip().lower()
                if mode == "on":
                    model_info["search_enabled"] = True
                    print_success("Web search mode: ON")
                elif mode == "off":
                    model_info["search_enabled"] = False
                    print_success("Web search mode: OFF")
                continue
            
            if user_input.lower() == "/think":
                # Toggle thinking mode
                model_info["thinking_enabled"] = not model_info["thinking_enabled"]
                if model_info["thinking_enabled"]:
                    MODEL = "deepseek-reasoner"
                    print_success("🧠 Thinking mode: ON (switched to deepseek-reasoner)")
                else:
                    MODEL = "deepseek-chat"
                    print_success("🧠 Thinking mode: OFF (switched to deepseek-chat)")
                continue
            
            if user_input.startswith("/think "):
                mode = user_input.split(" ", 1)[1].strip().lower()
                if mode == "on":
                    model_info["thinking_enabled"] = True
                    MODEL = "deepseek-reasoner"
                    print_success("R1 thinking mode: ON (model switched to deepseek-reasoner)")
                elif mode == "off":
                    model_info["thinking_enabled"] = False
                    MODEL = "deepseek-chat"
                    print_success("R1 thinking mode: OFF (model switched to deepseek-chat)")
                continue
            
            if user_input.lower().startswith("/remember "):
                memory_text = user_input[10:].strip()
                if memory_text:
                    memory.add_memory(memory_text, category="user_input")
                    print_success(f"✓ Memorized: {memory_text[:50]}...")
                else:
                    print_error("Usage: /remember <something to remember>")
                continue
            
            if user_input.lower() == "/memory list":
                mems = memory.list_memories()
                if mems:
                    print_info(f"📚 Total memories: {len(mems)}")
                    for mem in mems[:10]:  # Show first 10
                        print_dim(f"  • [{mem['category']}] {mem['content'][:60]}...")
                    if len(mems) > 10:
                        print_dim(f"  ... and {len(mems) - 10} more")
                else:
                    print_info("No memories yet. Use /remember <text> to add.")
                continue
            
            if user_input.lower() == "/memory clear":
                memory.clear_memories()
                print_success("✓ All project memories cleared")
                continue
            
            if user_input.lower() == "/memory stats":
                stats = memory.get_stats()
                print_info(f"📊 Memory Stats:")
                print_dim(f"  • Project memories: {stats.get('project_memories', 0)}")
                print_dim(f"  • Global memories: {stats.get('global_memories', 0)}")
                print_dim(f"  • Total chat turns: {stats.get('turn_count', 0)}")
                continue
            
            # ──── CHAT ────
            messages.append({"role": "user", "content": user_input})
            
            # Multi-turn agent loop
            while True:
                # Removed print_loading as send_chat handles streaming inline
                response_text = send_chat(messages, mcp, memory, current_deepseek_context)  # Pass auto-loaded context
                
                if not response_text:
                    print_error("Failed to get response from proxy")
                    break
                
                messages.append({"role": "assistant", "content": response_text})
                
                # Check for tool calls
                tool_match = re.search(r"<tool_call>\s*({.*?})\s*</tool_call>", response_text, re.DOTALL)
                
                if tool_match:
                    # In real-time stream mode, intermediate responses and <tool_call> 
                    # are already printed to stdout. No need to reprint text_before.
                    print()
                    print_dim("⚙️ Intercepted Tool Call, executing...")
                    
                    tool_json = tool_match.group(1)
                    result = attempt_tool_call(mcp, tool_json)
                    
                    messages.append({
                        "role": "user", 
                        "content": f"<tool_result>\n{result}\n</tool_result>\nProceed with the next step or your final answer."
                    })
                else:
                    # No tool call, show final response
                    # Optional deep refinement for shallow non-tool responses
                    refined_round = 0
                    final_response = response_text
                    while refined_round < CHAT_REFINE_MAX_ROUNDS and should_refine_chat_response(user_input, final_response):
                        refined_round += 1
                        live = print_loading(f"🧠 Deep-refining answer (round {refined_round}/{CHAT_REFINE_MAX_ROUNDS})...")
                        improved = refine_chat_response(user_input, final_response, current_deepseek_context)
                        stop_loading(live)
                        if not improved or len(improved) <= len(final_response):
                            break
                        final_response = improved

                    # In ra lại bản refinded bọc panel nếu có qua dòng refine hoặc chưa in (nếu lỗi).
                    # Do response ban đầu đã được in ra dạng stream rồi, ta bỏ đi hành động in lặp lại.
                    if refined_round > 0:
                        print_response(final_response, "DeepSeek Response (Refined)")
                        
                    # Log interaction and auto-extract learnings
                    memory.log_interaction(user_input, final_response)
                    learnings = memory.auto_extract_if_needed(user_input, final_response)
                    if learnings:
                        print_success(f"🧠 Extracted {len(learnings)} new learning(s)")
                    
                    break
        
        except KeyboardInterrupt:
            print_footer()
            break
        except Exception as e:
            print_error_panel("Unexpected Error", str(e))
            break


if __name__ == "__main__":
    main()
