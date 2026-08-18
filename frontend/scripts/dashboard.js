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

function setButtonState(button, { label, busy, tone } = {}) {
  if (!button) return;
  if (!button.dataset.idleLabel) button.dataset.idleLabel = button.textContent.trim();
  button.disabled = Boolean(busy);
  button.classList.toggle("busy", Boolean(busy));
  button.classList.remove("ok", "err");
  if (tone) button.classList.add(tone);
  if (label) button.textContent = label;
  if (!busy && !label) button.textContent = button.dataset.idleLabel;
}

function resetButtonSoon(button, delay = 1600) {
  if (!button) return;
  setTimeout(() => {
    button.classList.remove("ok", "err", "busy");
    button.disabled = false;
    button.textContent = button.dataset.idleLabel || button.textContent;
  }, delay);
}

function say(message, kind) {
  const log = document.getElementById("action-log");
  if (!log) return;
  const time = new Date().toLocaleTimeString();
  log.textContent = `${time} — ${message}`;
  log.className = `action-log ${kind || ""}`;
}

async function withButton(button, busyLabel, work) {
  setButtonState(button, { label: busyLabel, busy: true });
  try {
    const result = await work();
    setButtonState(button, { busy: false, tone: "ok", label: button.dataset.doneLabel || "Done" });
    resetButtonSoon(button);
    return result;
  } catch (err) {
    setButtonState(button, { busy: false, tone: "err", label: "Failed" });
    resetButtonSoon(button);
    say(err && err.message ? err.message : "That action failed.", "bad");
    throw err;
  }
}

function setPill(id, text, kind) {
  const el = $(id);
  el.textContent = text;
  el.className = `pill ${kind || ""}`;
}

function sourceLabel(source) {
  return source === "external_scanner" ? "External" : "Camera";
}

function formatLabel(format) {
  const raw = String(format || "UNKNOWN").toUpperCase();
  const names = {
    QR_CODE: "QR code",
    QRCODE: "QR code",
    EAN_13: "EAN-13",
    EAN_8: "EAN-8",
    UPC_A: "UPC-A",
    UPC_E: "UPC-E",
    CODE_128: "Code 128",
    CODE_39: "Code 39",
    CODE_93: "Code 93",
    CODABAR: "Codabar",
    ITF: "ITF",
    DATA_MATRIX: "Data Matrix",
    PDF_417: "PDF417",
    AZTEC: "Aztec",
    HID: "HID",
  };
  return names[raw] || raw.replaceAll("_", " ");
}

function whenLabel(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

async function copyText(text) {
  const value = String(text || "");
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (err) {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

async function copyScanValue(value, button) {
  const ok = await copyText(value);
  if (!ok) {
    say("Could not copy that code.", "bad");
    return;
  }
  say(`Copied ${value}`, "ok");
  if (button) {
    const previous = button.textContent;
    button.textContent = "Copied";
    button.classList.add("ok");
    setTimeout(() => {
      button.textContent = previous;
      button.classList.remove("ok");
    }, 1200);
  }
}

function scanMetaText(scan) {
  const bits = [
    formatLabel(scan.format),
    `${String(scan.value || "").length} chars`,
    sourceLabel(scan.source),
    whenLabel(scan.timestamp),
  ].filter(Boolean);
  return bits.join(" · ");
}

function updateLastScan(scan) {
  const box = $("last-scan");
  if (!box) return;
  if (!scan) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("last-scan-value").textContent = scan.value;
  $("last-scan-meta").textContent = scanMetaText(scan);
  const copyBtn = $("btn-copy-last");
  if (copyBtn) copyBtn.dataset.value = scan.value;
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
    updateLastScan(null);
    return;
  }
  updateLastScan(scans[0]);
  for (const scan of scans) {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = `badge ${scan.source}`;
    badge.textContent = sourceLabel(scan.source);

    const body = document.createElement("div");
    body.className = "scan-body";
    const value = document.createElement("div");
    value.className = "value";
    value.textContent = scan.value;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = scanMetaText(scan);
    body.append(value, meta);

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "ghost copy-btn";
    copyBtn.textContent = "Copy";
    copyBtn.title = "Copy this code";
    copyBtn.addEventListener("click", () => copyScanValue(scan.value, copyBtn));

    li.append(badge, body, copyBtn);
    list.appendChild(li);
  }
}

function prependScan(scan) {
  const exists = state.scans.some((item) => item.id === scan.id);
  state.scans = [scan, ...state.scans.filter((item) => item.id !== scan.id)];
  renderScans(state.scans);
  if (exists) return;
  state.stats.total = (state.stats.total || 0) + 1;
  state.stats.by_source = state.stats.by_source || {};
  state.stats.by_source[scan.source] = (state.stats.by_source[scan.source] || 0) + 1;
  renderStats(state.stats);
  playScanBeep(scan.source);
}

let audioCtx = null;

function getAudioContext() {
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (!Ctor) return null;
  if (!audioCtx) audioCtx = new Ctor();
  return audioCtx;
}

function unlockScanAudio() {
  const ctx = getAudioContext();
  if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
}

function playScanBeep(source) {
  const ctx = getAudioContext();
  if (!ctx) return;
  const play = () => {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = source === "external_scanner" ? 660 : 880;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.22, now + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.16);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.18);
  };
  if (ctx.state === "suspended") {
    ctx.resume().then(play).catch(() => {});
    return;
  }
  try {
    play();
  } catch (err) {
    console.warn("Could not play scan beep", err);
  }
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
    say("Cannot reach the backend. Is python backend/app.py still running?", "bad");
    throw err;
  }
}

function connectFeed() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${API}/ws/scans`);
  ws.addEventListener("message", (event) => {
    const scan = JSON.parse(event.data);
    prependScan(scan);
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
    window.ScannerHub.say(`Logged hardware scan: ${input.value.trim()}`, "ok");
    input.value = "";
  });

  $("btn-copy-last").addEventListener("click", () => {
    const value = $("btn-copy-last").dataset.value || ($("last-scan-value") && $("last-scan-value").textContent);
    copyScanValue(value, $("btn-copy-last"));
  });
  $("btn-copy-all").addEventListener("click", async () => {
    if (!state.scans.length) {
      say("Nothing to copy yet.", "warn");
      return;
    }
    const text = state.scans
      .map((scan) => `${scan.value}\t${formatLabel(scan.format)}\t${sourceLabel(scan.source)}\t${whenLabel(scan.timestamp)}`)
      .join("\n");
    const ok = await copyText(text);
    say(ok ? `Copied ${state.scans.length} scan(s).` : "Could not copy the scan list.", ok ? "ok" : "bad");
  });

  $("btn-clear").addEventListener("click", async () => {
    const button = $("btn-clear");
    await window.ScannerHub.withButton(button, "Clearing history…", async () => {
      await api("/scans", { method: "DELETE" });
      renderScans([]);
      renderStats({ total: 0, by_source: {} });
      updateLastScan(null);
      window.ScannerHub.say("Scan history cleared on this machine. New scans will show up below.", "ok");
    });
  });
}

window.ScannerHub = {
  api,
  refreshScans,
  refreshStatus,
  renderStats,
  prependScan,
  playScanBeep,
  say,
  setButtonState,
  resetButtonSoon,
  withButton,
};

document.addEventListener("DOMContentLoaded", async () => {
  document.addEventListener("pointerdown", unlockScanAudio, { capture: true });
  document.addEventListener("keydown", unlockScanAudio, { capture: true });
  wireFeed();
  connectFeed();
  try {
    await refreshStatus();
    await refreshScans();
  } catch (err) {
    console.error(err);
  }
});
