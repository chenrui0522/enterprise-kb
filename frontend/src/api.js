const API_BASE = "/api/v1";

async function jsonFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function listConversations() {
  return jsonFetch("/conversations");
}

export async function createConversation() {
  return jsonFetch("/conversations", { method: "POST", body: JSON.stringify({}) });
}

export async function getMessages(conversationId) {
  return jsonFetch(`/conversations/${conversationId}/messages`);
}

export async function listDocuments() {
  return jsonFetch("/documents");
}

export async function uploadDocument(file, { ocr = false } = {}) {
  const form = new FormData();
  form.append("file", file);
  const query = ocr ? "?ocr=true" : "";
  const response = await fetch(`${API_BASE}/documents${query}`, { method: "POST", body: form });
  if (!response.ok) {
    throw new Error((await response.json()).detail || "上传失败");
  }
  return response.json();
}

export async function retryDocument(documentId) {
  return jsonFetch(`/documents/${documentId}/retry`, { method: "POST" });
}

export async function submitFeedback({ messageId, rating, comment }) {
  return jsonFetch("/feedback", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId, rating, comment: comment || null }),
  });
}

export async function streamChat({ message, conversationId, onStart, onToken, onDone, onError }) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId || null }),
  });
  if (!response.ok || !response.body) {
    throw new Error("无法连接对话服务");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk
        .split("\n")
        .find((item) => item.startsWith("data:"));
      if (!line) continue;
      const payload = JSON.parse(line.slice(5).trim());
      if (payload.event === "message_start") onStart?.(payload.data);
      else if (payload.event === "token") onToken?.(payload.data);
      else if (payload.event === "error") onError?.(payload.data);
      else if (payload.event === "done") onDone?.(payload.data);
    }
  }
}
