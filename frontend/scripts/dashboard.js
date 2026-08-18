const API = "/api";

const state = {
  scans: [],
  stats: { total: 0, by_source: {} },
};

function $(id) {
  return document.getElementById(id);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setPill(id, text, kind) {
  const el = $(id);
  el.textContent = text;
  el.className = `pill ${kind || ""}`;
}

function sourceLabel(source) {
  return source === "external_scanner" ? "External" : "Camera";
}

function renderStats(stats) {
  state.stats = stats || { total: 0, by_source: {} };
  $("stat-total").textContent = state.stats.total || 0;
  $("stat-camera").textContent = (state.stats.by_source || {}).camera || 0;
  $("stat-hid").textContent = (state.stats.by_source || {}).external_scanner || 0;
}

function renderScans(scans) {
  state.scans = scans;
  const list = $("scan-list");
  list.innerHTML = "";
  if (!scans.length) {
    list.innerHTML = `<li class="meta">No scans yet. Point a code at the camera or use the scanner input.</li>`;
    return;
  }
  for (const scan of scans) {
    const li = document.createElement("li");
    const when = new Date(scan.timestamp).toLocaleTimeString();
    li.innerHTML = `
      <span class="badge ${scan.source}">${sourceLabel(scan.source)}</span>
      <span class="value">${escapeHtml(scan.value)}</span>
      <span class="meta">${when}<br />${escapeHtml(scan.format || "")}</span>
    `;
    list.appendChild(li);
  }
}

function prependScan(scan) {
  state.scans = [scan, ...state.scans.filter((item) => item.id !== scan.id)];
  renderScans(state.scans);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function refreshScans() {
  const data = await api("/scans");
  renderScans(data.scans || []);
  renderStats(data.stats);
}

async function refreshStatus() {
  try {
    const data = await api("/status");
    setPill("api-pill", "API online", "ok");
    const cam = data.camera || {};
    if (!(window.ScannerHub.cameraIsLive && window.ScannerHub.cameraIsLive())) {
      if (cam.running) setPill("camera-pill", `Camera ${cam.index}`, "ok");
      else if (cam.status === "error" || cam.status === "disconnected") setPill("camera-pill", cam.error || "Camera error", "bad");
      else setPill("camera-pill", "Camera idle", "");
    }

    const hid = data.scanner || {};
    if (hid.running && hid.mode === "global_hook") setPill("hid-pill", "HID hook on", "ok");
    else if (hid.status === "fallback") setPill("hid-pill", "Use input field", "warn");
    else setPill("hid-pill", "Scanner idle", "");
    renderStats(data.stats);
    return data;
  } catch (err) {
    setPill("api-pill", "API offline", "bad");
    throw err;
  }
}

function connectFeed() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${API}/ws/scans`);
  ws.addEventListener("message", (event) => {
    const scan = JSON.parse(event.data);
    prependScan(scan);
    const stats = state.stats;
    stats.total = (stats.total || 0) + 1;
    stats.by_source = stats.by_source || {};
    stats.by_source[scan.source] = (stats.by_source[scan.source] || 0) + 1;
    renderStats(stats);
  });
  ws.addEventListener("close", () => {
    setTimeout(connectFeed, 1500);
  });
}

async function submitManualScan(value) {
  const cleaned = value.trim();
  if (!cleaned) return;
  await api("/scans/manual", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value: cleaned, source: "external_scanner", format: "HID" }),
  });
}

function wireFeed() {
  $("hid-input").addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const input = event.target;
    await submitManualScan(input.value);
    input.value = "";
  });

  $("btn-clear").addEventListener("click", async () => {
    await api("/scans", { method: "DELETE" });
    renderScans([]);
    renderStats({ total: 0, by_source: {} });
  });
}

window.ScannerHub = {
  api,
  refreshScans,
  refreshStatus,
  renderStats,
};

document.addEventListener("DOMContentLoaded", async () => {
  wireFeed();
  connectFeed();
  try {
    await refreshStatus();
    await refreshScans();
  } catch (err) {
    console.error(err);
  }
});
