const API_BASE = "/api/v1";

function handleUnauthorized(status) {
  if (status === 401 && !window.location.pathname.startsWith("/login")) {
    window.location.assign = "/login";
  }
}

async function jsonFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    handleUnauthorized(response.status);
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function login(username, password) {
  return jsonFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout() {
  return jsonFetch("/auth/logout", { method: "POST" });
}

export async function getMe() {
  return jsonFetch("/auth/me");
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
export async function listDocumentImages(documentId) {
  return jsonFetch(`/documents/${documentId}/images`);
}

export async function uploadDocument(file, { ocr = false, orgUnitId, projectId, domain, classification } = {}) {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams();
  if (ocr) params.set("ocr", "true");
  if (orgUnitId) params.set("org_unit_id", orgUnitId);
  if (projectId) params.set("project_id", projectId);
  if (domain) params.set("domain", domain);
  if (classification) params.set("classification", classification);
  const query = params.toString() ? `?${params}` : "";
  const response = await fetch(`${API_BASE}/documents${query}`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!response.ok) {
    handleUnauthorized(response.status);
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
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId || null }),
  });
  if (!response.ok || !response.body) {
    handleUnauthorized(response.status);
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

// ---- Admin: org / positions / users / projects ----

export async function listOrgUnits() {
  return jsonFetch("/org-units");
}

export async function createOrgUnit(body) {
  return jsonFetch("/org-units", { method: "POST", body: JSON.stringify(body) });
}

export async function listPositions() {
  return jsonFetch("/positions");
}

export async function createPosition(body) {
  return jsonFetch("/positions", { method: "POST", body: JSON.stringify(body) });
}

export async function listUsers() {
  return jsonFetch("/users");
}

export async function createUser(body) {
  return jsonFetch("/users", { method: "POST", body: JSON.stringify(body) });
}

export async function bindUserPosition(userId, { positionId, clearance }) {
  if (!clearance) {
    throw new Error("绑岗必须选择密级");
  }
  return jsonFetch(`/users/${userId}/positions`, {
    method: "POST",
    body: JSON.stringify({ position_id: positionId, clearance }),
  });
}

export async function unbindUserPosition(userId, positionId, clearance) {
  if (!clearance) {
    throw new Error("减岗必须选择密级");
  }
  const params = new URLSearchParams({ clearance });
  return jsonFetch(`/users/${userId}/positions/${positionId}?${params}`, {
    method: "DELETE",
  });
}

export async function updateUserClearance(userId, clearance) {
  if (!clearance) {
    throw new Error("必须选择密级");
  }
  return jsonFetch(`/users/${userId}/clearance`, {
    method: "PATCH",
    body: JSON.stringify({ clearance }),
  });
}

export async function setEstablishment(userId, orgUnitId) {
  return jsonFetch(`/users/${userId}/establishment`, {
    method: "POST",
    body: JSON.stringify({ org_unit_id: orgUnitId }),
  });
}

export async function listProjects() {
  return jsonFetch("/projects");
}

export async function createProject(body) {
  return jsonFetch("/projects", { method: "POST", body: JSON.stringify(body) });
}

export async function listProjectMembers(projectId) {
  return jsonFetch(`/projects/${projectId}/members`);
}

export async function addProjectMember(projectId, userId) {
  return jsonFetch(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function removeProjectMember(projectId, userId) {
  return jsonFetch(`/projects/${projectId}/members/${userId}`, { method: "DELETE" });
}

export async function listAuditEvents({
  limit = 50,
  offset = 0,
  action = "",
  actor = "",
  since = "",
  until = "",
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (action) params.set("action", action);
  if (actor) params.set("actor", actor);
  if (since) params.set("since", since);
  if (until) params.set("until", until);
  return jsonFetch(`/audit/events?${params}`);
}
