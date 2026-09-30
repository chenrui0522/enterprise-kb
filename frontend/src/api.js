const API_BASE = "/api/v1";

function handleUnauthorized(status) {
  if (status === 401 && !window.location.pathname.startsWith("/login")) {
    window.location.assign("/login");
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

export async function updateConversationTitle(conversationId, title) {
  return jsonFetch(`/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(conversationId) {
  return jsonFetch(`/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export async function getMessages(conversationId) {
  return jsonFetch(`/conversations/${conversationId}/messages`);
}

export async function getConversationMemory(conversationId) {
  return jsonFetch(`/conversations/${conversationId}/memory`);
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

export async function streamChat({
  message,
  conversationId,
  activeTool,
  attachmentId,
  onStart,
  onToken,
  onDone,
  onError,
}) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId || null,
      // "" clears sticky tool; omit/null keeps prior conversation tool_state
      active_tool: activeTool === undefined || activeTool === null ? null : activeTool,
      attachment_id: attachmentId || null,
    }),
  });
  if (!response.ok || !response.body) {
    handleUnauthorized(response.status);
    throw new Error("无法连接对话服务");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let sawDone = false;
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
      else if (payload.event === "done") {
        sawDone = true;
        onDone?.(payload.data);
      }
    }
  }
  if (!sawDone) {
    throw new Error("对话中断，未收到完整回复，请重试");
  }
}

export async function listChatTools() {
  return jsonFetch("/chat/tools");
}

export async function uploadChatAttachment(file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/chat/attachments`, {
    method: "POST",
    credentials: "include",
    body: form,
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
    if (response.status === 404) {
      detail = "附件接口不可用（请重启后端后再试）";
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

export async function chatToolAction({ conversationId, action, payload }) {
  return jsonFetch("/chat/tool-action", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: conversationId,
      action,
      payload: payload || null,
    }),
  });
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

// ---- Staffing ----

export async function listMyStaffingProjects() {
  return jsonFetch("/staffing/my-projects");
}

export async function uploadStaffingImport(file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/staffing/imports`, {
    method: "POST",
    credentials: "include",
    body: form,
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
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = response.status;
    throw err;
  }
  return response.json();
}

export async function getStaffingImport(batchId) {
  return jsonFetch(`/staffing/imports/${batchId}`);
}

export async function reviewStaffingImport(batchId, body) {
  return jsonFetch(`/staffing/imports/${batchId}/review`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function confirmStaffingImport(batchId) {
  return jsonFetch(`/staffing/imports/${batchId}/confirm`, { method: "POST", body: "{}" });
}

export async function getStaffingSummary(projectId) {
  return jsonFetch(`/staffing/projects/${projectId}/summary`);
}

export async function mergeStaffingNames(projectId, fromName, toName) {
  return jsonFetch(`/staffing/projects/${projectId}/merge-names`, {
    method: "POST",
    body: JSON.stringify({ from_name: fromName, to_name: toName }),
  });
}

export async function repairStaffingRosterNames(projectId) {
  return jsonFetch(`/staffing/projects/${projectId}/repair-roster-names`, {
    method: "POST",
    body: "{}",
  });
}

export async function exportStaffingXlsx(projectId) {
  const response = await fetch(`${API_BASE}/staffing/projects/${projectId}/export.xlsx`, {
    method: "GET",
    credentials: "include",
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
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `staffing-${projectId}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function listStaffingFacts(projectId, includeVoided = false) {
  const q = includeVoided ? "?include_voided=true" : "";
  return jsonFetch(`/staffing/projects/${projectId}/facts${q}`);
}

export async function voidStaffing(projectId, body) {
  return jsonFetch(`/staffing/projects/${projectId}/void`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---- Leave ledger ----

export async function createLeaveLedgerJob(files) {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const response = await fetch(`${API_BASE}/leave-ledger/jobs`, {
    method: "POST",
    credentials: "include",
    body: form,
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
    throw new Error(detail);
  }
  return response.json();
}

export async function getLeaveLedgerJob(jobId) {
  return jsonFetch(`/leave-ledger/jobs/${jobId}`);
}

export async function listConfirmedLeaveLedgerJobs() {
  return jsonFetch(`/leave-ledger/jobs?status=confirmed`);
}

export async function mergeLeaveLedgerJob(jobId, priorJobId) {
  return jsonFetch(`/leave-ledger/jobs/${jobId}/merge`, {
    method: "POST",
    body: JSON.stringify({ prior_job_id: priorJobId }),
  });
}

export async function uploadLeaveLedgerSource(jobId, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/leave-ledger/jobs/${jobId}/sources`, {
    method: "POST",
    credentials: "include",
    body: form,
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
    throw new Error(detail);
  }
  return response.json();
}

export async function reviewLeaveLedgerJob(jobId, resolutions) {
  return jsonFetch(`/leave-ledger/jobs/${jobId}/review`, {
    method: "POST",
    body: JSON.stringify({ resolutions }),
  });
}

export async function confirmLeaveLedgerJob(jobId) {
  return jsonFetch(`/leave-ledger/jobs/${jobId}/confirm`, { method: "POST", body: "{}" });
}

export async function voidLeaveLedgerJob(jobId, reason = "") {
  return jsonFetch(`/leave-ledger/jobs/${jobId}/void`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function exportLeaveLedgerXlsx(jobId) {
  const response = await fetch(`${API_BASE}/leave-ledger/jobs/${jobId}/export.xlsx`, {
    method: "GET",
    credentials: "include",
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
    throw new Error(detail);
  }
  return response.blob();
}

