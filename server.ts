import express from "express";
import path from "path";
import fs from "fs";
import { spawn, ChildProcess, execSync } from "child_process";
import { createServer as createViteServer } from "vite";
import multer from "multer";

const app = express();
const PORT = 3000;

// Directories
const DEPLOY_DIR = path.resolve("./deployed_bots");
const SCRIPTS_DIR = path.join(DEPLOY_DIR, "scripts");
const LOGS_DIR = path.join(DEPLOY_DIR, "logs");
const METADATA_FILE = path.join(DEPLOY_DIR, "bots_metadata.json");
const MANAGER_LOG = path.resolve("manager.log");

// Ensure directories exist
if (!fs.existsSync(DEPLOY_DIR)) fs.mkdirSync(DEPLOY_DIR, { recursive: true });
if (!fs.existsSync(SCRIPTS_DIR)) fs.mkdirSync(SCRIPTS_DIR, { recursive: true });
if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });
if (!fs.existsSync(METADATA_FILE)) {
  fs.writeFileSync(METADATA_FILE, JSON.stringify({ bots: {} }, null, 2), "utf-8");
}

app.use(express.json());

// Setup Multer for script uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, SCRIPTS_DIR);
  },
  filename: (req, file, cb) => {
    cb(null, file.originalname);
  }
});
const upload = multer({ storage });

// Global Reference to Python Telegram Bot Manager process
let managerProcess: ChildProcess | null = null;
let managerStatus: "running" | "stopped" = "stopped";
let managerPid: number | null = null;

// Helper to check if PID is alive
function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// Start Main Manager Bot Process
function startManagerBot() {
  if (managerProcess && managerProcess.pid && isPidAlive(managerProcess.pid)) {
    console.log(`Manager Bot already running on PID ${managerProcess.pid}`);
    return;
  }

  console.log("Cleaning up any previous manager bot processes...");
  try {
    // Kill any pre-existing instances of python.py before spawning to avoid 409 conflict
    execSync("pkill -9 -f 'python3 python.py' || true");
    // Give OS a half-second to free up the socket/port/connection
    execSync("sleep 0.5 || true");
  } catch (err) {
    console.error("Failed cleaning up old processes:", err);
  }

  console.log("Starting Main Manager Telegram Bot (python.py)...");
  
  const logStream = fs.createWriteStream(MANAGER_LOG, { flags: "w" });
  logStream.write(`\n--- Server starting manager bot at ${new Date().toISOString()} ---\n`);

  managerProcess = spawn("python3", ["python.py"], {
    cwd: process.cwd(),
    detached: true,
    stdio: ["ignore", "pipe", "pipe"]
  });

  managerStatus = "running";
  managerPid = managerProcess.pid || null;

  if (managerProcess.stdout) {
    managerProcess.stdout.pipe(logStream);
    managerProcess.stdout.on("data", (data) => console.log(`[Bot Manager]: ${data.toString().trim()}`));
  }
  if (managerProcess.stderr) {
    managerProcess.stderr.pipe(logStream);
    managerProcess.stderr.on("data", (data) => console.error(`[Bot Manager Error]: ${data.toString().trim()}`));
  }

  managerProcess.on("exit", (code, signal) => {
    console.log(`Manager Bot process exited with code ${code} and signal ${signal}`);
    managerStatus = "stopped";
    managerPid = null;
    managerProcess = null;
    
    // Auto restart if stopped unexpectedly
    setTimeout(() => {
      console.log("Auto-restarting Bot Manager...");
      startManagerBot();
    }, 5000);
  });
}

// Stop Main Manager Bot Process
function stopManagerBot() {
  if (managerProcess && managerProcess.pid) {
    try {
      if (managerProcess.pid) {
        process.kill(-managerProcess.pid, "SIGTERM");
      }
    } catch {
      try {
        if (managerProcess.pid) {
          process.kill(managerProcess.pid, "SIGTERM");
        }
      } catch (err) {
        console.error("Failed to terminate manager bot process:", err);
      }
    }
    managerStatus = "stopped";
    managerPid = null;
    managerProcess = null;
  }
}

// Start Manager Bot on server startup
startManagerBot();

// Read Metadata
function readMetadata() {
  try {
    if (!fs.existsSync(METADATA_FILE)) {
      return { bots: {} };
    }
    const raw = fs.readFileSync(METADATA_FILE, "utf-8");
    return JSON.parse(raw);
  } catch (err) {
    console.error("Error reading metadata:", err);
    return { bots: {} };
  }
}

// Write Metadata
function writeMetadata(data: any) {
  try {
    fs.writeFileSync(METADATA_FILE, JSON.stringify(data, null, 2), "utf-8");
  } catch (err) {
    console.error("Error writing metadata:", err);
  }
}

// Dependency scan & installer
function detectAndInstallDeps(filePath: string, type: "python" | "node") {
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    const stdLibs = new Set([
      'os', 'sys', 're', 'json', 'subprocess', 'time', 'threading', 'math', 'random',
      'datetime', 'collections', 'urllib', 'http', 'socket', 'shutil', 'asyncio', 'logging',
      'hashlib', 'uuid', 'base64', 'csv', 'tempfile', 'argparse', 'typing', 'traceback',
      'pathlib', 'functools', 'itertools', 'select', 'signal', 'struct', 'platform'
    ]);

    const importMapping: Record<string, string> = {
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
    };

    const detected = new Set<string>();

    if (type === "python") {
      // 1. Standard PEP 723 parsing (e.g. within `# /// script` metadata block)
      const pep723Match = content.match(/#\s*\/\/\/\s*script[\s\S]*?#\s*\/\/\/\s*/);
      if (pep723Match) {
        const block = pep723Match[0];
        const depLines = block.match(/["']([a-zA-Z0-9_\-\[\]]+(?:[<>=!~]+[a-zA-Z0-9_\-\.]+)??)["']/g);
        if (depLines) {
          depLines.forEach(depLine => {
            const dep = depLine.replace(/['"]/g, "").trim();
            if (dep && !dep.startsWith("/") && !dep.startsWith(".")) {
              const prefixMatch = dep.match(/^([a-zA-Z0-9_\-]+)/);
              if (prefixMatch) {
                const prefix = prefixMatch[1];
                const mapped = importMapping[prefix] || prefix;
                detected.add(dep.replace(prefix, mapped));
              } else {
                detected.add(dep);
              }
            }
          });
        }
      }

      // 2. Head requirement parsing (e.g. `# pip: requests==2.31.0` or `# requirements: numpy>=1.2.0`)
      const pipHeaderMatch = content.match(/#\s*(?:pip|requirements|dependencies):\s*([^\r\n]+)/i);
      if (pipHeaderMatch && pipHeaderMatch[1]) {
        const reqs = pipHeaderMatch[1].split(",");
        reqs.forEach(r => {
          const dep = r.trim();
          if (dep) {
            const prefixMatch = dep.match(/^([a-zA-Z0-9_\-]+)/);
            if (prefixMatch) {
              const prefix = prefixMatch[1];
              const mapped = importMapping[prefix] || prefix;
              detected.add(dep.replace(prefix, mapped));
            } else {
              detected.add(dep);
            }
          }
        });
      }

      // 3. Line-by-line scanning & inline comment constraints (e.g. `import requests # version: 2.31.0`)
      const lines = content.split("\n");
      lines.forEach(line => {
        const importMatch = line.match(/^\s*(?:import\s+([a-zA-Z0-9_,\s]+)|from\s+([a-zA-Z0-9_]+)\s+import)/);
        if (importMatch) {
          const rawMods: string[] = [];
          if (importMatch[1]) {
            importMatch[1].split(",").forEach(m => {
              rawMods.push(m.trim().split(".")[0]);
            });
          } else if (importMatch[2]) {
            rawMods.push(importMatch[2].trim().split(".")[0]);
          }

          rawMods.forEach(rawMod => {
            const mod = rawMod.trim();
            if (mod && !stdLibs.has(mod)) {
              const mapped = importMapping[mod] || mod;
              const commentMatch = line.match(/#\s*(?:version:\s*|==|>=|@)?\s*([0-9a-zA-Z\.\-\+]+)/i);
              if (commentMatch && commentMatch[1]) {
                const ver = commentMatch[1].trim();
                if (/^[0-9]/.test(ver)) {
                  detected.add(`${mapped}==${ver}`);
                  return;
                } else if (/^[<>=~]/.test(ver)) {
                  detected.add(`${mapped}${ver}`);
                  return;
                }
              }
              detected.add(mapped);
            }
          });
        }
      });

      // Filter duplicates: keep versioned ones if both unversioned and versioned exist
      const finalDetected = new Set<string>();
      detected.forEach(dep => {
        const baseName = dep.split(/[<>=!~@]/)[0].trim();
        const hasVersioned = Array.from(detected).some(other => 
          other !== dep && 
          other.startsWith(baseName) && 
          (other.includes("=") || other.includes(">") || other.includes("<") || other.includes("~"))
        );
        if (!hasVersioned || dep !== baseName) {
          finalDetected.add(dep);
        }
      });

      if (finalDetected.size > 0) {
        const pkgs = Array.from(finalDetected);
        console.log(`Node server installing python packages with specific versions: ${pkgs}`);
        pkgs.forEach(pkg => {
          spawn("pip3", ["install", "--break-system-packages", pkg]);
        });
        return pkgs;
      }
    } else {
      // 1. Comment header parsing (e.g. `// npm: express@4.18.2, lodash@4.17.21`)
      const npmHeaderMatch = content.match(/\/\/\s*(?:npm|dependencies):\s*([^\r\n]+)/i);
      if (npmHeaderMatch && npmHeaderMatch[1]) {
        const reqs = npmHeaderMatch[1].split(",");
        reqs.forEach(r => {
          const dep = r.trim();
          if (dep) {
            detected.add(dep);
          }
        });
      }

      // 2. Line-by-line scanning & inline comment constraints (e.g. `import express from 'express' // @4.18.2`)
      const lines = content.split("\n");
      lines.forEach(line => {
        const detectedMods: string[] = [];
        
        // Find all require('...') matches
        const rMatches = line.matchAll(/require\([\'"]([^\'"]+)[\'"]\)/g);
        for (const match of rMatches) {
          if (match[1]) detectedMods.push(match[1]);
        }

        // Find all from '...' matches
        const iMatches = line.matchAll(/from\s+[\'"]([^\'"]+)[\'"]/g);
        for (const match of iMatches) {
          if (match[1]) detectedMods.push(match[1]);
        }

        detectedMods.forEach(mod => {
          if (mod && !mod.startsWith(".") && !mod.includes("/") && !['fs', 'path', 'child_process', 'crypto', 'http', 'https', 'os', 'util', 'url', 'events', 'stream'].includes(mod)) {
            const commentMatch = line.match(/\/\/\s*(?:version:\s*|==|>=|@)?\s*([0-9a-zA-Z\.\-\+]+)/i);
            if (commentMatch && commentMatch[1]) {
              const ver = commentMatch[1].trim();
              if (/^[0-9]/.test(ver)) {
                detected.add(`${mod}@${ver}`);
                return;
              } else if (/^[<>=~@\^]/.test(ver)) {
                const cleanVer = ver.startsWith("@") ? ver.slice(1) : ver;
                detected.add(`${mod}@${cleanVer}`);
                return;
              }
            }
            detected.add(mod);
          }
        });
      });

      // Filter duplicate Node packages
      const finalDetected = new Set<string>();
      detected.forEach(dep => {
        let actualBaseName = dep;
        if (dep.startsWith("@")) {
          const rest = dep.slice(1);
          if (rest.includes("@")) {
            actualBaseName = "@" + rest.split("@")[0];
          }
        } else {
          actualBaseName = dep.split("@")[0];
        }

        const hasVersioned = Array.from(detected).some(other => {
          if (other === dep) return false;
          let otherBase = other;
          if (other.startsWith("@")) {
            const r = other.slice(1);
            if (r.includes("@")) otherBase = "@" + r.split("@")[0];
          } else {
            otherBase = other.split("@")[0];
          }
          return otherBase === actualBaseName && other !== otherBase;
        });

        if (!hasVersioned || dep !== actualBaseName) {
          finalDetected.add(dep);
        }
      });

      if (finalDetected.size > 0) {
        const pkgs = Array.from(finalDetected);
        console.log(`Node server installing NPM packages with specific versions: ${pkgs}`);
        pkgs.forEach(pkg => {
          spawn("npm", ["install", pkg]);
        });
        return pkgs;
      }
    }
    return [];
  } catch (err) {
    console.error("Error detecting/installing dependencies:", err);
    return [];
  }
}

// Express REST APIs
app.get("/api/status", (req, res) => {
  const meta = readMetadata();
  const bots = meta.bots || {};
  
  // Refresh actual alive states from OS
  let runningCount = 0;
  Object.keys(bots).forEach(botId => {
    const info = bots[botId];
    if (info.status === "running" && info.pid) {
      if (!isPidAlive(info.pid)) {
        info.status = "stopped";
        info.pid = null;
      } else {
        runningCount++;
      }
    }
  });
  writeMetadata(meta);

  // System stats (approx)
  const stats = {
    uptime: Math.floor(process.uptime()),
    memory: process.memoryUsage().heapUsed,
    platform: process.platform,
    nodeVersion: process.version,
    pythonInstalled: true
  };

  res.json({
    manager: {
      status: managerStatus,
      pid: managerPid,
      token: "8923444398:AAF68GO0jb3_1ofreVAnMF7APcfdoIY0_K4"
    },
    bots,
    runningCount,
    totalCount: Object.keys(bots).length,
    stats
  });
});

// Control Manager Bot
app.post("/api/manager/control", (req, res) => {
  const { action } = req.body;
  if (action === "start") {
    startManagerBot();
    res.json({ success: true, message: "Manager Bot started." });
  } else if (action === "stop") {
    stopManagerBot();
    res.json({ success: true, message: "Manager Bot stopped." });
  } else if (action === "restart") {
    stopManagerBot();
    setTimeout(() => {
      startManagerBot();
      res.json({ success: true, message: "Manager Bot restarted." });
    }, 1000);
  } else {
    res.status(400).json({ error: "Invalid action" });
  }
});

// Control Deployed Bots
app.post("/api/bots/control", (req, res) => {
  const { botId, action } = req.body;
  const meta = readMetadata();
  const botInfo = meta.bots?.[botId];

  if (!botInfo) {
    return res.status(404).json({ error: "Bot not found" });
  }

  const scriptPath = path.join(SCRIPTS_DIR, botInfo.filename);
  const logPath = path.join(LOGS_DIR, `${botId}.log`);

  if (action === "start") {
    // If already running
    if (botInfo.pid && isPidAlive(botInfo.pid)) {
      return res.json({ success: true, message: "Bot is already running." });
    }

    try {
      const logStream = fs.createWriteStream(logPath, { flags: "a" });
      logStream.write(`\n--- Bot started by Web Panel at ${new Date().toISOString()} ---\n`);

      let child: ChildProcess;
      if (botInfo.type === "python") {
        child = spawn("python3", [scriptPath], {
          detached: true,
          stdio: ["ignore", "pipe", "pipe"]
        });
      } else {
        child = spawn("node", [scriptPath], {
          detached: true,
          stdio: ["ignore", "pipe", "pipe"]
        });
      }

      if (child.stdout) child.stdout.pipe(logStream);
      if (child.stderr) child.stderr.pipe(logStream);

      botInfo.status = "running";
      botInfo.pid = child.pid || null;
      botInfo.last_start = new Date().toISOString();
      writeMetadata(meta);

      // Listen for exit to update status
      child.on("exit", () => {
        const currentMeta = readMetadata();
        if (currentMeta.bots?.[botId]) {
          currentMeta.bots[botId].status = "stopped";
          currentMeta.bots[botId].pid = null;
          writeMetadata(currentMeta);
        }
      });

      res.json({ success: true, message: "Bot started." });
    } catch (err: any) {
      res.status(500).json({ error: `Failed to start: ${err.message}` });
    }
  } else if (action === "stop") {
    if (botInfo.pid) {
      try {
        process.kill(-botInfo.pid, "SIGTERM");
      } catch {
        try {
          process.kill(botInfo.pid, "SIGTERM");
        } catch {}
      }
    }
    botInfo.status = "stopped";
    botInfo.pid = null;
    writeMetadata(meta);
    res.json({ success: true, message: "Bot stopped." });
  } else if (action === "delete") {
    // Stop if running
    if (botInfo.pid) {
      try {
        process.kill(-botInfo.pid, "SIGTERM");
      } catch {
        try {
          process.kill(botInfo.pid, "SIGTERM");
        } catch {}
      }
    }

    // Delete files
    try {
      if (fs.existsSync(scriptPath)) fs.unlinkSync(scriptPath);
      if (fs.existsSync(logPath)) fs.unlinkSync(logPath);
    } catch (err) {
      console.error("Error deleting files:", err);
    }

    // Remove from metadata
    delete meta.bots[botId];
    writeMetadata(meta);
    res.json({ success: true, message: "Bot deleted." });
  } else {
    res.status(400).json({ error: "Invalid action" });
  }
});

// Get logs
app.get("/api/logs/manager", (req, res) => {
  try {
    if (!fs.existsSync(MANAGER_LOG)) {
      return res.send("No logs recorded yet.");
    }
    const lines = fs.readFileSync(MANAGER_LOG, "utf-8").split("\n");
    const lastLines = lines.slice(-100).join("\n");
    res.send(lastLines);
  } catch (err: any) {
    res.status(500).send(`Error reading logs: ${err.message}`);
  }
});

app.get("/api/logs/bot/:id", (req, res) => {
  const logPath = path.join(LOGS_DIR, `${req.params.id}.log`);
  try {
    if (!fs.existsSync(logPath)) {
      return res.send("No logs recorded yet.");
    }
    const lines = fs.readFileSync(logPath, "utf-8").split("\n");
    const lastLines = lines.slice(-100).join("\n");
    res.send(lastLines);
  } catch (err: any) {
    res.status(500).send(`Error reading logs: ${err.message}`);
  }
});

// Upload Script API
app.post("/api/upload", upload.single("file"), (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: "No file uploaded." });
  }

  const filename = req.file.originalname;
  const botId = filename.replace(/\./g, "_");
  const type = filename.endsWith(".py") ? "python" : "node";
  const filePath = path.join(SCRIPTS_DIR, filename);

  const meta = readMetadata();
  meta.bots = meta.bots || {};
  const exists = !!meta.bots[botId];
  if (!exists && Object.keys(meta.bots).length >= 3) {
    if (fs.existsSync(filePath)) {
      try {
        fs.unlinkSync(filePath);
      } catch {}
    }
    return res.status(400).json({ error: "Maximum deploy limit reached. You can deploy a total of up to 3 bots. Please delete an existing bot to upload a new one." });
  }

  const dependencies = detectAndInstallDeps(filePath, type);

  meta.bots[botId] = {
    filename,
    type,
    status: "stopped",
    dependencies,
    created_at: new Date().toISOString(),
    pid: null,
    last_start: null
  };
  writeMetadata(meta);

  res.json({
    success: true,
    message: "Script uploaded and scheduled.",
    bot: meta.bots[botId]
  });
});

// Serve frontend assets
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://0.0.0.0:${PORT}`);
  });
}

// Clean up child process on exit
process.on("SIGINT", () => {
  console.log("Shutting down gracefully...");
  stopManagerBot();
  process.exit(0);
});

process.on("SIGTERM", () => {
  console.log("Shutting down gracefully...");
  stopManagerBot();
  process.exit(0);
});

startServer();
