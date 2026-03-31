#!/usr/bin/env python3
"""
Open-Claw-Coder - Self-hosted Telegram AI Agent (Python Edition)
Run: python3 bot.py
"""

import os
import re
import sys
import time
import logging
import subprocess
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ApplicationHandlerStop

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x]
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())

# Pre-compute resolved workspace root once to avoid repeated Path.resolve() calls
WORKSPACE_ROOT_RESOLVED = str(Path(WORKSPACE_ROOT).resolve())

# Safety Guards
# Patterns are matched with re.search() so short tokens like "dd" are checked
# as whole words (via \b), preventing false positives on substrings like "add".
# The old "wget|curl" single-entry is split into two separate patterns.
DANGEROUS_PATTERNS = [
    r"rm\s+-rf",
    r"\bsudo\b",
    r"chmod\s+777",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r">\s*/dev/",
    r"\bwget\b",
    r"\bcurl\b",
]
ALLOWED_EXTENSIONS = [".py", ".txt", ".md", ".json", ".yaml", ".yml", ".js", ".ts"]
MAX_FILE_SIZE = 1024 * 1024  # 1MB

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# MEMORY (SQLite)
# ═══════════════════════════════════════════════════════════════════════════

DB_PATH = Path(WORKSPACE_ROOT) / ".clawbot_memory.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at INTEGER
        )""")

def save_memory(user_id: str, role: str, content: str):
    # Use a context manager so the transaction is committed automatically
    # and the connection is closed on exit (or rolled back on error).
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO memories (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, int(time.time())),
        )

# ═══════════════════════════════════════════════════════════════════════════
# TOOLS: FILESYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def safe_path(relative_path: str) -> Optional[Path]:
    """Prevent path traversal attacks."""
    try:
        full = (Path(WORKSPACE_ROOT) / relative_path).resolve()
        # Use the pre-computed resolved root to avoid repeated Path.resolve() calls
        if not str(full).startswith(WORKSPACE_ROOT_RESOLVED):
            return None
        return full
    except Exception:
        return None

def read_file(relative_path: str) -> Dict[str, Any]:
    full_path = safe_path(relative_path)
    if not full_path:
        return {"success": False, "error": "Path traversal detected"}
    if not full_path.exists():
        return {"success": False, "error": "File not found"}
    if full_path.suffix not in ALLOWED_EXTENSIONS:
        return {"success": False, "error": f"Extension {full_path.suffix} not allowed"}
    try:
        if full_path.stat().st_size > MAX_FILE_SIZE:
            return {"success": False, "error": "File too large"}
        return {"success": True, "output": full_path.read_text(encoding="utf-8")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def write_file(relative_path: str, content: str) -> Dict[str, Any]:
    full_path = safe_path(relative_path)
    if not full_path:
        return {"success": False, "error": "Path traversal detected"}
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        # Backup existing file before overwriting
        if full_path.exists():
            backup = full_path.with_suffix(full_path.suffix + f".bak.{int(time.time())}")
            full_path.rename(backup)
        full_path.write_text(content, encoding="utf-8")
        return {"success": True, "output": f"Written to {relative_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════════════════════
# TOOLS: SHELL
# ═══════════════════════════════════════════════════════════════════════════

def run_command(command: str, require_confirmation: bool = True) -> Dict[str, Any]:
    # Safety Check — use regex patterns to avoid false positives on substrings
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {"success": False, "error": "Dangerous command blocked"}

    if require_confirmation:
        return {"success": False, "error": f"CONFIRMATION_REQUIRED:{command}"}

    try:
        result = subprocess.run(
            command, shell=True, cwd=WORKSPACE_ROOT,
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout or result.stderr
        return {"success": result.returncode == 0, "output": output}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════════════════════
# AGENT: AUDITOR (Mock Logic for Python)
# ═══════════════════════════════════════════════════════════════════════════

def audit_issue(issue_text: str) -> str:
    """Simulates the 5-agent audit logic."""
    # In production, call LLM API here
    return f"""A) TL;DR: NEEDS_WORK
B) Claim verification matrix:
| Evidence | Missing |
| Root Cause | Not identified |
E) Concerns:
1. BLOCKER: No reproduction provided
2. BLOCKER: No logs attached
F) Tests: Missing failing test case"""

# ═══════════════════════════════════════════════════════════════════════════
# TELEGRAM BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

async def security_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None or user_id not in ALLOWED_USER_IDS:
        if update.message:
            await update.message.reply_text("🚫 Access Denied")
        raise ApplicationHandlerStop

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🦞 Clawbot Active\n\nWorkspace: {WORKSPACE_ROOT}\n\n"
        "/review <file> - Analyze file\n"
        "/run <command> - Run a shell command\n"
        "/debug <info> - Debug helper"
    )

async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # `text` holds the joined arguments; was previously shadowed by undefined `file_path`
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /review <file>")
        return
    result = read_file(text)
    if result["success"]:
        await update.message.reply_text(f"📄 {text}\nSize: {len(result['output'])} chars\n\n(Analysis stub)")
    else:
        await update.message.reply_text(f"❌ {result['error']}")

def _format_command_result(result: Dict[str, Any]) -> str:
    """Format a run_command result dict as a user-facing string."""
    status = "✅" if result.get("success") else "❌"
    body = result.get("output") or result.get("error") or ""
    return f"{status} {body}"

async def run_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = " ".join(context.args)
    if not command:
        await update.message.reply_text("Usage: /run <command>")
        return
    result = run_command(command, require_confirmation=True)
    if result.get("error", "").startswith("CONFIRMATION_REQUIRED:"):
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"run_confirm:{command}"),
                InlineKeyboardButton("❌ Cancel", callback_data="run_cancel"),
            ]
        ]
        await update.message.reply_text(
            f"⚠️ Confirm command:\n`{command}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(_format_command_result(result))

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = " ".join(context.args)
    if not info:
        await update.message.reply_text("Usage: /debug <issue description>")
        return
    report = audit_issue(info)
    await update.message.reply_text(f"🔍 Audit Report:\n\n{report}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("run_confirm:"):
        command = data[len("run_confirm:"):]
        result = run_command(command, require_confirmation=False)
        await query.edit_message_text(_format_command_result(result))
    elif data == "run_cancel":
        await query.edit_message_text("❌ Command cancelled.")

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    if not ALLOWED_USER_IDS:
        print("❌ ALLOWED_USER_IDS not set")
        sys.exit(1)

    init_db()
    print(f"🦞 Starting Clawbot (Python) | Workspace: {WORKSPACE_ROOT}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Security Middleware: group=-1 ensures this runs before group=0 command handlers
    app.add_handler(MessageHandler(filters.ALL, security_filter), group=-1)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("review", review_command))
    app.add_handler(CommandHandler("run", run_command_handler))
    app.add_handler(CommandHandler("debug", debug_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
