const express = require("express");
const router = express.Router();
const fetch = require("node-fetch");

const OLLAMA_URL = process.env.OLLAMA_URL || "http://10.0.0.2:11434";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || "qwen2.5:3b";
const MCP_URL = process.env.MCP_URL || "http://127.0.0.1:3002";
// Internal calls use no auth — token only needed for external (ElevenLabs) access.
const MCP_TOKEN = process.env.MCP_SECRET_TOKEN || "";

// ── Langfuse (optional, gracefully absent) ────────────────────────────────────
let langfuse = null;
try {
  const { Langfuse } = require("langfuse");
  langfuse = new Langfuse();
} catch (_) {}

// ── MCP helpers ───────────────────────────────────────────────────────────────

async function fetchMcpTools() {
  const headers = { "Content-Type": "application/json" };
  if (MCP_TOKEN) headers["Authorization"] = `Bearer ${MCP_TOKEN}`;

  const res = await fetch(`${MCP_URL}/tools`, { headers });
  if (!res.ok) throw new Error(`MCP /tools returned ${res.status}`);
  const data = await res.json();

  // Convert FastMCP tool list → Ollama function-calling schema
  return (data.tools || data).map((tool) => ({
    type: "function",
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.inputSchema || tool.parameters || { type: "object", properties: {} },
    },
  }));
}

async function callMcpTool(name, args) {
  const headers = {
    "Content-Type": "application/json",
    ...(MCP_TOKEN ? { Authorization: `Bearer ${MCP_TOKEN}` } : {}),
  };

  const res = await fetch(`${MCP_URL}/call`, {
    method: "POST",
    headers,
    body: JSON.stringify({ name, arguments: args }),
  });

  if (!res.ok) throw new Error(`MCP /call ${name} returned ${res.status}`);
  const data = await res.json();
  // FastMCP returns { content: [ { type: "text", text: "..." } ] }
  const textContent = (data.content || []).find((c) => c.type === "text");
  return textContent ? textContent.text : JSON.stringify(data);
}

// ── Route ─────────────────────────────────────────────────────────────────────

router.post("/", async (req, res) => {
  const { messages } = req.body;
  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: "messages array required" });
  }

  // SSE headers
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.flushHeaders();

  const trace = langfuse?.trace({ name: "chat" });

  const sendEvent = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  try {
    let tools = [];
    try {
      tools = await fetchMcpTools();
    } catch (err) {
      console.error("[chat] Failed to fetch MCP tools:", err.message);
      // Proceed without tools rather than failing the whole request
    }

    const ollamaPayload = {
      model: OLLAMA_MODEL,
      messages,
      stream: false,
      ...(tools.length > 0 ? { tools } : {}),
    };

    const span = trace?.span({ name: "ollama-first-call" });
    const firstRes = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ollamaPayload),
    });

    if (!firstRes.ok) {
      const errText = await firstRes.text();
      span?.end({ output: errText });
      throw new Error(`Ollama error ${firstRes.status}: ${errText}`);
    }

    const firstData = await firstRes.json();
    span?.end({ output: firstData });

    const assistantMsg = firstData.message;

    // ── Tool call handling ─────────────────────────────────────────────────
    if (assistantMsg?.tool_calls?.length > 0) {
      const updatedMessages = [
        ...messages,
        assistantMsg, // assistant turn with tool_calls
      ];

      for (const tc of assistantMsg.tool_calls) {
        const toolName = tc.function?.name;
        const toolArgs = tc.function?.arguments || {};

        const toolSpan = trace?.span({ name: `tool:${toolName}`, input: toolArgs });
        let toolResult;
        try {
          toolResult = await callMcpTool(toolName, toolArgs);
        } catch (err) {
          console.error(`[chat] Tool call ${toolName} failed:`, err.message);
          toolResult = JSON.stringify({ error: err.message });
        }
        toolSpan?.end({ output: toolResult });

        updatedMessages.push({
          role: "tool",
          content: toolResult,
        });
      }

      // Second Ollama call — stream the final natural-language response
      const finalRes = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          messages: updatedMessages,
          stream: true,
        }),
      });

      if (!finalRes.ok) {
        const errText = await finalRes.text();
        throw new Error(`Ollama final error ${finalRes.status}: ${errText}`);
      }

      // Stream NDJSON chunks from Ollama → SSE events to browser
      const decoder = new TextDecoder();
      for await (const chunk of finalRes.body) {
        const lines = decoder.decode(chunk).split("\n").filter(Boolean);
        for (const line of lines) {
          try {
            const parsed = JSON.parse(line);
            if (parsed.message?.content) {
              sendEvent({ content: parsed.message.content, done: parsed.done });
            }
            if (parsed.done) {
              res.write("data: [DONE]\n\n");
              res.end();
              return;
            }
          } catch (_) {}
        }
      }
    } else {
      // No tool calls — the model replied directly; stream the content as one chunk
      const content = assistantMsg?.content || "";
      sendEvent({ content, done: true });
      res.write("data: [DONE]\n\n");
      res.end();
    }
  } catch (err) {
    console.error("[chat] Unhandled error:", err);
    sendEvent({ error: err.message });
    res.write("data: [DONE]\n\n");
    res.end();
  }
});

module.exports = router;
