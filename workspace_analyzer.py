#!/usr/bin/env python3
"""
Workspace Analyzer Module
==========================

Phân tích cấu trúc dự án và tạo chiến lược phát triển tự động.
Dành cho tính năng /init trong DeepSeek CLI.

Features:
- Build file tree (bỏ qua thư mục rác)
- Đọc các file config quan trọng
- Generate chiến lược cho dự án
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple

# Các thư mục/file cần bỏ qua
IGNORE_DIRS = {
    '.git', '.github', '.venv', 'venv', 'env', 'ENV',
    'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache',
    'dist', 'build', 'egg-info', '.egg-info',
    '.next', '.nuxt', '.cache', '.DS_Store',
    'target', 'bin', 'obj', '.gradle',
    'coverage', '.coverage', '.nyc_output',
    'package-lock.json', 'yarn.lock', '.lock',
    'pycache', 'htmlcov', '.tox',
}

IGNORE_FILES = {
    '.DS_Store', 'Thumbs.db', '.env.local', '.env.*.local',
    '*.pyc', '*.pyo', '*.pyd', '*.so', '*.dll',
    '*.swp', '*.swo', '*~', '.DS_Store',
}

CONFIG_FILES = [
    'package.json', 'requirements.txt', 'setup.py', 'pyproject.toml',
    'Gemfile', 'go.mod', 'Cargo.toml', 'pom.xml',
    'tsconfig.json', 'webpack.config.js', 'Dockerfile',
    'docker-compose.yml', '.env.example',
    'README.md', '.gitignore', 'CONTRIBUTING.md',
]


def should_ignore(name: str, is_dir: bool = False) -> bool:
    """Kiểm tra xem file/folder có nên bỏ qua không"""
    if is_dir and name in IGNORE_DIRS:
        return True
    if not is_dir and any(name.endswith(pattern.replace('*', '')) for pattern in IGNORE_FILES if '*' in pattern):
        return True
    if not is_dir and name in IGNORE_FILES:
        return True
    return False


def build_file_tree(root_dir: str, max_depth: int = 4, current_depth: int = 0) -> str:
    """
    Xây dựng file tree dạng text từ thư mục.
    
    Args:
        root_dir: Đường dẫn gốc
        max_depth: Độ sâu tối đa (để tránh quá dài)
        current_depth: Độ sâu hiện tại
    
    Returns:
        String chứa file tree
    """
    if current_depth >= max_depth:
        return ""
    
    lines = []
    try:
        entries = sorted(os.listdir(root_dir))
    except PermissionError:
        return ""
    
    dirs = []
    files = []
    
    for entry in entries:
        full_path = os.path.join(root_dir, entry)
        is_dir = os.path.isdir(full_path)
        
        if should_ignore(entry, is_dir):
            continue
        
        if is_dir:
            dirs.append((entry, full_path))
        else:
            files.append(entry)
    
    # Hiển thị files trước
    for i, file in enumerate(files):
        is_last_file = (i == len(files) - 1) and len(dirs) == 0
        prefix = "└── " if is_last_file else "├── "
        lines.append(f"{'  ' * current_depth}{prefix}{file}")
    
    # Sau đó là directories
    for i, (dir_name, dir_path) in enumerate(dirs):
        is_last = i == len(dirs) - 1
        prefix = "└── " if is_last else "├── "
        lines.append(f"{'  ' * current_depth}{prefix}{dir_name}/")
        
        # Recursive call
        sub_tree = build_file_tree(dir_path, max_depth, current_depth + 1)
        if sub_tree:
            lines.append(sub_tree)
    
    return "\n".join(lines)


def read_config_files(root_dir: str) -> Dict[str, str]:
    """
    Đọc các file config quan trọng.
    
    Returns:
        Dict với tên file làm key, nội dung làm value
    """
    configs = {}
    
    for config_file in CONFIG_FILES:
        config_path = os.path.join(root_dir, config_file)
        
        if os.path.isfile(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Giới hạn độ dài để không quá dài
                    if len(content) > 5000:
                        content = content[:5000] + "\n... (truncated)"
                    configs[config_file] = content
            except (UnicodeDecodeError, PermissionError):
                pass
    
    return configs


def detect_project_type(root_dir: str, configs: Dict[str, str]) -> Dict[str, any]:
    """
    Phát hiện loại dự án và tech stack.
    
    Returns:
        Dict chứa thông tin về dự án
    """
    project_info = {
        "type": "Unknown",
        "languages": [],
        "frameworks": [],
        "build_tools": [],
    }
    
    # Kiểm tra file tree
    tree_str = build_file_tree(root_dir, max_depth=2)
    
    # Phát hiện theo file config
    if 'package.json' in configs:
        project_info["type"] = "Node.js/JavaScript"
        project_info["languages"].append("JavaScript/TypeScript")
        try:
            pkg = json.loads(configs['package.json'])
            if 'dependencies' in pkg:
                deps = list(pkg['dependencies'].keys())
                if any('react' in dep for dep in deps):
                    project_info["frameworks"].append("React")
                if any('vue' in dep for dep in deps):
                    project_info["frameworks"].append("Vue")
                if any('next' in dep for dep in deps):
                    project_info["frameworks"].append("Next.js")
                if any('express' in dep for dep in deps):
                    project_info["frameworks"].append("Express")
        except:
            pass
    
    if 'requirements.txt' in configs or 'setup.py' in configs or 'pyproject.toml' in configs:
        project_info["type"] = "Python"
        project_info["languages"].append("Python")
        if 'django' in (configs.get('requirements.txt', '') or ''):
            project_info["frameworks"].append("Django")
        if 'flask' in (configs.get('requirements.txt', '') or ''):
            project_info["frameworks"].append("Flask")
    
    if 'Dockerfile' in configs:
        project_info["build_tools"].append("Docker")
    
    if 'Gemfile' in configs:
        project_info["type"] = "Ruby"
        project_info["languages"].append("Ruby")
    
    if 'go.mod' in configs:
        project_info["type"] = "Go"
        project_info["languages"].append("Go")
    
    return project_info


def generate_analysis_prompt(root_dir: str) -> Tuple[str, Dict]:
    """
    Tạo prompt để gửi tới AI để phân tích dự án.
    
    Returns:
        (prompt_text, project_metadata)
    """
    # Build tree
    file_tree = build_file_tree(root_dir, max_depth=4)
    
    # Read configs
    configs = read_config_files(root_dir)
    
    # Detect project type
    project_info = detect_project_type(root_dir, configs)
    
    # Build prompt
    prompt_parts = [
        "=== WORKSPACE ANALYSIS REQUEST ===\n",
        f"Current Working Directory: {root_dir}\n",
        f"Detected Project Type: {project_info['type']}\n",
        f"Languages: {', '.join(project_info['languages']) or 'Unknown'}\n",
        f"Frameworks: {', '.join(project_info['frameworks']) or 'None'}\n",
        f"Build Tools: {', '.join(project_info['build_tools']) or 'None'}\n\n",
        
        "=== FILE TREE ===\n",
        f"```\n{root_dir}/\n{file_tree}\n```\n\n",
        
        "=== KEY CONFIG FILES ===\n",
    ]
    
    for config_name, config_content in sorted(configs.items()):
        prompt_parts.append(f"\n{config_name}:\n```\n{config_content}\n```\n")
    
        prompt_parts.append("""
=== ANALYSIS TASK (DEEP MODE) ===
Based on the project structure and configurations above, produce a deep, evidence-based analysis.

MANDATORY RULES:
1) Ground every claim in visible evidence from file tree/config content.
2) Prefer definitive statements when evidence exists.
3) If evidence is missing, explicitly write **UNKNOWN** and list what is needed.
4) Avoid vague hedging words like: maybe, likely, possibly, có thể, dường như.
5) Include concrete file/folder paths in each major section.

OUTPUT FORMAT (MANDATORY):

## Project Summary
- 3-5 concise bullets
- Must include the main objective and current maturity level

## Tech Stack
- Table: Category | Tools/Frameworks | Evidence (path)
- Only include items with evidence

## Project Structure (Deep)
- Explain top-level folders and their role in workflow
- For each critical folder, include:
    - Purpose
    - Typical artifacts
    - Security/testing value

## Key Files (High-Impact)
- Table: File Path | Why Important | Risk/Opportunity
- Include at least 8 items when available

## Workflow Assessment
- Describe likely end-to-end workflow used by this workspace
- Include bottlenecks and operational risks

## Improvement Plan (Prioritized)
- P0 / P1 / P2 priorities
- Each item must include: action, expected impact, effort (S/M/L)

## Development Guidelines
- Provide practical rules for future work in this workspace
- Include naming conventions, evidence handling, and reporting standards

## Confidence & Gaps
- Confidence score (0-100)
- List uncertain areas and what additional evidence is needed

QUALITY BAR:
- Be specific, technical, and actionable.
- Do not repeat generic advice.
- Use markdown headings, bullet lists, and tables for readability.
""")
    
    prompt_text = "".join(prompt_parts)
    
    return prompt_text, project_info


def save_context_file(root_dir: str, analysis_text: str) -> str:
    """
    Lưu analysis vào file `.deepseek_context.md`.
    
    Returns:
        Đường dẫn file được lưu
    """
    deepseek_dir = os.path.join(root_dir, '.deepseek')
    os.makedirs(deepseek_dir, exist_ok=True)
    
    context_file = os.path.join(deepseek_dir, 'context.md')
    
    with open(context_file, 'w', encoding='utf-8') as f:
        f.write("# DeepSeek Project Context\n\n")
        f.write(f"Generated at: {Path(root_dir).name}\n")
        f.write(f"Last Updated: {__import__('datetime').datetime.now().isoformat()}\n\n")
        f.write(analysis_text)
    
    return context_file


def load_context_file(root_dir: str) -> str:
    """
    Tải analysis từ file `.deepseek_context.md` nếu tồn tại.
    
    Returns:
        Content hoặc empty string nếu không tìm thấy
    """
    context_file = os.path.join(root_dir, '.deepseek', 'context.md')
    
    if os.path.isfile(context_file):
        try:
            with open(context_file, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            pass
    
    return ""


if __name__ == "__main__":
    # Demo
    if len(sys.argv) > 1:
        root = sys.argv[1]
    else:
        root = os.getcwd()
    
    print(f"Analyzing: {root}\n")
    prompt, info = generate_analysis_prompt(root)
    print(prompt)
    print(f"\n\nProject Info: {info}")
