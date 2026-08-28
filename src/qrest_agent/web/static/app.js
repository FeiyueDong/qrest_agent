"use strict";

const state = {
  sessionId: localStorage.getItem("qrest-agent-session-id") || "",
  session: null,
  recordFilter: localStorage.getItem("qrest-agent-record-filter") || "accepted",
  pendingAttachments: []
};

const recordFilterLabels = {accepted: "已确认", pending: "待确认", missing: "缺失", conflict: "冲突"};
const statusLabels = {
  confirmed: "已确认", extracted: "已提取", derived: "推导", uncertain: "待确认",
  inferred: "推测", missing: "缺失", conflict: "冲突"
};

const messages = document.querySelector("#messages");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const fileInput = document.querySelector("#fileInput");
const uploadButton = document.querySelector("#uploadButton");
const exportButton = document.querySelector("#exportButton");
const refreshButton = document.querySelector("#refreshButton");
const recordFilterButtons = Array.from(document.querySelectorAll("[data-record-filter]"));
const skillList = document.querySelector("#skillList");
const artifactList = document.querySelector("#artifactList");
const attachmentChips = document.querySelector("#attachmentChips");
const attachmentStatus = document.querySelector("#attachmentStatus");
const turnActivity = document.querySelector("#turnActivity");
const turnBadge = document.querySelector("#turnBadge");
const recentTurns = document.querySelector("#recentTurns");
const recentTurnCount = document.querySelector("#recentTurnCount");
const inputList = document.querySelector("#inputList");
const inputCount = document.querySelector("#inputCount");

async function api(path, options = {}) {
  const headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
  const response = await fetch(path, Object.assign({}, options, {headers}));
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const error = new Error(data.error || response.statusText);
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

async function ensureSession() {
  const payload = state.sessionId ? {session_id: state.sessionId} : {};
  try {
    state.session = await api("/api/sessions", {method: "POST", body: JSON.stringify(payload)});
  } catch (error) {
    if (error.status !== 409 || !state.sessionId) throw error;
    state.session = await api("/api/session?session_id=" + encodeURIComponent(state.sessionId));
  }
  state.sessionId = state.session.session_id;
  localStorage.setItem("qrest-agent-session-id", state.sessionId);
  appendMessage("assistant", "会话已就绪。");
  renderSession();
}

async function refreshSession() {
  if (!state.sessionId) return;
  state.session = await api("/api/session?session_id=" + encodeURIComponent(state.sessionId));
  renderSession();
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message && state.pendingAttachments.length === 0) return;
  const attachments = state.pendingAttachments.map((item) => item.attachment_id);
  const attachmentNames = state.pendingAttachments.map((item) => item.name);
  appendMessage("user", message || "（附件）", null, attachmentNames);
  messageInput.value = "";
  state.pendingAttachments = [];
  renderAttachmentChips();
  sendButton.disabled = true;
  try {
    const result = await api("/api/turn", {
      method: "POST",
      body: JSON.stringify({session_id: state.sessionId, message, attachments})
    });
    appendMessage("assistant", result.response, result);
    renderTurnActivity(result.turn);
    await refreshSession();
  } catch (error) {
    appendMessage("assistant", "请求失败：" + error.message);
  } finally {
    sendButton.disabled = false;
    messageInput.focus();
  }
});

uploadButton.addEventListener("click", async () => {
  const files = Array.from(fileInput.files || []);
  if (!files.length) return;
  uploadButton.disabled = true;
  try {
    for (const file of files) {
      const contentBase64 = await fileToBase64(file);
      const result = await api("/api/upload", {
        method: "POST",
        body: JSON.stringify({
          session_id: state.sessionId,
          file_name: file.name,
          content_base64: contentBase64
        })
      });
      state.pendingAttachments.push({attachment_id: result.attachment_id, name: result.name});
    }
    fileInput.value = "";
    renderAttachmentChips();
  } catch (error) {
    appendMessage("assistant", "附件上传失败：" + error.message);
  } finally {
    uploadButton.disabled = false;
  }
});

exportButton.addEventListener("click", async () => {
  exportButton.disabled = true;
  try {
    const result = await api("/api/export-metadata", {
      method: "POST",
      body: JSON.stringify({session_id: state.sessionId, file_name: "metadata.json"})
    });
    const lines = result.messages || [];
    if (result.ok) {
      appendMessage("assistant", ["metadata.json 已导出。"].concat(lines).join("\n"), result);
    } else {
      appendMessage("assistant", ["metadata.json 未导出。"].concat(lines).join("\n"), result);
    }
    await refreshSession();
  } catch (error) {
    appendMessage("assistant", "导出失败：" + error.message);
  } finally {
    exportButton.disabled = false;
  }
});

refreshButton.addEventListener("click", () => {
  refreshSession().catch((error) => appendMessage("assistant", "刷新失败：" + error.message));
});

for (const button of recordFilterButtons) {
  button.addEventListener("click", () => {
    state.recordFilter = button.dataset.recordFilter || "accepted";
    localStorage.setItem("qrest-agent-record-filter", state.recordFilter);
    renderSession();
  });
}

function appendMessage(role, text, payload, attachmentNames) {
  const item = document.createElement("article");
  item.className = "message " + (role === "user" ? "user" : "assistant");
  const label = document.createElement("div");
  label.className = "role";
  label.textContent = role === "user" ? "你" : "Agent";
  const body = document.createElement("pre");
  body.textContent = text || "";
  item.append(label, body);
  if (attachmentNames && attachmentNames.length) {
    const note = document.createElement("div");
    note.className = "role";
    note.textContent = "附件：" + attachmentNames.join("、");
    item.append(note);
  }
  if (payload && payload.turn) {
    const detail = document.createElement("div");
    detail.className = "role";
    const turn = payload.turn;
    detail.textContent = "intent=" + (turn.intent || "?") +
      "; skills=" + (turn.skills || []).join(",") +
      "; extractor=" + (turn.extractor || "?") +
      (turn.fallback_reason ? "; fallback=" + turn.fallback_reason : "");
    item.append(detail);
  }
  messages.append(item);
  messages.scrollTop = messages.scrollHeight;
}

function renderSession() {
  const session = state.session || {};
  const report = session.report || {};
  const records = session.records || {};
  const runtime = session.runtime || {};
  const recordSets = collectRecordSets(records, report);
  document.querySelector("#sessionBadge").textContent = "session: " + (session.session_id || "...");
  document.querySelector("#runtimeBadge").textContent = runtime.model
    ? "runtime: " + runtime.provider + " / " + runtime.model
    : "runtime: " + (runtime.provider || "rule");
  const readyBadge = document.querySelector("#readyBadge");
  readyBadge.textContent = "ready: " + (report.ready ? "yes" : "no");
  readyBadge.classList.toggle("ready", !!report.ready);
  document.querySelector("#acceptedCount").textContent = String(recordSets.accepted.length);
  document.querySelector("#pendingCount").textContent = String(recordSets.pending.length);
  document.querySelector("#missingCount").textContent = String(recordSets.missing.length);
  document.querySelector("#conflictCount").textContent = String(recordSets.conflict.length);
  renderFilterButtons();
  renderSkills(session);
  renderArtifacts(session);
  renderRecentTurns(session);
  renderInputs(session);
  renderRecords(recordSets[state.recordFilter] || recordSets.accepted, state.recordFilter);
  if (session.last_turn && !turnBadge.dataset.latest) {
    renderTurnActivity(session.last_turn);
  }
}

function renderRecentTurns(session) {
  const turns = (session.turns || []).filter((t) => t.role === "assistant" && t.payload && t.payload.turn);
  recentTurnCount.textContent = turns.length + " 轮";
  recentTurns.replaceChildren();
  if (!turns.length) {
    const empty = document.createElement("div");
    empty.className = "recent-turn-item muted";
    empty.textContent = "暂无历史回合";
    recentTurns.append(empty);
    return;
  }
  for (const t of turns.slice(-5).reverse()) {
    const turn = t.payload.turn;
    const item = document.createElement("div");
    item.className = "recent-turn-item";
    const intent = document.createElement("div");
    intent.className = "rt-intent";
    intent.textContent = (turn.intent || "unknown") + " · " + ((turn.actions || []).length) + " actions";
    const meta = document.createElement("div");
    meta.className = "rt-meta";
    const skills = (turn.skills || []).join(",") || "-";
    meta.textContent = "skills: " + skills + (turn.extractor ? " · " + turn.extractor : "");
    item.append(intent, meta);
    recentTurns.append(item);
  }
}

function renderInputs(session) {
  const attachments = session.attachments || [];
  inputCount.textContent = attachments.length + " 项";
  inputList.replaceChildren();
  if (!attachments.length) {
    const empty = document.createElement("div");
    empty.className = "input-item muted";
    empty.textContent = "暂无附件";
    inputList.append(empty);
    return;
  }
  for (const attachment of attachments.slice(-10).reverse()) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "input-item";
    const status = attachment.status === "used" ? "✓ 已使用" : "待发送";
    const span = document.createElement("span");
    span.className = attachment.status === "used" ? "used" : "pending";
    span.textContent = "[" + status + "] " + (attachment.name || "?");
    item.append(span);
    if (attachment.status === "used") {
      item.title = "查看附件内容";
      item.addEventListener("click", () => showArtifact({name: "uploads/" + (attachment.name || "")}));
    } else {
      item.title = "将随下一条消息发送";
    }
    inputList.append(item);
  }
}

function renderSkills(session) {
  const skills = session.skills || [];
  document.querySelector("#skillCount").textContent = skills.length + " skills";
  skillList.replaceChildren();
  if (!skills.length) {
    const empty = document.createElement("span");
    empty.className = "skill-item";
    empty.textContent = "暂无 skill";
    skillList.append(empty);
  } else {
    for (const skill of skills) {
      const item = document.createElement("span");
      item.className = "skill-item";
      const name = skill.policy_name || skill.name;
      item.textContent = skill.version ? name + " v" + skill.version : name;
      item.title = skill.description || "";
      skillList.append(item);
    }
  }
}

function renderArtifacts(session) {
  const artifacts = session.artifacts || [];
  document.querySelector("#artifactCount").textContent = artifacts.length + " 项";
  artifactList.replaceChildren();
  if (!artifacts.length) {
    const empty = document.createElement("div");
    empty.className = "artifact-item";
    empty.textContent = "暂无产物";
    artifactList.append(empty);
  } else {
    for (const artifact of artifacts.slice(-8).reverse()) {
      const item = document.createElement("button");
      item.className = "artifact-item";
      item.textContent = artifact.name;
      item.type = "button";
      item.addEventListener("click", () => showArtifact(artifact));
      artifactList.append(item);
    }
  }
}

async function showArtifact(artifact) {
  try {
    const result = await api("/api/artifact?session_id=" + encodeURIComponent(state.sessionId) +
      "&name=" + encodeURIComponent(artifact.name));
    appendMessage("assistant", "Artifact: " + artifact.name + "\n" + (result.text || ""));
  } catch (error) {
    appendMessage("assistant", "产物读取失败：" + error.message);
  }
}

function renderAttachmentChips() {
  attachmentChips.replaceChildren();
  attachmentStatus.textContent = state.pendingAttachments.length
    ? state.pendingAttachments.length + " 个待发送附件（随下一条消息一起处理）"
    : "";
  for (const attachment of state.pendingAttachments) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    const name = document.createElement("span");
    name.textContent = attachment.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "移除附件";
    remove.addEventListener("click", () => {
      state.pendingAttachments = state.pendingAttachments.filter((item) => item.attachment_id !== attachment.attachment_id);
      renderAttachmentChips();
    });
    chip.append(name, remove);
    attachmentChips.append(chip);
  }
}

function renderTurnActivity(turn) {
  if (!turn) return;
  turnBadge.dataset.latest = "1";
  const actionCount = (turn.actions || []).length;
  const summaryParts = [turn.intent || "unknown"];
  if ((turn.skills || []).length) summaryParts.push("skills: " + turn.skills.join(","));
  summaryParts.push(actionCount + " action" + (actionCount === 1 ? "" : "s"));
  turnBadge.textContent = summaryParts.join(" · ");
  turnActivity.replaceChildren();
  const rows = [
    {label: "Intent", value: turn.intent || "unknown"},
    {label: "Skills", chips: turn.skills || []},
    {label: "Actions", chips: (turn.actions || []).map((action) => action.type)},
    {label: "Tools", chips: turn.tools || []},
  ];
  for (const row of rows) {
    const div = document.createElement("div");
    div.className = "row";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = row.label;
    div.append(label);
    if (row.chips) {
      const chips = document.createElement("div");
      chips.className = "chips";
      for (const value of row.chips) {
        const chip = document.createElement("span");
        chip.className = "chip" + (row.label === "Actions" ? " ok" : "");
        chip.textContent = value;
        chips.append(chip);
      }
      div.append(chips);
    } else {
      const value = document.createElement("div");
      value.className = "value";
      value.textContent = row.value;
      div.append(value);
    }
    turnActivity.append(div);
  }
}

function collectRecordSets(records, report) {
  const conflicts = new Set(report.conflicts || []);
  const accepted = [];
  const pending = [];
  for (const [path, record] of Object.entries(records)) {
    if (conflicts.has(path) || record.status === "conflict") continue;
    if (record.value === null || record.value === undefined) continue;
    if (["confirmed", "extracted", "derived"].includes(record.status)) {
      accepted.push([path, record]);
    } else if (["uncertain", "inferred"].includes(record.status)) {
      pending.push([path, record]);
    }
  }
  const missingPaths = []
    .concat(report.missing_required || [])
    .concat(report.missing_important || [])
    .concat(report.missing_optional || []);
  const missing = missingPaths.map((path) => [path, records[path] || makeSyntheticRecord(null, "missing")]);
  const conflict = Array.from(conflicts).map((path) => [path, records[path] || makeSyntheticRecord(null, "conflict")]);
  return {accepted, pending, missing, conflict};
}

function makeSyntheticRecord(value, status) {
  return {value, status, confidence: 0, evidence: [], alternatives: [], derived_from: []};
}

function renderFilterButtons() {
  for (const button of recordFilterButtons) {
    button.classList.toggle("active", button.dataset.recordFilter === state.recordFilter);
  }
}

function renderRecords(records, filterName) {
  const label = recordFilterLabels[filterName] || "字段";
  document.querySelector("#fieldCount").textContent = label + " " + records.length + " 项";
  const tree = document.querySelector("#recordsTree");
  tree.replaceChildren();
  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "tree-leaf muted";
    empty.textContent = "暂无字段";
    tree.append(empty);
    return;
  }
  const root = buildRecordTree(records);
  for (const [name, node] of sortedChildren(root)) {
    tree.append(renderTreeNode(name, node, 0));
  }
}

function buildRecordTree(records) {
  const root = {children: new Map(), record: null, path: ""};
  for (const [path, record] of records.sort(([a], [b]) => a.localeCompare(b))) {
    const parts = path.split(".");
    let current = root;
    let currentPath = "";
    for (const part of parts) {
      currentPath = currentPath ? currentPath + "." + part : part;
      if (!current.children.has(part)) {
        current.children.set(part, {children: new Map(), record: null, path: currentPath});
      }
      current = current.children.get(part);
    }
    current.record = record;
  }
  return root;
}

function renderTreeNode(name, node, depth) {
  if (!node.children.size) {
    return renderRecordLeaf(name, node.record);
  }
  const details = document.createElement("details");
  details.className = "tree-node";
  details.open = depth < 1;
  const summary = document.createElement("summary");
  summary.className = "tree-summary";
  const label = document.createElement("span");
  label.className = "tree-name";
  label.textContent = name;
  const count = document.createElement("span");
  count.className = "tree-count";
  count.textContent = countLeaves(node) + " 项";
  summary.append(label, count);
  details.append(summary);
  const children = document.createElement("div");
  children.className = "tree-children";
  for (const [childName, childNode] of sortedChildren(node)) {
    children.append(renderTreeNode(childName, childNode, depth + 1));
  }
  if (node.record) {
    children.append(renderRecordLeaf("_value", node.record));
  }
  details.append(children);
  return details;
}

function renderRecordLeaf(name, record) {
  const item = document.createElement("div");
  item.className = "tree-leaf";
  const head = document.createElement("div");
  head.className = "leaf-head";
  const label = document.createElement("span");
  label.className = "leaf-name";
  label.textContent = name;
  const status = document.createElement("span");
  status.className = "status-chip status-" + (record && record.status ? record.status : "");
  status.textContent = record && record.status ? statusLabels[record.status] || record.status : "";
  head.append(label, status);
  item.append(head);
  if (!record) return item;
  if (record.status === "missing") {
    const value = document.createElement("div");
    value.className = "leaf-value muted";
    value.textContent = "未提供";
    item.append(value);
  } else if (record.status === "conflict") {
    const details = document.createElement("details");
    details.className = "value-details";
    details.open = true;
    const summary = document.createElement("summary");
    const alternatives = record.alternatives || [];
    summary.textContent = "当前值与 " + alternatives.length + " 个候选值冲突";
    const pre = document.createElement("pre");
    pre.className = "value-json";
    pre.textContent = JSON.stringify(
      {current: record.value, alternatives: alternatives.map((item) => item.value)},
      null,
      2
    );
    details.append(summary, pre);
    item.append(details);
  } else if (isStructuredValue(record.value)) {
    const details = document.createElement("details");
    details.className = "value-details";
    const summary = document.createElement("summary");
    summary.textContent = valueSummary(record.value);
    const pre = document.createElement("pre");
    pre.className = "value-json";
    pre.textContent = JSON.stringify(record.value, null, 2);
    details.append(summary, pre);
    item.append(details);
    appendFieldMeta(item, record);
  } else {
    const value = document.createElement("div");
    value.className = "leaf-value";
    value.textContent = JSON.stringify(record.value);
    item.append(value);
    appendFieldMeta(item, record);
  }
  return item;
}

function appendFieldMeta(item, record) {
  if (record.derived_from && record.derived_from.length) {
    const note = document.createElement("div");
    note.className = "derived-note";
    note.textContent = "Derived from: " + record.derived_from.join(", ");
    item.append(note);
    const tool = record.evidence && record.evidence.length
      ? (record.evidence[0].tool || "tool") : "tool";
    const toolNote = document.createElement("div");
    toolNote.className = "derived-note";
    toolNote.textContent = "Tool: " + tool;
    item.append(toolNote);
  }
  if (record.status === "inferred") {
    const note = document.createElement("div");
    note.className = "inferred-note";
    note.textContent = "工程推测，不会进入正式 metadata";
    item.append(note);
  }
  if (record.status === "uncertain") {
    const note = document.createElement("div");
    note.className = "inferred-note";
    note.textContent = "来源模糊，待确认";
    item.append(note);
  }
  const evidence = record.evidence || [];
  if (evidence.length) {
    const list = document.createElement("ul");
    list.className = "evidence-list";
    for (const entry of evidence.slice(0, 3)) {
      const li = document.createElement("li");
      const src = document.createElement("div");
      src.className = "src";
      src.textContent = "来源：" + (entry.source_id || "?") + (entry.location ? " · " + entry.location : "");
      const text = document.createElement("div");
      text.textContent = "Evidence：" + (entry.text || "");
      li.append(src, text);
      list.append(li);
    }
    item.append(list);
  }
}

function sortedChildren(node) {
  return Array.from(node.children.entries()).sort(([a], [b]) => a.localeCompare(b));
}

function countLeaves(node) {
  let count = node.record ? 1 : 0;
  for (const child of node.children.values()) {
    count += countLeaves(child);
  }
  return count;
}

function isStructuredValue(value) {
  return value !== null && typeof value === "object";
}

function valueSummary(value) {
  if (Array.isArray(value)) return "Array(" + value.length + ")";
  return "Object(" + Object.keys(value || {}).length + ")";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result);
      let binary = "";
      const chunkSize = 32768;
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(offset, offset + chunkSize));
      }
      resolve(btoa(binary));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
}

ensureSession().catch((error) => {
  appendMessage("assistant", "初始化失败：" + error.message);
});
