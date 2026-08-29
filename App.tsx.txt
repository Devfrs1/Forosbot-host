import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import { 
  Bot, 
  Terminal, 
  Upload, 
  Play, 
  Square, 
  Trash2, 
  RefreshCw, 
  CheckCircle, 
  AlertCircle, 
  Server, 
  Cpu, 
  Clock, 
  ExternalLink,
  Copy,
  Check,
  FileCode,
  Layers
} from "lucide-react";

interface DeployedBot {
  filename: string;
  type: "python" | "node";
  status: "running" | "stopped";
  dependencies: string[];
  created_at: string;
  pid: number | null;
  last_start: string | null;
}

interface ServerStatus {
  manager: {
    status: "running" | "stopped";
    pid: number | null;
    token: string;
  };
  bots: Record<string, DeployedBot>;
  runningCount: number;
  totalCount: number;
  stats: {
    uptime: number;
    memory: number;
    platform: string;
    nodeVersion: string;
    pythonInstalled: boolean;
  };
}

export default function App() {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [selectedLogSource, setSelectedLogSource] = useState<string>("manager");
  const [logs, setLogs] = useState<string>("");
  const [isCopied, setIsCopied] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [isOffline, setIsOffline] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Fetch bot manager and system status
  const fetchStatus = async () => {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setIsOffline(false);
      } else {
        setIsOffline(true);
      }
    } catch (err) {
      setIsOffline(true);
    }
  };

  // Fetch logs based on selection
  const fetchLogs = async () => {
    try {
      const url = selectedLogSource === "manager" 
        ? "/api/logs/manager" 
        : `/api/logs/bot/${selectedLogSource}`;
      const res = await fetch(url);
      if (res.ok) {
        const text = await res.text();
        setLogs(text || "No logs available.");
        setIsOffline(false);
      } else {
        setIsOffline(true);
      }
    } catch (err) {
      setIsOffline(true);
    }
  };

  // Initialize and poll
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 2000);
    return () => clearInterval(interval);
  }, [selectedLogSource]);

  // Scroll terminal to bottom
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, autoScroll]);

  // Copy bot token helper
  const handleCopyToken = () => {
    if (status?.manager.token) {
      navigator.clipboard.writeText(status.manager.token);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    }
  };

  // Control Main Manager Process
  const handleManagerControl = async (action: "start" | "stop" | "restart") => {
    try {
      const res = await fetch("/api/manager/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      if (res.ok) {
        fetchStatus();
      }
    } catch (err) {
      console.error("Error controlling manager bot:", err);
    }
  };

  // Control Deployed Bots
  const handleBotControl = async (botId: string, action: "start" | "stop" | "delete") => {
    try {
      const res = await fetch("/api/bots/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ botId, action })
      });
      if (res.ok) {
        fetchStatus();
        if (action === "delete" && selectedLogSource === botId) {
          setSelectedLogSource("manager");
        }
      }
    } catch (err) {
      console.error(`Error performing ${action} on bot ${botId}:`, err);
    }
  };

  // Handle Drag & Drop Upload
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!file.name.endsWith(".py") && !file.name.endsWith(".js")) {
      setUploadError("Invalid file type. Please upload only Python (.py) or Node.js (.js) scripts.");
      setUploadSuccess(null);
      return;
    }

    const botId = file.name.replace(/\./g, "_");
    const exists = status?.bots && !!status.bots[botId];
    if (!exists && status && status.totalCount >= 3) {
      setUploadError("Maximum deployment limit reached! You can deploy a total of up to 3 bots. Please delete an existing bot to upload a new one.");
      setUploadSuccess(null);
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    setUploadProgress(10);

    const formData = new FormData();
    formData.append("file", file);

    try {
      // Simulate progressive bar setup
      const interval = setInterval(() => {
        setUploadProgress(prev => (prev < 90 ? prev + 15 : prev));
      }, 200);

      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });

      clearInterval(interval);
      setUploadProgress(100);

      if (res.ok) {
        const data = await res.json();
        setUploadSuccess(`Successfully deployed ${file.name}! Python setup and automatic dependency scan completed.`);
        fetchStatus();
      } else {
        const errorData = await res.json();
        setUploadError(errorData.error || "Failed to deploy script.");
      }
    } catch (err) {
      setUploadError("Network error occurred during deployment.");
    } finally {
      setTimeout(() => {
        setIsUploading(false);
        setUploadProgress(0);
      }, 1500);
    }
  };

  // Human uptime formatting
  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / (3600 * 24));
    const h = Math.floor((seconds % (3600 * 24)) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    const parts = [];
    if (d > 0) parts.push(`${d}d`);
    if (h > 0) parts.push(`${h}h`);
    if (m > 0) parts.push(`${m}m`);
    parts.push(`${s}s`);
    return parts.join(" ");
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col font-sans" id="app_container">
      {/* Offline/Reconnecting Alert Banner */}
      <AnimatePresence>
        {isOffline && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="bg-amber-500 text-white font-medium text-xs px-6 py-2.5 flex items-center justify-center gap-2 shadow-inner select-none overflow-hidden"
            id="offline_banner"
          >
            <AlertCircle size={15} className="animate-spin" />
            <span>Connecting to the backend server... Status and log updates will resume shortly.</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Top Banner & Header */}
      <header className="bg-white border-b border-slate-200/80 px-6 py-4 shadow-sm" id="main_header">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-600 text-white rounded-xl shadow-md" id="app_logo">
              <Bot size={28} className="animate-pulse" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">Telegram Bot Deployer</h1>
              <p className="text-sm text-slate-500 mt-0.5">Self-hosting manager and dependency auto-installer for Telegram bots</p>
            </div>
          </div>

          {/* Bot Manager Connection Status */}
          <div className="flex items-center gap-3 bg-slate-50 border border-slate-200 p-3 rounded-2xl" id="manager_status_card">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400">Telegram Manager Bot</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`h-2.5 w-2.5 rounded-full ${status?.manager.status === "running" ? "bg-emerald-500" : "bg-rose-500"}`}></span>
                <span className="text-sm font-semibold text-slate-700 capitalize">{status?.manager.status || "Checking..."}</span>
              </div>
            </div>
            <div className="h-8 w-[1px] bg-slate-200"></div>
            <div className="flex gap-1.5">
              {status?.manager.status === "running" ? (
                <button 
                  onClick={() => handleManagerControl("stop")} 
                  className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 rounded-lg text-xs font-medium transition-colors flex items-center gap-1"
                  title="Stop Bot Manager"
                  id="btn_stop_manager"
                >
                  <Square size={13} fill="currentColor" /> Stop
                </button>
              ) : (
                <button 
                  onClick={() => handleManagerControl("start")} 
                  className="px-3 py-1.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-600 rounded-lg text-xs font-medium transition-colors flex items-center gap-1"
                  title="Start Bot Manager"
                  id="btn_start_manager"
                >
                  <Play size={13} fill="currentColor" /> Start
                </button>
              )}
              <button 
                onClick={() => handleManagerControl("restart")} 
                className="p-1.5 hover:bg-slate-200 text-slate-500 rounded-lg transition-colors"
                title="Restart Bot Manager"
                id="btn_restart_manager"
              >
                <RefreshCw size={14} />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6" id="main_content">
        {/* Statistics and System Overview Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" id="stats_row">
          <div className="bg-white border border-slate-200/80 p-5 rounded-2xl flex items-center gap-4 shadow-sm" id="stat_running">
            <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl">
              <Bot size={22} />
            </div>
            <div>
              <span className="text-xs text-slate-400 font-medium block">Running Bots</span>
              <span className="text-2xl font-bold text-slate-800">{status?.runningCount ?? 0}</span>
              <span className="text-[10px] text-slate-400 block mt-0.5">active sub-processes</span>
            </div>
          </div>

          <div className="bg-white border border-slate-200/80 p-5 rounded-2xl flex items-center gap-4 shadow-sm" id="stat_total">
            <div className={`p-3 rounded-xl ${(status?.totalCount ?? 0) >= 3 ? "bg-amber-50 text-amber-600 animate-pulse" : "bg-indigo-50 text-indigo-600"}`}>
              <Layers size={22} />
            </div>
            <div>
              <span className="text-xs text-slate-400 font-medium block">Total Deployed</span>
              <span className="text-2xl font-bold text-slate-800">
                {status?.totalCount ?? 0}
                <span className="text-xs font-normal text-slate-400 ml-1.5">/ 3 limit</span>
              </span>
              <span className="text-[10px] text-slate-400 block mt-0.5">uploaded scripts</span>
            </div>
          </div>

          <div className="bg-white border border-slate-200/80 p-5 rounded-2xl flex items-center gap-4 shadow-sm" id="stat_uptime">
            <div className="p-3 bg-amber-50 text-amber-600 rounded-xl">
              <Clock size={22} />
            </div>
            <div>
              <span className="text-xs text-slate-400 font-medium block">Server Uptime</span>
              <span className="text-xl font-bold text-slate-800 truncate block max-w-[150px]">
                {status ? formatUptime(status.stats.uptime) : "0s"}
              </span>
              <span className="text-[10px] text-slate-400 block mt-0.5">continuous hosting</span>
            </div>
          </div>

          <div className="bg-white border border-slate-200/80 p-5 rounded-2xl flex items-center gap-4 shadow-sm" id="stat_memory">
            <div className="p-3 bg-rose-50 text-rose-600 rounded-xl">
              <Server size={22} />
            </div>
            <div>
              <span className="text-xs text-slate-400 font-medium block">Memory Usage</span>
              <span className="text-2xl font-bold text-slate-800">
                {status ? `${(status.stats.memory / 1024 / 1024).toFixed(1)} MB` : "0 MB"}
              </span>
              <span className="text-[10px] text-slate-400 block mt-0.5">Node process stack</span>
            </div>
          </div>
        </div>

        {/* Token and Integration Panel */}
        <div className="bg-white border border-slate-200/80 p-5 rounded-2xl shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4" id="token_banner">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-50 border border-slate-200 text-slate-500 rounded-lg">
              <Cpu size={18} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800">Manager Bot Token</h3>
              <p className="text-xs text-slate-400">Use this token to connect or talk to your master bot in Telegram</p>
            </div>
          </div>
          <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 px-3 py-2 rounded-xl flex-1 max-w-lg">
            <code className="text-xs font-mono text-slate-600 truncate select-all flex-1">
              8923444398:AAF68GO0jb3_1ofreVAnMF7APcfdoIY0_K4
            </code>
            <button 
              onClick={handleCopyToken}
              className="p-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-slate-700 rounded-lg transition-colors flex items-center"
              title="Copy Token"
            >
              {isCopied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
            </button>
          </div>
          <a 
            href="https://t.me/BotFather" 
            target="_blank" 
            referrerPolicy="no-referrer"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 shadow-sm"
          >
            Open Telegram <ExternalLink size={12} />
          </a>
        </div>

        {/* Dashboard Split Screen */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6" id="dashboard_body">
          
          {/* LEFT: Deployment Uplader and Bot List */}
          <div className="lg:col-span-7 flex flex-col gap-6" id="left_column">
            
            {/* Uplader Box */}
            <div 
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`bg-white border-2 border-dashed rounded-2xl p-6 text-center transition-all cursor-pointer relative overflow-hidden shadow-sm ${
                isDragOver ? "border-indigo-500 bg-indigo-50/20" : "border-slate-200 hover:border-indigo-400"
              }`}
              onClick={() => fileInputRef.current?.click()}
              id="upload_box"
            >
              <input 
                type="file" 
                ref={fileInputRef} 
                onChange={handleFileSelect} 
                accept=".py,.js" 
                className="hidden" 
              />
              <div className="flex flex-col items-center gap-2">
                <div className={`p-4 rounded-full ${isDragOver ? "bg-indigo-100 text-indigo-600" : "bg-slate-50 text-slate-400"} transition-colors`}>
                  <Upload size={28} />
                </div>
                <h3 className="font-semibold text-slate-800 text-sm">Deploy New Telegram Bot Script</h3>
                <p className="text-xs text-slate-400 max-w-sm mx-auto">
                  Drag and drop your <span className="font-medium text-slate-600">.py (Python)</span> or <span className="font-medium text-slate-600">.js (Node.js)</span> files here, or click to browse.
                </p>
                <span className="text-[10px] text-indigo-500 bg-indigo-50 px-2.5 py-1 rounded-full font-medium mt-1">
                  Automatic dependency resolver & installer enabled
                </span>
              </div>

              {/* Progress and status notifications */}
              <AnimatePresence>
                {isUploading && (
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-0 bg-white/95 flex flex-col items-center justify-center p-6"
                  >
                    <RefreshCw className="animate-spin text-indigo-600 mb-3" size={32} />
                    <span className="text-xs font-semibold text-slate-700">Analyzing Script Dependencies...</span>
                    <div className="w-full max-w-xs bg-slate-100 rounded-full h-1.5 mt-2 overflow-hidden">
                      <div 
                        className="bg-indigo-600 h-1.5 rounded-full transition-all duration-300" 
                        style={{ width: `${uploadProgress}%` }}
                      ></div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Notifications panel */}
            {(uploadError || uploadSuccess) && (
              <motion.div 
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`p-4 rounded-xl border flex gap-3 ${
                  uploadError ? "bg-rose-50 border-rose-100 text-rose-700" : "bg-emerald-50 border-emerald-100 text-emerald-700"
                }`}
                id="upload_feedback_panel"
              >
                {uploadError ? <AlertCircle size={18} className="shrink-0" /> : <CheckCircle size={18} className="shrink-0" />}
                <div className="text-xs">
                  <p className="font-semibold">{uploadError ? "Deployment Error" : "Deployment Successful"}</p>
                  <p className="mt-0.5 opacity-90">{uploadError || uploadSuccess}</p>
                </div>
              </motion.div>
            )}

            {/* Deployed Bot List */}
            <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden flex flex-col flex-1" id="bots_list_card">
              <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="p-1.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-500">
                    <Bot size={16} />
                  </span>
                  <h2 className="text-sm font-semibold text-slate-800">Deployed Bot Sub-processes</h2>
                </div>
                <span className="text-[10px] font-bold text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-full">
                  {status ? Object.keys(status.bots).length : 0} Total
                </span>
              </div>

              {/* Bot rows */}
              <div className="flex-1 divide-y divide-slate-100 overflow-y-auto max-h-[400px]">
                {status && Object.keys(status.bots).length > 0 ? (
                  Object.entries(status.bots).map(([botId, item]) => {
                    const botInfo = item as DeployedBot;
                    const isRunning = botInfo.status === "running";
                    return (
                      <div key={botId} className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 hover:bg-slate-50/50 transition-colors">
                        <div className="flex items-start gap-3">
                          <div className={`p-2.5 rounded-xl border ${isRunning ? "bg-emerald-50 border-emerald-100 text-emerald-600" : "bg-slate-50 border-slate-200 text-slate-400"}`}>
                            <FileCode size={20} />
                          </div>
                          <div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm text-slate-800">{botInfo.filename}</span>
                              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-md ${
                                botInfo.type === "python" ? "bg-blue-50 text-blue-600 border border-blue-100" : "bg-yellow-50 text-yellow-600 border border-yellow-100"
                              } uppercase`}>
                                {botInfo.type === "python" ? "Python" : "Node.js"}
                              </span>
                              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                                isRunning ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"
                              }`}>
                                {isRunning ? "Active" : "Stopped"}
                              </span>
                            </div>
                            
                            {/* Dependencies chip list */}
                            {botInfo.dependencies && botInfo.dependencies.length > 0 && (
                              <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                                <span className="text-[10px] text-slate-400">Deps:</span>
                                {botInfo.dependencies.map(dep => (
                                  <span key={dep} className="text-[9px] font-mono bg-slate-100 border border-slate-200 text-slate-500 px-1.5 py-0.5 rounded">
                                    {dep}
                                  </span>
                                ))}
                              </div>
                            )}

                            <span className="text-[10px] text-slate-400 block mt-1.5">
                              Deployed: {new Date(botInfo.created_at).toLocaleString()}
                            </span>
                          </div>
                        </div>

                        {/* Bot Actions */}
                        <div className="flex items-center gap-2 sm:self-center">
                          {isRunning ? (
                            <button 
                              onClick={() => handleBotControl(botId, "stop")}
                              className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 rounded-xl text-xs font-semibold transition-colors flex items-center gap-1"
                              id={`btn_stop_${botId}`}
                            >
                              <Square size={12} fill="currentColor" /> Stop
                            </button>
                          ) : (
                            <button 
                              onClick={() => handleBotControl(botId, "start")}
                              className="px-3 py-1.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-600 rounded-xl text-xs font-semibold transition-colors flex items-center gap-1"
                              id={`btn_start_${botId}`}
                            >
                              <Play size={12} fill="currentColor" /> Run
                            </button>
                          )}
                          
                          <button 
                            onClick={() => setSelectedLogSource(botId)}
                            className={`p-1.5 border rounded-xl text-xs font-semibold transition-colors flex items-center gap-1 ${
                              selectedLogSource === botId 
                                ? "bg-indigo-50 border-indigo-200 text-indigo-600" 
                                : "bg-white border-slate-200 hover:bg-slate-50 text-slate-500"
                            }`}
                            title="View Terminal Logs"
                            id={`btn_logs_${botId}`}
                          >
                            <Terminal size={14} />
                          </button>

                          <button 
                            onClick={() => handleBotControl(botId, "delete")}
                            className="p-1.5 bg-white border border-slate-200 hover:bg-rose-50 text-slate-400 hover:text-rose-600 rounded-xl transition-colors"
                            title="Delete Script"
                            id={`btn_delete_${botId}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="py-12 px-6 text-center text-slate-400 flex flex-col items-center gap-2" id="empty_bots_fallback">
                    <Bot size={36} className="opacity-40" />
                    <p className="text-sm font-medium text-slate-500">No script bots deployed yet</p>
                    <p className="text-xs max-w-xs mx-auto">Upload a script (.py or .js) using the card above or through your master Telegram bot!</p>
                  </div>
                )}
              </div>
            </div>

          </div>

          {/* RIGHT: Terminal Log Viewer */}
          <div className="lg:col-span-5 flex flex-col" id="right_column">
            <div className="bg-slate-900 text-slate-100 rounded-2xl shadow-lg border border-slate-800 flex flex-col flex-1 h-full min-h-[450px] lg:min-h-[550px] overflow-hidden" id="terminal_card">
              
              {/* Terminal Header */}
              <div className="px-4 py-3 bg-slate-950 border-b border-slate-800/80 flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1.5 mr-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80"></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
                  </div>
                  <Terminal size={14} className="text-slate-400" />
                  <span className="text-xs font-mono font-semibold tracking-wide text-slate-300">Live Log Terminal</span>
                </div>

                {/* Log Source selector */}
                <div className="flex items-center gap-2">
                  <select 
                    value={selectedLogSource} 
                    onChange={(e) => setSelectedLogSource(e.target.value)}
                    className="bg-slate-800 border border-slate-700/80 rounded-lg text-xs text-slate-200 px-2 py-1 font-mono focus:outline-none focus:border-indigo-500"
                    id="log_source_select"
                  >
                    <option value="manager">📋 Bot Manager Log</option>
                    {status && Object.entries(status.bots).map(([botId, item]) => {
                      const botInfo = item as DeployedBot;
                      return (
                        <option key={botId} value={botId}>
                          {botInfo.filename} ({botInfo.status === "running" ? "🟢" : "🔴"})
                        </option>
                      );
                    })}
                  </select>

                  <button 
                    onClick={fetchLogs}
                    className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded-md transition-colors"
                    title="Manual Refresh Logs"
                    id="btn_refresh_logs"
                  >
                    <RefreshCw size={13} />
                  </button>
                </div>
              </div>

              {/* Terminal Output Stream */}
              <div className="flex-1 p-4 overflow-y-auto font-mono text-[11px] leading-relaxed select-text flex flex-col gap-1 bg-slate-950/40">
                {logs ? (
                  logs.split("\n").map((line, idx) => {
                    let colorClass = "text-slate-300";
                    if (line.includes("[ERROR]") || line.includes("Error") || line.includes("Exception")) colorClass = "text-rose-400";
                    else if (line.includes("[WARN]") || line.includes("Warning")) colorClass = "text-amber-400";
                    else if (line.includes("Success") || line.includes("started successfully")) colorClass = "text-emerald-400";
                    else if (line.startsWith("---")) colorClass = "text-indigo-400/80";

                    return (
                      <div key={idx} className={`${colorClass} whitespace-pre-wrap break-all hover:bg-slate-800/10 px-1 py-0.5 rounded transition-colors`}>
                        {line}
                      </div>
                    );
                  })
                ) : (
                  <div className="text-slate-500 italic py-10 text-center">Awaiting log entries...</div>
                )}
                <div ref={terminalEndRef}></div>
              </div>

              {/* Terminal Footer controls */}
              <div className="px-4 py-2 bg-slate-950/80 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-400 font-mono">
                <span>Polling: every 2s</span>
                <label className="flex items-center gap-1.5 cursor-pointer hover:text-slate-200 transition-colors">
                  <input 
                    type="checkbox" 
                    checked={autoScroll} 
                    onChange={(e) => setAutoScroll(e.target.checked)}
                    className="rounded border-slate-800 bg-slate-900 text-indigo-600 focus:ring-0 w-3 h-3 cursor-pointer"
                  />
                  <span>Auto-Scroll</span>
                </label>
              </div>

            </div>
          </div>

        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200/60 py-5 text-center text-xs text-slate-400 mt-12" id="main_footer">
        <p>© 2026 Telegram Bot Deployer. Made with 🤍 on Google AI Studio.</p>
      </footer>
    </div>
  );
}
