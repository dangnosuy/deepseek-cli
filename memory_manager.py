#!/usr/bin/env python3
"""
Memory Manager Module for DeepSeek CLI
========================================

Cung cấp khả năng lưu trữ dài hạn (Long-term Memory) và RAG (Retrieval-Augmented Generation).
Sử dụng SQLite + Embedding đơn giản để trích xuất kiến thức từ lịch sử chat.

Features:
- Simple text-based memory storage
- Semantic search (sử dụng embedding API hoặc local model)
- Auto-extraction sau mỗi 5-10 turn chat
- Project-scoped memory + Global memory
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Try to import embedding model
try:
    from sentence_transformers import SentenceTransformer
    HAS_EMBEDDING = True
    EMBEDDING_MODEL = None  # Will be lazily loaded
except ImportError:
    HAS_EMBEDDING = False
    print("[WARNING] sentence-transformers not installed. Memory search will be basic.")


class MemoryManager:
    """
    Quản lý bộ nhớ dài hạn cho DeepSeek CLI.
    
    Có 2 cấp độ memory:
    1. Project Memory: Lưu ở .deepseek/memory.db (tỷ lệ 70%)
    2. Global Memory: Lưu ở ~/.deepseek_memory.db (tỷ lệ 30%)
    """
    
    def __init__(self, project_dir: Optional[str] = None, use_embedding: bool = True):
        """
        Khởi tạo Memory Manager.
        
        Args:
            project_dir: Đường dẫn dự án (mặc định: cwd)
            use_embedding: Có dùng embedding API không
        """
        self.project_dir = project_dir or os.getcwd()
        self.use_embedding = use_embedding
        
        # Setup project memory
        self.project_mem_dir = os.path.join(self.project_dir, '.deepseek')
        os.makedirs(self.project_mem_dir, exist_ok=True)
        self.project_db = os.path.join(self.project_mem_dir, 'memory.db')
        
        # Setup global memory
        home_dir = os.path.expanduser('~')
        self.global_db = os.path.join(home_dir, '.deepseek_memory.db')
        
        # Initialize databases
        self._init_db(self.project_db)
        self._init_db(self.global_db)
        
        # Chat turn counter (để auto-extract)
        self.turn_count = 0
        self.extraction_interval = 5  # Extract sau mỗi 5 turn
        
        # Embedding model (lazy load)
        self.embedding_model = None
    
    def _init_db(self, db_path: str):
        """Tạo bảng memory nếu chưa tồn tại."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding BLOB,
                category TEXT DEFAULT 'general',
                source TEXT DEFAULT 'user',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_msg TEXT,
                assistant_msg TEXT,
                turn_num INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                extracted BOOLEAN DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_embedding_model(self):
        """Lazy load embedding model nếu cần."""
        if not HAS_EMBEDDING or self.embedding_model is not None:
            return
        
        try:
            print("[INFO] Loading embedding model... (first time only)")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            print(f"[WARNING] Failed to load embedding model: {e}")
            self.embedding_model = None
    
    def _get_embedding(self, text: str) -> Optional[bytes]:
        """Lấy embedding cho text. Return None nếu không có model."""
        if not self.use_embedding or not HAS_EMBEDDING:
            return None
        
        try:
            self._load_embedding_model()
            if self.embedding_model is None:
                return None
            
            embedding = self.embedding_model.encode(text)
            return embedding.astype('float32').tobytes()
        except Exception as e:
            print(f"[WARNING] Embedding error: {e}")
            return None
    
    def add_memory(self, content: str, category: str = "general", 
                   metadata: Optional[Dict] = None, is_global: bool = False) -> bool:
        """
        Thêm một ký ức mới.
        
        Args:
            content: Nội dung cần nhớ
            category: Loại ký ức (general, code_style, user_preference, etc.)
            metadata: Thông tin bổ sung
            is_global: Có lưu global memory không
        
        Returns:
            True nếu thành công
        """
        db_path = self.global_db if is_global else self.project_db
        
        try:
            embedding = self._get_embedding(content)
            metadata_json = json.dumps(metadata) if metadata else None
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO memories (content, embedding, category, source, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (content, embedding, category, "user", metadata_json))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to add memory: {e}")
            return False
    
    def search_memory(self, query: str, top_k: int = 3, 
                      is_global: bool = False) -> List[Dict]:
        """
        Tìm kiếm ký ức liên quan.
        
        Args:
            query: Câu hỏi/cụm từ tìm kiếm
            top_k: Số kết quả trả về
            is_global: Tìm trong global memory không
        
        Returns:
            List các ký ức liên quan nhất
        """
        db_path = self.global_db if is_global else self.project_db
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Nếu có embedding, dùng semantic search
            if self.use_embedding and HAS_EMBEDDING:
                try:
                    self._load_embedding_model()
                    query_embedding = self.embedding_model.encode(query)
                    
                    # Get all memories
                    cursor.execute("SELECT id, content, category, timestamp FROM memories")
                    rows = cursor.fetchall()
                    
                    # Calculate similarity
                    results = []
                    for row_id, content, category, timestamp in rows:
                        if not content:
                            continue
                        
                        # Simple cosine similarity
                        try:
                            mem_embedding = SentenceTransformer('all-MiniLM-L6-v2').encode(content)
                            similarity = (query_embedding @ mem_embedding) / (
                                (query_embedding @ query_embedding) ** 0.5 * 
                                (mem_embedding @ mem_embedding) ** 0.5 + 1e-6
                            )
                            results.append({
                                'id': row_id,
                                'content': content,
                                'category': category,
                                'timestamp': timestamp,
                                'score': float(similarity)
                            })
                        except:
                            pass
                    
                    # Sort by score
                    results.sort(key=lambda x: x['score'], reverse=True)
                    conn.close()
                    return results[:top_k]
                except:
                    pass
            
            # Fallback: Simple text search (substring match)
            query_lower = query.lower()
            cursor.execute(
                "SELECT id, content, category, timestamp FROM memories WHERE LOWER(content) LIKE ?",
                (f"%{query_lower}%",)
            )
            rows = cursor.fetchall()
            
            results = [
                {
                    'id': row[0],
                    'content': row[1],
                    'category': row[2],
                    'timestamp': row[3],
                    'score': 1.0  # Binary score
                }
                for row in rows
            ]
            
            conn.close()
            return results[:top_k]
        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            return []
    
    def log_interaction(self, user_msg: str, assistant_msg: str):
        """Ghi lại một lần tương tác."""
        self.turn_count += 1
        
        try:
            conn = sqlite3.connect(self.project_db)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO interactions (user_msg, assistant_msg, turn_num)
                VALUES (?, ?, ?)
            """, (user_msg, assistant_msg, self.turn_count))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARNING] Failed to log interaction: {e}")
    
    def extract_learnings(self, user_msg: str, assistant_msg: str) -> List[str]:
        """
        Tự động trích xuất kiến thức từ một interaction.
        Nên được gọi sau mỗi 5-10 turn.
        
        Hiện tại: Simple heuristic (có thể upgrade dùng AI extraction)
        
        Returns:
            List các kiến thức mới được extract
        """
        learnings = []
        
        # Heuristic 1: Detect "format preference"
        if "format" in user_msg.lower() or "style" in user_msg.lower():
            if "always" in user_msg.lower() or "always use" in user_msg.lower():
                learnings.append({
                    'content': f"User preference: {user_msg}",
                    'category': 'user_preference'
                })
        
        # Heuristic 2: Detect code style patterns
        if "use" in user_msg.lower() and ("arrow" in user_msg.lower() or 
                                          "const" in user_msg.lower() or
                                          "def " in user_msg.lower()):
            learnings.append({
                'content': f"Coding style rule: {user_msg}",
                'category': 'code_style'
            })
        
        # Heuristic 3: Important decisions
        if "decided" in user_msg.lower() or "decision" in user_msg.lower():
            learnings.append({
                'content': f"Project decision: {user_msg}",
                'category': 'decision'
            })
        
        # Store learnings
        for learning in learnings:
            self.add_memory(
                learning['content'],
                category=learning['category'],
                metadata={'source': 'auto_extraction'}
            )
        
        return learnings
    
    def get_context_for_prompt(self, current_user_input: str, top_k: int = 3) -> str:
        """
        Tạo context string để chèn vào prompt hiện tại.
        Dùng semantic search để tìm các ký ức liên quan.
        
        Returns:
            Formatted context string
        """
        # Tìm từ project memory
        project_memories = self.search_memory(current_user_input, top_k=top_k, is_global=False)
        
        # Tìm từ global memory (ít quan trọng hơn)
        global_memories = self.search_memory(current_user_input, top_k=top_k//2, is_global=True)
        
        if not project_memories and not global_memories:
            return ""
        
        context_lines = ["[Previous Context / Kiến thức đã biết:"]
        
        for mem in project_memories:
            context_lines.append(f"  • {mem['content'][:100]}... (Project)")
        
        for mem in global_memories:
            context_lines.append(f"  • {mem['content'][:100]}... (Global)")
        
        context_lines.append("]")
        
        return "\n".join(context_lines)
    
    def auto_extract_if_needed(self, user_msg: str, assistant_msg: str) -> List[str]:
        """
        Tự động extract kiến thức nếu đã tới interval.
        
        Returns:
            List learnings được extract (hoặc empty list)
        """
        if self.turn_count % self.extraction_interval == 0:
            return self.extract_learnings(user_msg, assistant_msg)
        return []
    
    def list_memories(self, category: Optional[str] = None, 
                     is_global: bool = False) -> List[Dict]:
        """Liệt kê tất cả ký ức."""
        db_path = self.global_db if is_global else self.project_db
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            if category:
                cursor.execute(
                    "SELECT id, content, category, timestamp FROM memories WHERE category = ?",
                    (category,)
                )
            else:
                cursor.execute("SELECT id, content, category, timestamp FROM memories")
            
            rows = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'id': row[0],
                    'content': row[1],
                    'category': row[2],
                    'timestamp': row[3]
                }
                for row in rows
            ]
        except Exception as e:
            print(f"[ERROR] Failed to list memories: {e}")
            return []
    
    def clear_memories(self, is_global: bool = False) -> bool:
        """Xóa toàn bộ ký ức."""
        db_path = self.global_db if is_global else self.project_db
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to clear memories: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """Lấy thống kê về memory."""
        try:
            proj_conn = sqlite3.connect(self.project_db)
            proj_cursor = proj_conn.cursor()
            proj_cursor.execute("SELECT COUNT(*) FROM memories")
            proj_count = proj_cursor.fetchone()[0]
            proj_conn.close()
            
            global_conn = sqlite3.connect(self.global_db)
            global_cursor = global_conn.cursor()
            global_cursor.execute("SELECT COUNT(*) FROM memories")
            global_count = global_cursor.fetchone()[0]
            global_conn.close()
            
            return {
                'project_memories': proj_count,
                'global_memories': global_count,
                'total_memories': proj_count + global_count,
                'turn_count': self.turn_count
            }
        except Exception as e:
            print(f"[WARNING] Failed to get stats: {e}")
            return {}


if __name__ == "__main__":
    # Demo
    print("🧠 Memory Manager Demo\n")
    
    mm = MemoryManager()
    
    # Add some test memories
    mm.add_memory("Always use arrow functions in JavaScript", category="code_style")
    mm.add_memory("Prefer React hooks over class components", category="code_style")
    mm.add_memory("Use snake_case for Python variables", category="code_style")
    
    # Search
    print("\n🔍 Searching for 'javascript style':")
    results = mm.search_memory("javascript code style")
    for r in results:
        print(f"  • {r['content']} (score: {r['score']:.2f})")
    
    # Get stats
    print(f"\n📊 Stats: {mm.get_stats()}")
