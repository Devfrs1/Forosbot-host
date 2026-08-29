#!/usr/bin/env python3
import os
import sys
import re
import json
import time
import signal
import logging
import subprocess
import threading
from datetime import datetime
import psutil
import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("manager.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Constants
TOKEN = "8923444398:AAF68GO0jb3_1ofreVAnMF7APcfdoIY0_K4"
DEPLOY_DIR = os.path.abspath("./deployed_bots")
SCRIPTS_DIR = os.path.join(DEPLOY_DIR, "scripts")
LOGS_DIR = os.path.join(DEPLOY_DIR, "logs")
METADATA_FILE = os.path.join(DEPLOY_DIR, "bots_metadata.json")

# Ensure directories exist
os.makedirs(DEPLOY_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Global active process dict (bot_id -> subprocess.Popen)
active_processes = {}

# Import and package lists
STD_LIBS = {
    'os', 'sys', 're', 'json', 'subprocess', 'time', 'threading', 'math', 'random',
    'datetime', 'collections', 'urllib', 'http', 'socket', 'shutil', 'asyncio', 'logging',
    'hashlib', 'uuid', 'base64', 'csv', 'tempfile', 'argparse', 'typing', 'traceback',
    'pathlib', 'functools', 'itertools', 'select', 'signal', 'struct', 'select', 'platform'
}

IMPORT_MAPPING = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'discord': 'discord.py',
    'bs4': 'beautifulsoup4',
    'numpy': 'numpy',
    'pandas': 'pandas',
    'matplotlib': 'matplotlib',
    'dotenv': 'python-dotenv',
    'PIL': 'Pillow',
    'flask': 'Flask',
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'jinja2': 'Jinja2',
    'sqlalchemy': 'SQLAlchemy',
    'requests': 'requests',
    'aiohttp': 'aiohttp',
    'tweepy': 'tweepy',
    'scrapy': 'scrapy',
    'gspread': 'gspread',
    'oauth2client': 'oauth2client',
}

# Load or initialize metadata
def load_metadata():
    if not os.path.exists(METADATA_FILE):
        return {"bots": {}}
    try:
        with open(METADATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading metadata: {e}")
        return {"bots": {}}

def save_metadata(data):
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")

# Process Management Helper
def stop_process(pid):
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                child.terminate()
            except Exception:
                pass
        parent.terminate()
        # Wait up to 3 seconds for process to exit
        gone, alive = psutil.wait_procs([parent] + parent.children(recursive=True), timeout=3)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        return True
    except psutil.NoSuchProcess:
        return True
    except Exception as e:
        logger.error(f"Failed to kill process {pid}: {e}")
        return False

# Initialize bot
try:
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=False)
    logger.info("Main Manager Bot initialized successfully.")
except Exception as e:
    logger.critical(f"Failed to initialize Telegram Bot: {e}")
    sys.exit(1)

# Extract and install python dependencies
def install_python_deps(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        detected = set()

        # 1. Standard PEP 723 parsing (e.g. within `# /// script` metadata block)
        pep723_match = re.search(r'#\s*/\s*/\s*/\s*script[\s\S]*?#\s*/\s*/\s*/\s*', content)
        if pep723_match:
            block = pep723_match.group(0)
            dep_lines = re.findall(r'["\']([a-zA-Z0-9_\-\[\]]+(?:[<>=!~]+[a-zA-Z0-9_\-\.]+)??)["\']', block)
            if dep_lines:
                for dep in dep_lines:
                    dep = dep.strip()
                    if dep and not dep.startswith("/") and not dep.startswith("."):
                        prefix_match = re.match(r'^([a-zA-Z0-9_\-]+)', dep)
                        if prefix_match:
                            prefix = prefix_match.group(1)
                            mapped = IMPORT_MAPPING.get(prefix, prefix)
                            detected.add(dep.replace(prefix, mapped))
                        else:
                            detected.add(dep)

        # 2. Header parsing (e.g. `# pip: requests==2.31.0` or `# requirements: numpy>=1.2.0`)
        pip_header_match = re.search(r'#\s*(?:pip|requirements|dependencies):\s*([^\r\n]+)', content, re.IGNORECASE)
        if pip_header_match and pip_header_match.group(1):
            reqs = pip_header_match.group(1).split(",")
            for r in reqs:
                dep = r.strip()
                if dep:
                    prefix_match = re.match(r'^([a-zA-Z0-9_\-]+)', dep)
                    if prefix_match:
                        prefix = prefix_match.group(1)
                        mapped = IMPORT_MAPPING.get(prefix, prefix)
                        detected.add(dep.replace(prefix, mapped))
                    else:
                        detected.add(dep)

        # 3. Line-by-line scanning & inline comment constraints (e.g. `import requests # version: 2.31.0`)
        lines = content.split("\n")
        for line in lines:
            import_match = re.match(r'^\s*(?:import\s+([a-zA-Z0-9_,\s]+)|from\s+([a-zA-Z0-9_]+)\s+import)', line)
            if import_match:
                raw_mods = []
                if import_match.group(1):
                    for m in import_match.group(1).split(","):
                        raw_mods.append(m.strip().split(".")[0])
                elif import_match.group(2):
                    raw_mods.append(import_match.group(2).strip().split(".")[0])

                for raw_mod in raw_mods:
                    mod = raw_mod.strip()
                    if mod and mod not in STD_LIBS:
                        mapped = IMPORT_MAPPING.get(mod, mod)
                        comment_match = re.search(r'#\s*(?:version:\s*|==|>=|@)?\s*([0-9a-zA-Z\.\-\+]+)', line, re.IGNORECASE)
                        if comment_match and comment_match.group(1):
                            ver = comment_match.group(1).strip()
                            if re.match(r'^[0-9]', ver):
                                detected.add(f"{mapped}=={ver}")
                                continue
                            elif re.match(r'^[<>=~]', ver):
                                detected.add(f"{mapped}{ver}")
                                continue
                        detected.add(mapped)

        # Filter duplicates: keep versioned ones if both unversioned and versioned exist
        final_detected = set()
        for dep in detected:
            base_name = re.split(r'[<>=!~@]', dep)[0].strip()
            has_versioned = any(
                other != dep and 
                other.startswith(base_name) and 
                ("=" in other or ">" in other or "<" in other or "~" in other)
                for other in detected
            )
            if not has_versioned or dep != base_name:
                final_detected.add(dep)

        if final_detected:
            needed_packages = list(final_detected)
            logger.info(f"Installing detected python dependencies: {needed_packages}")
            # Install packages via pip
            for pkg in needed_packages:
                cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", pkg]
                logger.info(f"Running command: {' '.join(cmd)}")
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return needed_packages
        return []
    except Exception as e:
        logger.error(f"Error resolving python dependencies: {e}")
        return []

# Extract and install node dependencies
def install_node_deps(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        detected = set()

        # 1. Comment header parsing (e.g. `// npm: express@4.18.2, lodash@4.17.21`)
        npm_header_match = re.search(r'//\s*(?:npm|dependencies):\s*([^\r\n]+)', content, re.IGNORECASE)
        if npm_header_match and npm_header_match.group(1):
            reqs = npm_header_match.group(1).split(",")
            for r in reqs:
                dep = r.strip()
                if dep:
                    detected.add(dep)

        # 2. Line-by-line scanning & inline comment constraints (e.g. `import express from 'express' // @4.18.2`)
        lines = content.split("\n")
        for line in lines:
            detected_mods = []
            r_matches = re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', line)
            i_matches = re.findall(r'from\s+[\'"]([^\'"]+)[\'"]', line)
            for m in r_matches + i_matches:
                detected_mods.append(m)

            for mod in detected_mods:
                if mod and not mod.startswith(".") and "/" not in mod:
                    builtins = {'fs', 'path', 'child_process', 'crypto', 'http', 'https', 'os', 'util', 'url', 'events', 'stream'}
                    if mod in builtins:
                        continue
                    
                    comment_match = re.search(r'//\s*(?:version:\s*|==|>=|@)?\s*([0-9a-zA-Z\.\-\+]+)', line, re.IGNORECASE)
                    if comment_match and comment_match.group(1):
                        ver = comment_match.group(1).strip()
                        if re.match(r'^[0-9]', ver):
                            detected.add(f"{mod}@{ver}")
                            continue
                        elif re.match(r'^[<>=~@\^]', ver):
                            clean_ver = ver[1:] if ver.startswith("@") else ver
                            detected.add(f"{mod}@{clean_ver}")
                            continue
                    detected.add(mod)

        # Filter duplicate Node packages
        final_detected = set()
        for dep in detected:
            if dep.startswith("@"):
                rest = dep[1:]
                actual_base_name = "@" + rest.split("@")[0] if "@" in rest else dep
            else:
                actual_base_name = dep.split("@")[0]

            has_versioned = False
            for other in detected:
                if other == dep:
                    continue
                if other.startswith("@"):
                    r = other[1:]
                    other_base = "@" + r.split("@")[0] if "@" in r else other
                else:
                    other_base = other.split("@")[0]
                if other_base == actual_base_name and other != other_base:
                    has_versioned = True
                    break

            if not has_versioned or dep != actual_base_name:
                final_detected.add(dep)

        if final_detected:
            needed_packages = list(final_detected)
            logger.info(f"Installing detected node dependencies: {needed_packages}")
            for pkg in needed_packages:
                cmd = ["npm", "install", pkg]
                logger.info(f"Running command: {' '.join(cmd)}")
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return needed_packages
        return []
    except Exception as e:
        logger.error(f"Error resolving node dependencies: {e}")
        return []

# Run script
def run_bot_script(bot_id):
    meta = load_metadata()
    bot_info = meta["bots"].get(bot_id)
    if not bot_info:
        return False, "Bot metadata not found."

    script_path = os.path.join(SCRIPTS_DIR, bot_info["filename"])
    log_path = os.path.join(LOGS_DIR, f"{bot_id}.log")

    if not os.path.exists(script_path):
        return False, "Script file does not exist."

    # If already running, return or stop the existing process to avoid 409 conflicts
    old_pid = bot_info.get("pid")
    if old_pid:
        try:
            if psutil.pid_exists(old_pid):
                logger.info(f"Terminating old process {old_pid} for bot {bot_id} to avoid collision...")
                stop_process(old_pid)
        except Exception as e:
            logger.warning(f"Error terminating process {old_pid}: {e}")
            
    if bot_id in active_processes:
        try:
            active_processes[bot_id].terminate()
        except Exception:
            pass
        del active_processes[bot_id]

    try:
        log_file = open(log_path, 'a', encoding='utf-8')
        log_file.write(f"\n--- Bot Started at {datetime.now().isoformat()} ---\n")
        log_file.flush()

        if bot_info["type"] == "python":
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=log_file,
                stderr=log_file,
                preexec_fn=os.setsid
            )
        else: # Node.js
            proc = subprocess.Popen(
                ["node", script_path],
                stdout=log_file,
                stderr=log_file,
                preexec_fn=os.setsid
            )

        active_processes[bot_id] = proc
        bot_info["status"] = "running"
        bot_info["pid"] = proc.pid
        bot_info["last_start"] = datetime.now().isoformat()
        save_metadata(meta)
        return True, "Bot started successfully."
    except Exception as e:
        logger.error(f"Failed to run bot {bot_id}: {e}")
        return False, f"Error starting bot: {str(e)}"

# Stop script
def stop_bot_script(bot_id):
    meta = load_metadata()
    bot_info = meta["bots"].get(bot_id)
    if not bot_info:
        return False, "Bot metadata not found."

    # Stop process
    stopped = False
    if bot_id in active_processes:
        proc = active_processes[bot_id]
        stopped = stop_process(proc.pid)
        del active_processes[bot_id]
    elif bot_info.get("pid"):
        stopped = stop_process(bot_info["pid"])

    bot_info["status"] = "stopped"
    bot_info["pid"] = None
    save_metadata(meta)
    return True, "Bot stopped successfully."

# Start all previously running bots on boot
def auto_start_bots():
    meta = load_metadata()
    count = 0
    for bot_id, info in meta["bots"].items():
        if info.get("status") == "running":
            success, _ = run_bot_script(bot_id)
            if success:
                count += 1
    logger.info(f"Auto-started {count} bots on boot.")

# Custom Main Keyboard
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    b1 = types.KeyboardButton("📁 Upload Script")
    b2 = types.KeyboardButton("📊 Bot Status")
    b3 = types.KeyboardButton("📋 View Logs")
    b4 = types.KeyboardButton("⚙️ Web Panel")
    markup.add(b1, b2, b3, b4)
    return markup

# Handler: /start
@bot.message_handler(commands=['start'])
def cmd_start(message):
    welcome_text = (
        "🤖 <b>Welcome to the Telegram Bot Manager!</b>\n\n"
        "This manager allows you to host and deploy other Python or Node.js Telegram bots directly from within Telegram.\n\n"
        "💡 <b>Available Actions:</b>\n"
        "• Click <b>📁 Upload Script</b> or simply upload any <code>.py</code> or <code>.js</code> file to deploy it.\n"
        "• Click <b>📊 Bot Status</b> to monitor and control your running bots.\n"
        "• Click <b>📋 View Logs</b> to view real-time log files.\n"
        "• Click <b>⚙️ Web Panel</b> to get your dedicated Web Control Dashboard link.\n\n"
        "Use commands: /start, /status, /stop, /delete, /logs, /panel"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_keyboard(), parse_mode="HTML")

# Handler: /panel or ⚙️ Web Panel
@bot.message_handler(commands=['panel'])
@bot.message_handler(func=lambda msg: msg.text == "⚙️ Web Panel")
def cmd_panel(message):
    app_url = os.environ.get("APP_URL", "http://0.0.0.0:3000")
    panel_text = (
        "⚙️ <b>Web Control Dashboard</b>\n\n"
        f"You can manage, upload, and monitor your bots from your dedicated web interface:\n"
        f"👉 <a href='{app_url}'>{app_url}</a>\n\n"
        "The web interface supports drag-and-drop file uploads, real-time log streaming, and process controls!"
    )
    bot.send_message(message.chat.id, panel_text, disable_web_page_preview=True, parse_mode="HTML")

# Handler: /status or 📊 Bot Status
@bot.message_handler(commands=['status'])
@bot.message_handler(func=lambda msg: msg.text == "📊 Bot Status")
def cmd_status(message):
    meta = load_metadata()
    bots = meta.get("bots", {})
    
    if not bots:
        bot.send_message(message.chat.id, "📭 <b>No bots deployed yet!</b> Upload a script file to get started.", parse_mode="HTML")
        return

    # Count statuses
    running_count = sum(1 for b in bots.values() if b.get("status") == "running")
    total_count = len(bots)

    status_text = f"📊 <b>Bot Manager Status:</b>\n"
    status_text += f"• Running Bots: <b>{running_count}</b> / {total_count}\n\n"
    status_text += "📂 <b>Deployed Bots:</b>\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for bot_id, info in bots.items():
        status_emoji = "🟢 RUNNING" if info.get("status") == "running" else "🔴 STOPPED"
        lang_emoji = "🐍" if info.get("type") == "python" else "📦"
        status_text += f"\n{lang_emoji} <b>{info['filename']}</b>\n"
        status_text += f"└ State: {status_emoji} | Created: {info.get('created_at', 'N/A')[:10]}\n"

        # Manage individual bots using inline buttons
        if info.get("status") == "running":
            btn_action = types.InlineKeyboardButton(text=f"🛑 Stop {info['filename']}", callback_data=f"stop_{bot_id}")
        else:
            btn_action = types.InlineKeyboardButton(text=f"▶️ Start {info['filename']}", callback_data=f"start_{bot_id}")
            
        btn_logs = types.InlineKeyboardButton(text=f"📋 Logs {info['filename']}", callback_data=f"logs_{bot_id}")
        btn_del = types.InlineKeyboardButton(text=f"🗑️ Delete {info['filename']}", callback_data=f"del_{bot_id}")
        
        # Add buttons side by side
        markup.row(btn_action)
        markup.row(btn_logs, btn_del)

    bot.send_message(message.chat.id, status_text, reply_markup=markup, parse_mode="HTML")

# Callback query handler for inline button controls
@bot.callback_query_handler(func=lambda call: True)
def callback_controls(call):
    action, bot_id = call.data.split('_', 1)
    meta = load_metadata()
    bot_info = meta["bots"].get(bot_id)

    if not bot_info:
        bot.answer_callback_query(call.id, "Bot not found in configuration.")
        return

    if action == "start":
        success, msg = run_bot_script(bot_id)
        bot.answer_callback_query(call.id, msg)
        # Refresh status message
        try:
            cmd_status(call.message)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
            
    elif action == "stop":
        success, msg = stop_bot_script(bot_id)
        bot.answer_callback_query(call.id, msg)
        # Refresh status message
        try:
            cmd_status(call.message)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif action == "logs":
        bot.answer_callback_query(call.id, "Retrieving logs...")
        send_bot_logs(call.message.chat.id, bot_id)

    elif action == "del":
        # Confirm delete or delete directly
        stop_bot_script(bot_id)
        script_path = os.path.join(SCRIPTS_DIR, bot_info["filename"])
        log_path = os.path.join(LOGS_DIR, f"{bot_id}.log")
        
        try:
            if os.path.exists(script_path):
                os.remove(script_path)
            if os.path.exists(log_path):
                os.remove(log_path)
        except Exception as e:
            logger.error(f"Error removing files for {bot_id}: {e}")

        # Update metadata
        meta = load_metadata()
        if bot_id in meta["bots"]:
            del meta["bots"][bot_id]
        save_metadata(meta)

        bot.answer_callback_query(call.id, f"Deleted {bot_info['filename']}")
        # Refresh status message
        try:
            cmd_status(call.message)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

# Helper to send logs to chat
def send_bot_logs(chat_id, bot_id):
    meta = load_metadata()
    bot_info = meta["bots"].get(bot_id)
    if not bot_info:
        bot.send_message(chat_id, "❌ Bot not found.")
        return

    log_path = os.path.join(LOGS_DIR, f"{bot_id}.log")
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        bot.send_message(chat_id, f"📋 <b>Logs for {bot_info['filename']}:</b>\n\n<i>No logs recorded yet.</i>", parse_mode="HTML")
        return

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            # Read last 25 lines
            lines = f.readlines()
            last_lines = lines[-25:]
            log_content = "".join(last_lines)
            
        bot.send_message(
            chat_id,
            f"📋 <b>Last 25 lines of logs for {bot_info['filename']}:</b>\n<pre>{log_content[-3500:]}</pre>",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to read logs: {e}")

# Handler: 📋 View Logs button or /logs command
@bot.message_handler(commands=['logs'])
@bot.message_handler(func=lambda msg: msg.text == "📋 View Logs")
def cmd_logs_selection(message):
    meta = load_metadata()
    bots = meta.get("bots", {})
    if not bots:
        bot.send_message(message.chat.id, "📭 <b>No bots deployed.</b> Please upload a script to view logs.", parse_mode="HTML")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for bot_id, info in bots.items():
        markup.add(types.InlineKeyboardButton(text=f"📋 Logs: {info['filename']}", callback_data=f"logs_{bot_id}"))
    
    bot.send_message(message.chat.id, "📋 <b>Select a bot to view its logs:</b>", reply_markup=markup, parse_mode="HTML")

# Handler: 📁 Upload Script button
@bot.message_handler(func=lambda msg: msg.text == "📁 Upload Script")
def cmd_upload_instruction(message):
    instruct = (
        "📁 <b>How to Upload & Deploy a Script:</b>\n\n"
        "1. Send your script file (<b>.py</b> or <b>.js</b>) directly to this chat.\n"
        "2. The manager will scan your script, download and install dependencies automatically.\n"
        "3. Once ready, it starts running in the background, and we will notify you!"
    )
    bot.send_message(message.chat.id, instruct, parse_mode="HTML")

# File receiver handler for uploads
@bot.message_handler(content_types=['document'])
def handle_uploaded_file(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        filename = message.document.file_name
        
        if not filename.endswith(('.py', '.js')):
            bot.send_message(
                message.chat.id, 
                "⚠️ <b>Unsupported File Type!</b> Please upload only Python (<code>.py</code>) or Node.js (<code>.js</code>) files.",
                parse_mode="HTML"
            )
            return

        bot.send_message(message.chat.id, f"📥 <b>Downloading {filename}...</b>", parse_mode="HTML")

        # Save downloaded script
        downloaded_file = bot.download_file(file_info.file_path)
        dest_path = os.path.join(SCRIPTS_DIR, filename)
        
        with open(dest_path, 'wb') as f:
            f.write(downloaded_file)

        bot_id = filename.replace(".", "_") # Simple unique ID from file name
        bot_type = "python" if filename.endswith(".py") else "node"

        # Check maximum deploy limit
        meta = load_metadata()
        meta["bots"] = meta.get("bots", {})
        exists = bot_id in meta["bots"]
        if not exists and len(meta["bots"]) >= 3:
            bot.send_message(
                message.chat.id,
                f"❌ <b>Maximum Deploy Limit Reached!</b>\nYou have already deployed {len(meta['bots'])}/3 bots. Please delete an existing bot to deploy a new one.",
                parse_mode="HTML"
            )
            try:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
            except Exception:
                pass
            return

        bot.send_message(message.chat.id, f"🔍 <b>Analyzing script imports & installing dependencies...</b>", parse_mode="HTML")

        # Automatically resolve and install dependencies
        dependencies = []
        if bot_type == "python":
            dependencies = install_python_deps(dest_path)
        else:
            dependencies = install_node_deps(dest_path)

        # Update bots list
        meta = load_metadata()
        meta["bots"][bot_id] = {
            "filename": filename,
            "type": bot_type,
            "status": "stopped",
            "dependencies": dependencies,
            "created_at": datetime.now().isoformat(),
            "pid": None,
            "last_start": None
        }
        save_metadata(meta)

        dep_str = ", ".join(dependencies) if dependencies else "None"
        bot.send_message(
            message.chat.id, 
            f"📦 <b>Dependencies Setup Complete!</b>\n• Installed: <code>{dep_str}</code>\n\n⚡ <b>Starting bot background execution...</b>",
            parse_mode="HTML"
        )

        # Run script
        success, run_msg = run_bot_script(bot_id)
        if success:
            bot.send_message(
                message.chat.id, 
                f"🚀 <b>Success!</b> Bot <code>{filename}</code> is now running in the background!\n\nUse <b>📊 Bot Status</b> to monitor it.",
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                message.chat.id, 
                f"❌ <b>Startup Warning:</b> Installed dependencies but failed to start bot script:\n<code>{run_msg}</code>",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Error handling upload: {e}")
        bot.send_message(message.chat.id, f"❌ <b>An error occurred during deployment:</b>\n<code>{str(e)}</code>", parse_mode="HTML")

# Slash Commands mapping to buttons or functions
@bot.message_handler(commands=['stop'])
def cmd_stop_command(message):
    # Parse bot name from argument if available
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "💡 <b>Usage:</b> /stop <code>&lt;bot_filename&gt;</code>", parse_mode="HTML")
        return
    bot_name = args[1].strip()
    bot_id = bot_name.replace(".", "_")
    success, msg = stop_bot_script(bot_id)
    bot.send_message(message.chat.id, f"🛑 <b>Stop action on {bot_name}:</b> {msg}", parse_mode="HTML")

@bot.message_handler(commands=['delete'])
def cmd_delete_command(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "💡 <b>Usage:</b> /delete <code>&lt;bot_filename&gt;</code>", parse_mode="HTML")
        return
    bot_name = args[1].strip()
    bot_id = bot_name.replace(".", "_")
    
    meta = load_metadata()
    if bot_id not in meta["bots"]:
        bot.send_message(message.chat.id, f"❌ Bot <b>{bot_name}</b> not found.", parse_mode="HTML")
        return

    stop_bot_script(bot_id)
    script_path = os.path.join(SCRIPTS_DIR, bot_name)
    log_path = os.path.join(LOGS_DIR, f"{bot_id}.log")
    try:
        if os.path.exists(script_path):
            os.remove(script_path)
        if os.path.exists(log_path):
            os.remove(log_path)
    except Exception as e:
        logger.error(f"Error deleting files: {e}")

    meta = load_metadata()
    if bot_id in meta["bots"]:
        del meta["bots"][bot_id]
    save_metadata(meta)

    bot.send_message(message.chat.id, f"🗑️ Bot <b>{bot_name}</b> has been deleted successfully.", parse_mode="HTML")

# Non-blocking Polling Loop
def start_bot_polling():
    auto_start_bots()
    logger.info("Bot Polling loop started...")
    
    try:
        logger.info("Removing any existing webhooks to ensure clean polling...")
        bot.remove_webhook()
    except Exception as e:
        logger.warning(f"Could not remove webhook: {e}")
        
    offset = 0
    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=20, allowed_updates=None)
            if updates:
                offset = updates[-1].update_id + 1
                bot.process_new_updates(updates)
            time.sleep(1)
        except ApiTelegramException as e:
            if e.error_code == 409:
                logger.warning(
                    "⚠️ [Conflict Alert] Another instance of this Telegram Bot is currently running "
                    "(e.g., the Shared/Pre-production App container or another active deployment). "
                    "To prevent an aggressive polling connection loop war, this instance will pause for 45 seconds."
                )
                time.sleep(45)
            else:
                logger.error(f"Telegram API Exception: {e}")
                time.sleep(5)
        except Exception as e:
            logger.error(f"Bot Polling connection error: {e}")
            time.sleep(5) # Delay before retry

# Graceful shutdown handler
def graceful_shutdown(signum, frame):
    logger.info(f"Shutdown signal {signum} received. Gracefully cleaning up active child bot processes...")
    # Make a copy of keys to avoid modification during iteration
    for bot_id in list(active_processes.keys()):
        try:
            logger.info(f"Stopping bot {bot_id} during manager shutdown...")
            stop_bot_script(bot_id)
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id} on shutdown: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

if __name__ == "__main__":
    start_bot_polling()
