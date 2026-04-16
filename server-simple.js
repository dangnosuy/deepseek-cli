#!/usr/bin/env node
/**
 * DeepSeek → OpenAI Proxy Server
 *
 * Exposes OpenAI-compatible endpoints, proxies to DeepSeek web API.
 * Compatible with any OpenAI SDK / OpenClaw agent.
 *
 * Usage:
 *   DS_TOKEN="Bearer ..." DS_SESSION="..." node server.js
 *
 * Endpoints:
 *   GET  /v1/models
 *   POST /v1/chat/completions   (streaming + non-streaming)
 */

const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");

// ─── Config ───────────────────────────────────────────────────────
const PORT = parseInt(process.env.PORT || "8787", 10);
const API_KEY = process.env.PROXY_API_KEY || null; // optional auth
const DS_HOST = "chat.deepseek.com";
const WASM_URL =
  "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm";
const WASM_PATH = path.join(__dirname, "sha3_wasm_bg.wasm");

// ─── Utilities ────────────────────────────────────────────────────
function genId() {
  return (
    "chatcmpl-" +
    Math.random().toString(36).slice(2) +
    Date.now().toString(36)
  );
}

// ANSI Escape Codes for coloring outputs
const c = {
  rst: "\x1b[0m",
  grn: "\x1b[32m",
  red: "\x1b[31m",
  ylw: "\x1b[33m",
  cyn: "\x1b[36m",
  gry: "\x1b[90m",
};

function formatStatus(code) {
  if (!code) return `${c.gry}UNK${c.rst}`;
  if (code >= 200 && code < 300) return `${c.grn}${code}${c.rst}`;
  if (code >= 400 && code < 600) return `${c.red}${code}${c.rst}`;
  return `${c.ylw}${code}${c.rst}`;
}

function log(...args) {
  console.error(`${c.gry}[${new Date().toISOString()}]${c.rst}`, ...args);
}

function sendJSON(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Content-Length": Buffer.byteLength(data),
  });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}

function checkAuth(req) {
  if (!API_KEY) return true;
  const auth = req.headers["authorization"] || "";
  return auth === `Bearer ${API_KEY}`;
}

// ─── Model map ───────────────────────────────────────────────────
// Maps incoming model name → { thinking, search }
const MODEL_MAP = {
  "deepseek-chat": { thinking: false, search: false },
  "deepseek-chat-search": { thinking: false, search: true },
  "deepseek-reasoner": { thinking: true, search: false },
  "deepseek-r1": { thinking: true, search: false },
  // Allow passthrough aliases
  "gpt-4": { thinking: false, search: false },
  "gpt-4o": { thinking: false, search: false },
  "gpt-3.5-turbo": { thinking: false, search: false },
};

const AVAILABLE_MODELS = [
  { id: "deepseek-chat", object: "model", owned_by: "deepseek" },
  { id: "deepseek-chat-search", object: "model", owned_by: "deepseek" },
  { id: "deepseek-reasoner", object: "model", owned_by: "deepseek" },
  { id: "deepseek-r1", object: "model", owned_by: "deepseek" },
];

// ─── WASM PoW ─────────────────────────────────────────────────────
async function downloadWasm() {
  if (fs.existsSync(WASM_PATH)) return;
  log("Downloading SHA3 WASM (one-time)...");
  await new Promise((res, rej) => {
    https
      .get(WASM_URL, (r) => {
        const chunks = [];
        r.on("data", (c) => chunks.push(c));
        r.on("end", () => {
          fs.writeFileSync(WASM_PATH, Buffer.concat(chunks));
          res();
        });
        r.on("error", rej);
      })
      .on("error", rej);
  });
  log("WASM downloaded.");
}

let _solver = null;
async function getSolver() {
  if (_solver) return _solver;
  await downloadWasm();
  const wasmBytes = fs.readFileSync(WASM_PATH);
  const { instance } = await WebAssembly.instantiate(wasmBytes, {});
  const wasm = instance.exports;
  const enc = new TextEncoder();
  let vecLen = 0;
  const mem8 = () => new Uint8Array(wasm.memory.buffer);
  const memDV = () => new DataView(wasm.memory.buffer);
  function passStr(s) {
    const buf = enc.encode(s);
    const ptr = wasm.__wbindgen_export_0(buf.length, 1);
    mem8().subarray(ptr, ptr + buf.length).set(buf);
    vecLen = buf.length;
    return ptr;
  }
  _solver = function solve(challenge, salt, difficulty, expireAt) {
    const prefix = `${salt}_${expireAt}_`;
    const ret = wasm.__wbindgen_add_to_stack_pointer(-16);
    try {
      const cp = passStr(challenge),
        cl = vecLen;
      const pp = passStr(prefix),
        pl = vecLen;
      wasm.wasm_solve(ret, cp, cl, pp, pl, difficulty);
      const flag = memDV().getInt32(ret, true);
      const ans = memDV().getFloat64(ret + 8, true);
      return flag === 0 ? null : ans;
    } finally {
      wasm.__wbindgen_add_to_stack_pointer(16);
    }
  };
  return _solver;
}

// ─── DeepSeek HTTP helpers ────────────────────────────────────────
function dsHeaders(extra = {}) {
  const token = process.env.DS_TOKEN;
  const session = process.env.DS_SESSION;
  if (!token || !session) throw new Error("DS_TOKEN and DS_SESSION not set");
  return {
    "Content-Type": "application/json",
    Authorization: token,
    Origin: "https://chat.deepseek.com",
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    Cookie: "ds_session_id=" + session,
    ...extra,
  };
}

function dsPost(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request(
      {
        hostname: DS_HOST,
        path: urlPath,
        method: "POST",
        headers: {
          ...dsHeaders(),
          "Content-Length": Buffer.byteLength(data),
        },
      },
      (res) => {
        let b = "";
        res.on("data", (c) => (b += c));
        res.on("end", () => {
          if (res.statusCode !== 200) {
            log(`${c.red}[DS POST] Error ${formatStatus(res.statusCode)} for ${urlPath}${c.rst}`);
            log(`${c.red}[DS POST] Response body: ${b.slice(0, 300)}${c.rst}`);
          }
          try {
            resolve(JSON.parse(b));
          } catch {
            reject(new Error("Bad JSON: " + b.slice(0, 300)));
          }
        });
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function dsGet(urlPath) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      { hostname: DS_HOST, path: urlPath, method: "GET", headers: dsHeaders() },
      (res) => {
        let b = "";
        res.on("data", (c) => (b += c));
        res.on("end", () => {
          if (res.statusCode !== 200) {
            log(`${c.red}[DS GET] Error ${formatStatus(res.statusCode)} for ${urlPath}${c.rst}`);
            log(`${c.red}[DS GET] Response body: ${b.slice(0, 300)}${c.rst}`);
          }
          try {
            resolve(JSON.parse(b));
          } catch {
            reject(new Error("Bad JSON: " + b.slice(0, 300)));
          }
        });
      }
    );
    req.on("error", reject);
    req.end();
  });
}

// ─── PoW ─────────────────────────────────────────────────────────
async function solvePoW() {
  const solver = await getSolver();
  const resp = await dsPost("/api/v0/chat/create_pow_challenge", {
    target_path: "/api/v0/chat/completion",
  });
  if (resp.code !== 0)
    throw new Error("PoW challenge failed: " + JSON.stringify(resp));
  const ch = resp.data.biz_data.challenge;
  const answer = solver(ch.challenge, ch.salt, ch.difficulty, ch.expire_at);
  if (answer === null) throw new Error("PoW: no solution found");
  return Buffer.from(
    JSON.stringify({
      algorithm: ch.algorithm,
      challenge: ch.challenge,
      salt: ch.salt,
      answer,
      signature: ch.signature,
      target_path: "/api/v0/chat/completion",
    })
  ).toString("base64");
}

// ─── Session management ──────────────────────────────────────────
async function createSession() {
  const resp = await dsPost("/api/v0/chat_session/create", {
    character_id: null,
  });
  if (resp.code !== 0)
    throw new Error("Session create failed: " + JSON.stringify(resp));
  return resp.data.biz_data.id;
}

async function getLastMsgId(chatId) {
  const resp = await dsGet(
    `/api/v0/chat/history_messages?chat_session_id=${chatId}`
  );
  if (resp.code !== 0)
    throw new Error("History failed: " + JSON.stringify(resp));
  return resp.data.biz_data.chat_session.current_message_id;
}

// ─── Convert OpenAI messages → single DeepSeek prompt ────────────
function buildPrompt(messages) {
  // Build a rich prompt from the messages array
  const parts = [];
  let systemPrompt = null;

  for (const msg of messages) {
    const role = msg.role;
    const content =
      typeof msg.content === "string"
        ? msg.content
        : msg.content
            ?.map((c) => (c.type === "text" ? c.text : ""))
            .join("") || "";

    if (role === "system") {
      systemPrompt = content;
    } else if (role === "user") {
      parts.push(`User: ${content}`);
    } else if (role === "assistant") {
      parts.push(`Assistant: ${content}`);
    }
  }

  let prompt = parts.join("\n\n");
  if (systemPrompt) {
    prompt = `System: ${systemPrompt}\n\n${prompt}`;
  }
  return prompt;
}

// ─── Stream DeepSeek → OpenAI SSE ────────────────────────────────
function streamCompletion(
  chatId,
  parentId,
  prompt,
  powB64,
  thinking,
  search,
  res,
  model,
  reqId
) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      chat_session_id: chatId,
      parent_message_id: parentId,
      model_type: null,
      prompt,
      ref_file_ids: [],
      thinking_enabled: thinking,
      search_enabled: search,
      preempt: false,
    });

    const req = https.request(
      {
        hostname: DS_HOST,
        path: "/api/v0/chat/completion",
        method: "POST",
        headers: {
          ...dsHeaders({ "X-Ds-Pow-Response": powB64 }),
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (dsRes) => {
        let buf = "";
        let currentField = null;
        let thinkingBuf = "";
        let contentBuf = "";
        let finished = false;

        log(`${c.cyn}[${reqId}] streamCompletion connected, status=${formatStatus(dsRes.statusCode)}${c.rst}`);

        const sendChunk = (delta) => {
          const chunk = {
            id: reqId,
            object: "chat.completion.chunk",
            created: Math.floor(Date.now() / 1000),
            model,
            choices: [{ index: 0, delta, finish_reason: null }],
          };
          res.write(`data: ${JSON.stringify(chunk)}\n\n`);
        };

        // Send role first
        sendChunk({ role: "assistant", content: "" });

        dsRes.on("data", (chunk) => {
          buf += chunk.toString();
          let idx;
          while ((idx = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 1);
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6);
            if (!raw || raw === "{}") continue;
            let msg;
            try {
              msg = JSON.parse(raw);
            } catch {
              continue;
            }

            if (msg.code && msg.code !== 0) {
              reject(new Error(`DeepSeek error: ${msg.msg} (${msg.code})`));
              return;
            }

            if (!msg.p) {
              // Continuation of current field
              if (typeof msg.v === "string") {
                if (currentField === "thinking") {
                  thinkingBuf += msg.v;
                  // Stream thinking as reasoning_content in a special delta
                  sendChunk({ reasoning_content: msg.v, content: "" });
                } else if (currentField === "content") {
                  contentBuf += msg.v;
                  sendChunk({ content: msg.v });
                }
              }
              continue;
            }

            // Thinking content
            if (msg.p === "response/thinking_content") {
              currentField = "thinking";
              if (typeof msg.v === "string" && msg.v) {
                thinkingBuf += msg.v;
                sendChunk({ reasoning_content: msg.v, content: "" });
              }
              continue;
            }

            // Regular content
            if (msg.p === "response/content") {
              currentField = "content";
              if (typeof msg.v === "string" && msg.v) {
                contentBuf += msg.v;
                sendChunk({ content: msg.v });
              }
              continue;
            }

            // Search fragment content
            if (
              msg.p &&
              msg.p.includes("fragments") &&
              msg.p.endsWith("/content")
            ) {
              currentField = "content";
              if (typeof msg.v === "string" && msg.v) {
                contentBuf += msg.v;
                sendChunk({ content: msg.v });
              }
              continue;
            }

            // End of thinking
            if (msg.p === "response/thinking_elapsed_secs") {
              currentField = null;
              continue;
            }

            // Finished
            if (msg.p === "response/status" || msg.p === "response") {
              const checkFinished = (v) => {
                if (v === "FINISHED" && !finished) {
                  finished = true;
                  const doneChunk = {
                    id: reqId,
                    object: "chat.completion.chunk",
                    created: Math.floor(Date.now() / 1000),
                    model,
                    choices: [
                      {
                        index: 0,
                        delta: {},
                        finish_reason: "stop",
                      },
                    ],
                  };
                  res.write(`data: ${JSON.stringify(doneChunk)}\n\n`);
                  res.write("data: [DONE]\n\n");
                }
              };
              if (typeof msg.v === "string") checkFinished(msg.v);
              if (Array.isArray(msg.v)) {
                for (const op of msg.v) {
                  if (op.p === "status") checkFinished(op.v);
                }
              }
              continue;
            }
          }
        });

        dsRes.on("end", () => {
          if (dsRes.statusCode !== 200) {
            log(`${c.red}[${reqId}] Error ${formatStatus(dsRes.statusCode)} for response completion. Buffer: ${buf.slice(0, 300)}${c.rst}`);
          } else {
            log(`${c.grn}[${reqId}] Stream completion finished successfully.${c.rst}`);
          }
          if (!finished) {
            const doneChunk = {
              id: reqId,
              object: "chat.completion.chunk",
              created: Math.floor(Date.now() / 1000),
              model,
              choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
            };
            res.write(`data: ${JSON.stringify(doneChunk)}\n\n`);
            res.write("data: [DONE]\n\n");
          }
          resolve({ content: contentBuf, thinking: thinkingBuf });
        });
        dsRes.on("error", reject);
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ─── Collect non-streaming response ──────────────────────────────
function collectCompletion(
  chatId,
  parentId,
  prompt,
  powB64,
  thinking,
  search
) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      chat_session_id: chatId,
      parent_message_id: parentId,
      model_type: null,
      prompt,
      ref_file_ids: [],
      thinking_enabled: thinking,
      search_enabled: search,
      preempt: false,
    });

    const req = https.request(
      {
        hostname: DS_HOST,
        path: "/api/v0/chat/completion",
        method: "POST",
        headers: {
          ...dsHeaders({ "X-Ds-Pow-Response": powB64 }),
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (dsRes) => {
        let buf = "";
        let currentField = null;
        let contentBuf = "";
        let thinkingBuf = "";

        log(`${c.cyn}[DS NO-STREAM] collectCompletion connected, status=${formatStatus(dsRes.statusCode)}${c.rst}`);

        dsRes.on("data", (chunk) => {
          buf += chunk.toString();
          let idx;
          while ((idx = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 1);
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6);
            if (!raw || raw === "{}") continue;
            let msg;
            try {
              msg = JSON.parse(raw);
            } catch {
              continue;
            }

            if (msg.code && msg.code !== 0) {
              reject(new Error(`DeepSeek error: ${msg.msg} (${msg.code})`));
              return;
            }

            if (!msg.p) {
              if (typeof msg.v === "string") {
                if (currentField === "thinking") thinkingBuf += msg.v;
                else if (currentField === "content") contentBuf += msg.v;
              }
              continue;
            }

            if (msg.p === "response/thinking_content") {
              currentField = "thinking";
              if (typeof msg.v === "string") thinkingBuf += msg.v;
              continue;
            }

            if (msg.p === "response/content") {
              currentField = "content";
              if (typeof msg.v === "string") contentBuf += msg.v;
              continue;
            }

            if (
              msg.p &&
              msg.p.includes("fragments") &&
              msg.p.endsWith("/content")
            ) {
              currentField = "content";
              if (typeof msg.v === "string") contentBuf += msg.v;
              continue;
            }

            if (msg.p === "response/thinking_elapsed_secs") {
              currentField = null;
              continue;
            }
          }
        });

        dsRes.on("end", () => {
          if (dsRes.statusCode !== 200) {
            log(`${c.red}[DS NO-STREAM] Error ${formatStatus(dsRes.statusCode)} for response completion. Buffer: ${buf.slice(0, 300)}${c.rst}`);
          } else {
            log(`${c.grn}[DS NO-STREAM] Finished successfully.${c.rst}`);
          }
          resolve({ content: contentBuf, thinking: thinkingBuf })
        });
        dsRes.on("error", reject);
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

// ─── Route handlers ───────────────────────────────────────────────
async function handleModels(req, res) {
  sendJSON(res, 200, {
    object: "list",
    data: AVAILABLE_MODELS.map((m) => ({
      ...m,
      created: 1700000000,
    })),
  });
}

async function handleChatCompletions(req, res) {
  let body;
  try {
    body = await readBody(req);
  } catch {
    return sendJSON(res, 400, {
      error: { message: "Invalid JSON", type: "invalid_request_error" },
    });
  }

  const {
    messages = [],
    model = "deepseek-chat",
    stream = false,
  } = body;

  if (!messages.length) {
    return sendJSON(res, 400, {
      error: {
        message: "messages is required",
        type: "invalid_request_error",
      },
    });
  }

  // Resolve model config
  const modelCfg = MODEL_MAP[model] || MODEL_MAP["deepseek-chat"];
  const thinking = modelCfg.thinking;
  const search = modelCfg.search;

  const reqId = genId();
  const promptLen = JSON.stringify(messages).length;
  log(`${c.cyn}[${reqId}] REQ:${c.rst} model=${model} stream=${stream} context_len=${promptLen} msgs=${messages.length}`);

  try {
    const prompt = buildPrompt(messages);
    const [powB64, chatId] = await Promise.all([solvePoW(), createSession()]);
    const parentId = await getLastMsgId(chatId);

    if (stream) {
      // Streaming response
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "X-Accel-Buffering": "no",
      });

      await streamCompletion(
        chatId,
        parentId,
        prompt,
        powB64,
        thinking,
        search,
        res,
        model,
        reqId
      );
      res.end();
    } else {
      // Non-streaming response
      const { content, thinking: thinkingContent } = await collectCompletion(
        chatId,
        parentId,
        prompt,
        powB64,
        thinking,
        search
      );

      const message = { role: "assistant", content };
      if (thinkingContent)
        message.reasoning_content = thinkingContent;

      sendJSON(res, 200, {
        id: reqId,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model,
        choices: [
          {
            index: 0,
            message,
            finish_reason: "stop",
          },
        ],
        usage: {
          prompt_tokens: -1,
          completion_tokens: -1,
          total_tokens: -1,
        },
      });
    }
  } catch (err) {
    log(`${c.red}[${reqId}] Error processing request: ${err.message}${c.rst}`);
    if (!res.headersSent) {
      sendJSON(res, 500, {
        error: {
          message: err.message,
          type: "server_error",
        },
      });
    } else {
      res.end();
    }
  }
}

// ─── Server ───────────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
    });
    return res.end();
  }

  // Auth check
  if (!checkAuth(req)) {
    return sendJSON(res, 401, {
      error: { message: "Invalid API key", type: "invalid_request_error" },
    });
  }

  const url = req.url.split("?")[0];

  try {
    if (req.method === "GET" && url === "/v1/models") {
      return await handleModels(req, res);
    }
    if (req.method === "POST" && url === "/v1/chat/completions") {
      return await handleChatCompletions(req, res);
    }
    // Health check
    if (req.method === "GET" && (url === "/" || url === "/health")) {
      return sendJSON(res, 200, { status: "ok", version: "1.0.0" });
    }
    sendJSON(res, 404, { error: { message: "Not found" } });
  } catch (err) {
    log("Unhandled error:", err);
    if (!res.headersSent) {
      sendJSON(res, 500, { error: { message: "Internal server error" } });
    }
  }
});

// ─── Boot ─────────────────────────────────────────────────────────
async function boot() {
  if (!process.env.DS_TOKEN || !process.env.DS_SESSION) {
    console.error("ERROR: DS_TOKEN and DS_SESSION environment variables are required.");
    console.error("Run: node deepseek-cli.js --setup to get them.");
    process.exit(1);
  }

  // Pre-download WASM
  await downloadWasm();
  // Pre-init solver
  await getSolver();
  log("WASM solver ready.");

  server.listen(PORT, () => {
    console.log(`
╔══════════════════════════════════════════════════╗
║         DeepSeek → OpenAI Proxy Server           ║
╠══════════════════════════════════════════════════╣
║  URL  : http://localhost:${PORT}                    ║
║  Auth : ${API_KEY ? "enabled (PROXY_API_KEY)" : "disabled (open access)     "}         ║
╠══════════════════════════════════════════════════╣
║  Endpoints:                                      ║
║    GET  /v1/models                               ║
║    POST /v1/chat/completions                     ║
╠══════════════════════════════════════════════════╣
║  Models:                                         ║
║    deepseek-chat          → regular chat         ║
║    deepseek-reasoner      → R1 thinking mode     ║
║    deepseek-chat-search   → chat + web search    ║
╚══════════════════════════════════════════════════╝
`);
  });
}

boot().catch((e) => {
  console.error("Fatal:", e.message);
  process.exit(1);
});
