const CAMERA_STORAGE_KEY = "scannerhub.cameraDeviceId";

const cameraState = {
  stream: null,
  scanTimer: null,
  detector: null,
  deviceId: storedCameraId(),
  busy: false,
  warnedMissingDecoder: false,
  starting: false,
  zxingReader: null,
  zxingPure: null,
  zxingBrowser: null,
  frames: 0,
  misses: 0,
  backendReleased: false,
  imageCapture: null,
  snapping: false,
  snapTimer: null,
  confirmValue: "",
  confirmCount: 0,
};

function storedCameraId() {
  try {
    return localStorage.getItem(CAMERA_STORAGE_KEY) || "";
  } catch (err) {
    return "";
  }
}

function rememberCameraId(deviceId) {
  cameraState.deviceId = deviceId || "";
  try {
    if (deviceId) localStorage.setItem(CAMERA_STORAGE_KEY, deviceId);
  } catch (err) {
    /* ignore quota / private mode */
  }
}

function previewEl() {
  return document.getElementById("preview");
}

function emptyEl() {
  return document.getElementById("preview-empty");
}

function permissionEl() {
  return document.getElementById("camera-permission");
}

function setCameraPill(text, kind) {
  const el = document.getElementById("camera-pill");
  el.textContent = text;
  el.className = `pill ${kind || ""}`;
}

function showLivePreview(on) {
  const video = previewEl();
  emptyEl().style.display = on ? "none" : "grid";
  permissionEl().hidden = true;
  document.getElementById("scan-reticle").hidden = !on;
  const debug = document.getElementById("scan-debug");
  if (debug) debug.hidden = !on;
  if (on) video.classList.add("visible");
  else video.classList.remove("visible");
}

function showPermissionHelp(message) {
  stopScanLoop();
  const video = previewEl();
  video.classList.remove("visible");
  emptyEl().style.display = "none";
  permissionEl().hidden = false;
  document.getElementById("camera-permission-text").textContent = message;
  setCameraPill("Camera blocked", "bad");
  window.ScannerHub.say(message, "bad");
}

async function releaseBackendCamera() {
  if (cameraState.backendReleased) return;
  cameraState.backendReleased = true;
  try {
    await window.ScannerHub.api("/camera/stop", { method: "POST" });
  } catch (err) {
    console.warn("Could not release backend camera", err);
  }
}

function isRealDeviceId(value) {
  return Boolean(value) && !String(value).startsWith("__idx_");
}

function setCameraListLabel(text) {
  const label = document.getElementById("camera-list-label");
  if (label) label.textContent = text;
}

function renderCameraChoices(cameras, selectedId) {
  const list = document.getElementById("camera-choices");
  if (!list) return;
  list.innerHTML = "";
  list.hidden = false;
  const items = cameras.length
    ? cameras
    : [{ id: "", label: "Default camera" }];
  items.forEach((device) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "camera-choice" + (device.id === selectedId ? " active" : "");
    button.textContent = device.label;
    button.addEventListener("click", () => chooseCamera(device.id));
    list.appendChild(button);
  });
}

async function listBrowserCameras(selectedId) {
  const select = document.getElementById("camera-select");
  select.disabled = false;
  select.hidden = false;

  const cameras = [];
  if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    const devices = await navigator.mediaDevices.enumerateDevices();
    devices
      .filter((device) => device.kind === "videoinput")
      .forEach((device, index) => {
        cameras.push({
          id: device.deviceId || `__idx_${index}`,
          label: device.label || `Camera ${index + 1}`,
        });
      });
  }

  const wanted = selectedId || cameraState.deviceId || "";
  select.innerHTML = "";
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = "Default camera";
  select.appendChild(fallback);

  cameras.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = device.label;
    select.appendChild(option);
  });

  const selectable = ["", ...cameras.map((device) => device.id)];
  if (wanted && selectable.includes(wanted)) {
    select.value = wanted;
  }
  select.size = Math.max(3, Math.min(cameras.length + 1, 8));
  renderCameraChoices(cameras, select.value);
  const named = cameras.filter((device) => device.label && !device.label.startsWith("Camera ")).length;
  setCameraListLabel(
    cameras.length
      ? `Device (${cameras.length} found${named ? "" : ", names appear after Allow"})`
      : "Device (none listed yet — click Start camera)",
  );
}

function chooseCamera(deviceId) {
  if (cameraState.starting) return;
  const select = document.getElementById("camera-select");
  if (select) select.value = deviceId || "";
  const real = isRealDeviceId(deviceId) ? deviceId : "";
  if (cameraState.stream && real && real === cameraState.deviceId) {
    window.ScannerHub.say("That camera is already running.", "ok");
    return;
  }
  startBrowserCamera();
}

function stopTracks() {
  if (!cameraState.stream) return;
  cameraState.stream.getTracks().forEach((track) => track.stop());
  cameraState.stream = null;
  cameraState.imageCapture = null;
  previewEl().srcObject = null;
}

function attachStreamWatch(stream) {
  const track = stream.getVideoTracks()[0];
  if (!track) return;
  track.addEventListener("ended", () => {
    if (cameraState.starting) return;
    cameraState.stream = null;
    cameraState.imageCapture = null;
    stopScanLoop();
    previewEl().srcObject = null;
    showLivePreview(false);
    setCameraPill("Camera dropped", "warn");
    window.ScannerHub.say("The camera turned itself off. Click Start camera to open it again.", "warn");
  });
}

function stopScanLoop() {
  if (cameraState.scanTimer) {
    clearInterval(cameraState.scanTimer);
    cameraState.scanTimer = null;
  }
  if (cameraState.snapTimer) {
    clearInterval(cameraState.snapTimer);
    cameraState.snapTimer = null;
  }
  if (cameraState.zxingBrowser) {
    try {
      cameraState.zxingBrowser.stopContinuousDecode();
    } catch (err) {
      /* ignore */
    }
    try {
      cameraState.zxingBrowser.reset();
    } catch (err) {
      /* ignore */
    }
    cameraState.zxingBrowser = null;
  }
}

async function openCameraStream(deviceId) {
  const videoBase = { width: { ideal: 1920 }, height: { ideal: 1080 } };
  const attempts = [];
  if (deviceId) {
    attempts.push({ video: { ...videoBase, deviceId: { exact: deviceId } }, audio: false });
    attempts.push({ video: { deviceId: { exact: deviceId } }, audio: false });
  } else {
    attempts.push({ video: { ...videoBase, facingMode: { ideal: "environment" } }, audio: false });
  }
  attempts.push({ video: { width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
  attempts.push({ video: true, audio: false });

  let lastError = null;
  for (const constraints of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error("Could not start the camera.");
}

async function tuneTrack(track) {
  if (!track || typeof track.getCapabilities !== "function") return;
  try {
    const caps = track.getCapabilities() || {};
    const advanced = {};
    if (Array.isArray(caps.focusMode) && caps.focusMode.includes("continuous")) {
      advanced.focusMode = "continuous";
    } else if (Array.isArray(caps.focusMode) && caps.focusMode.includes("manual") && caps.focusDistance) {
      const min = Number(caps.focusDistance.min) || 0;
      const max = Number(caps.focusDistance.max) || 1;
      advanced.focusMode = "manual";
      advanced.focusDistance = min + (max - min) * 0.18;
    }
    if (Array.isArray(caps.exposureMode) && caps.exposureMode.includes("continuous")) {
      advanced.exposureMode = "continuous";
    }
    if (caps.exposureCompensation && caps.exposureCompensation.max != null) {
      advanced.exposureCompensation = Math.min(Number(caps.exposureCompensation.max), 2);
    }
    if (caps.brightness && caps.brightness.max != null) {
      const min = Number(caps.brightness.min) || 0;
      const max = Number(caps.brightness.max) || 1;
      advanced.brightness = min + (max - min) * 0.7;
    }
    if (Array.isArray(caps.whiteBalanceMode) && caps.whiteBalanceMode.includes("continuous")) {
      advanced.whiteBalanceMode = "continuous";
    }
    if (caps.width && caps.width.max) {
      advanced.width = Math.min(1920, caps.width.max);
    }
    if (Object.keys(advanced).length) {
      await track.applyConstraints({ advanced: [advanced] });
    }
  } catch (err) {
    console.warn("Could not tune camera focus/resolution", err);
  }
}

async function startBrowserCamera() {
  if (cameraState.starting) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showPermissionHelp(`This browser cannot access a camera. Use Chrome or Firefox on ${location.origin}/`);
    return;
  }

  const select = document.getElementById("camera-select");
  const raw = (select && select.value) || cameraState.deviceId || "";
  const deviceId = isRealDeviceId(raw) ? raw : undefined;
  if (cameraState.stream && deviceId && deviceId === cameraState.deviceId) {
    if (!cameraState.scanTimer) startScanLoop();
    window.ScannerHub.say("Camera is already running. Hold a code inside the green box.", "ok");
    return;
  }

  cameraState.starting = true;
  const startBtn = document.getElementById("btn-start-camera");
  window.ScannerHub.setButtonState(startBtn, { label: "Asking for camera…", busy: true });
  setCameraPill("Waiting for permission", "warn");
  window.ScannerHub.say("Browser permission prompt should appear. Choose Allow so the preview can start.", "warn");

  try {
    stopScanLoop();
    // Linux V4L2 usually cannot open a second node while the first stream is still live.
    stopTracks();
    await releaseBackendCamera();

    const stream = await openCameraStream(deviceId);
    cameraState.stream = stream;
    attachStreamWatch(stream);

    const video = previewEl();
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    try {
      await video.play();
    } catch (err) {
      console.warn(err);
    }

    const track = stream.getVideoTracks()[0];
    await tuneTrack(track);
    const openedId = (track && track.getSettings().deviceId) || deviceId || "";
    rememberCameraId(openedId);
    await listBrowserCameras(openedId);
    showLivePreview(true);
    setCameraPill(track && track.label ? track.label : "Camera on", "ok");
    if (video.readyState < 2) {
      await new Promise((resolve) => video.addEventListener("loadeddata", resolve, { once: true }));
    }
    startScanLoop();
    const name = track && track.label ? track.label : "webcam";
    window.ScannerHub.setButtonState(startBtn, { busy: false, tone: "ok", label: "Camera running" });
    window.ScannerHub.resetButtonSoon(startBtn, 1800);
    if (deviceId && openedId && deviceId !== openedId) {
      window.ScannerHub.say(`Could not open the selected camera. Using ${name} instead.`, "warn");
    } else {
      window.ScannerHub.say(
        `Camera is live (${name}). For printed labels: hold the item 12–18 inches away, under a lamp, fill the green box, and keep it still. Screen codes are easier than paper.`,
        "ok",
      );
    }
  } catch (err) {
    window.ScannerHub.setButtonState(startBtn, { busy: false, tone: "err", label: "Camera failed" });
    window.ScannerHub.resetButtonSoon(startBtn);
    handleGetUserMediaError(err);
  } finally {
    cameraState.starting = false;
  }
}

window.ScannerHub = window.ScannerHub || {};
window.ScannerHub.cameraIsLive = () => Boolean(cameraState.stream);

function handleGetUserMediaError(err) {
  const name = err && err.name;
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    showPermissionHelp("Camera permission was denied. Click Allow camera, then choose Allow in the browser prompt. If that is gone, click the camera icon in the address bar and set it to Allow.");
    return;
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    showPermissionHelp("No camera was found, or the selected camera is not available.");
    return;
  }
  if (name === "NotReadableError") {
    showPermissionHelp("The camera is in use by another app. Close other video programs and try again.");
    return;
  }
  showPermissionHelp(err && err.message ? err.message : "Could not start the camera.");
}

function startScanLoop() {
  stopScanLoop();
  cameraState.zxingReader = null;
  cameraState.zxingPure = null;
  cameraState.zxingBrowser = null;
  cameraState.detector = null;
  cameraState.imageCapture = null;
  cameraState.frames = 0;
  cameraState.misses = 0;
  cameraState.confirmValue = "";
  cameraState.confirmCount = 0;
  cameraState.detector = createBarcodeDetector();
  setScanHint("Looking for printed barcodes. Serials and MACs are logged only after a checksum-valid, confirmed read.");
  warnIfDecoderMissing();
  cameraState.scanTimer = setInterval(scanCurrentFrame, 280);
}

async function warnIfDecoderMissing() {
  try {
    const data = await window.ScannerHub.api("/status");
    const engines = data.decoder || {};
    if (!engines.zxingcpp && !engines.pyzbar) {
      window.ScannerHub.say(
        "Native barcode decoder is not loaded. Stop the app and restart python backend/app.py after installing zxing-cpp.",
        "bad",
      );
      setScanHint("Native decoder missing. Restart python backend/app.py so zxing-cpp can load.");
    } else if (!engines.zxingcpp) {
      window.ScannerHub.say("zxing-cpp is not loaded. Printed labels will be weak until the backend is restarted.", "warn");
    }
  } catch (err) {
    window.ScannerHub.say("Cannot reach the backend. Start python backend/app.py first.", "bad");
  }
}

function runDecoderSelfTest() {
  try {
    const canvas = buildTestQrCanvas("SCANNERHUB-OK");
    if (!canvas) return false;
    const found = decodeWithJsQR(canvas) || decodeWithZxing(canvas);
    if (found && found.value) {
      window.ScannerHub.say(`Decoder self-test passed (read "${found.value}"). Point a printed code at the camera.`, "ok");
      return true;
    }
    window.ScannerHub.say("Decoder self-test failed on a generated QR. Check that jsQR.js and zxing.min.js loaded.", "bad");
    return false;
  } catch (err) {
    window.ScannerHub.say(`Decoder self-test error: ${err && err.message ? err.message : err}`, "bad");
    return false;
  }
}

function buildTestQrCanvas(text) {
  const zxing = window.ZXing;
  if (!zxing || !zxing.QRCodeWriter || !zxing.BarcodeFormat) return null;
  const writer = new zxing.QRCodeWriter();
  // This UMD build treats a missing hints arg as present (null !== undefined)
  // and then calls hints.get(), which throws "can't access property get, i is undefined".
  const hints = new Map();
  const matrix = writer.encode(text, zxing.BarcodeFormat.QR_CODE, 180, 180, hints);
  if (!matrix || typeof matrix.get !== "function") return null;
  const width = typeof matrix.getWidth === "function" ? matrix.getWidth() : matrix.width;
  const height = typeof matrix.getHeight === "function" ? matrix.getHeight() : matrix.height;
  if (!width || !height) return null;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#000000";
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (matrix.get(x, y)) ctx.fillRect(x, y, 1, 1);
    }
  }
  return canvas;
}

function setScanHint(text) {
  const hint = document.getElementById("scan-hint");
  if (hint) hint.textContent = text;
}

function canvasToJpeg(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Could not encode the camera frame."));
      },
      "image/jpeg",
      quality == null ? 0.95 : quality,
    );
  });
}

async function decodeOnBackend(canvas) {
  const blob = await canvasToJpeg(canvas, 0.92);
  const body = new FormData();
  body.append("file", blob, "frame.jpg");
  const response = await fetch("/api/camera/frame", { method: "POST", body });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const data = await response.json();
  cameraState.lastDebug = data.debug || {};
  const hits = data.hits || [];
  const scans = data.scans || [];
  for (const scan of scans) {
    if (window.ScannerHub.prependScan) window.ScannerHub.prependScan(scan);
  }
  const debug = cameraState.lastDebug;
  if (!debug.zxingcpp && !debug.pyzbar && !cameraState.warnedMissingDecoder) {
    cameraState.warnedMissingDecoder = true;
    window.ScannerHub.say(
      "Frames are reaching the backend, but no native decoder is loaded. Restart python backend/app.py.",
      "bad",
    );
  }
  if (hits.length) {
    const first = hits[0];
    if (first.confidence === "confirm" && !scans.length) {
      return acceptConfirmedHit(first);
    }
    cameraState.confirmValue = "";
    cameraState.confirmCount = 0;
    if (scans.length) {
      setScanHint(`Native decoder read ${first.value} · ${String(first.format || "code").replaceAll("_", " ")}`);
      window.ScannerHub.say(`Camera scan logged: ${first.value}`, "ok");
    } else {
      setScanHint(`Still seeing ${first.value} — ignored as a duplicate`);
    }
    return { value: first.value, format: first.format, fromBackend: true };
  }
  cameraState.confirmValue = "";
  cameraState.confirmCount = 0;
  return null;
}

function acceptConfirmedHit(hit) {
  const value = String(hit.value || "").trim();
  if (!value) return null;
  if (cameraState.confirmValue === value) {
    cameraState.confirmCount += 1;
  } else {
    cameraState.confirmValue = value;
    cameraState.confirmCount = 1;
    setScanHint(`Saw ${value} once — hold still so the next frame can confirm it.`);
    return null;
  }
  if (cameraState.confirmCount < 2) {
    setScanHint(`Confirming ${value}… keep the label still.`);
    return null;
  }
  cameraState.confirmValue = "";
  cameraState.confirmCount = 0;
  return { value, format: hit.format, fromBackend: false };
}

async function reportScan(value, format) {
  const cleaned = String(value || "").trim();
  if (!cleaned) return false;
  const data = await window.ScannerHub.api("/scans/manual", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      value: cleaned,
      source: "camera",
      format: String(format || "UNKNOWN").toUpperCase(),
    }),
  });
  if (data && data.scan && window.ScannerHub.prependScan) {
    window.ScannerHub.prependScan(data.scan);
  }
  if (data && data.suppressed) {
    setScanHint(`Still seeing ${cleaned} — ignored as a duplicate`);
  } else {
    setScanHint(`Scanned ${cleaned} · ${String(format || "code").replaceAll("_", " ")}`);
    window.ScannerHub.say(`Camera scan logged: ${cleaned}`, "ok");
  }
  return true;
}

function paintVideo(video, canvas, width, height) {
  canvas.width = Math.max(1, width);
  canvas.height = Math.max(1, height);
  const ctx = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return ctx;
}

function photoScore(ctx, width, height) {
  const sw = Math.min(width, 160);
  const sh = Math.min(height, 96);
  if (!sw || !sh) return 0;
  const sample = ctx.getImageData(0, 0, sw, sh).data;
  const hist = new Uint32Array(16);
  const seen = new Uint8Array(4096);
  let unique = 0;
  const n = sample.length / 4;
  for (let i = 0; i < sample.length; i += 4) {
    hist[sample[i] >> 4] += 1;
    const key = (sample[i] >> 4) * 256 + (sample[i + 1] >> 4) * 16 + (sample[i + 2] >> 4);
    if (!seen[key]) {
      seen[key] = 1;
      unique += 1;
    }
  }
  let entropy = 0;
  for (let i = 0; i < hist.length; i += 1) {
    if (!hist[i]) continue;
    const p = hist[i] / n;
    entropy -= p * Math.log2(p);
  }
  const ranked = Array.from(hist).sort((a, b) => b - a);
  const twoTone = ranked[0] + ranked[1] > n * 0.92;
  if (twoTone && unique < 24) return 0;
  return unique + entropy * 12;
}

function grabFrame(video) {
  const canvas = grabFrame.canvas || document.createElement("canvas");
  grabFrame.canvas = canvas;
  const scratch = grabFrame.scratch || document.createElement("canvas");
  grabFrame.scratch = scratch;
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return canvas;

  // Never copy 1:1 native pixels on Linux — that path often dumps YUV as RGB
  // (gray/red bands). Scaling forces an RGB conversion.
  const candidates = [
    { w: 1280, h: Math.max(1, Math.round((1280 * vh) / vw)) },
    { w: Math.max(2, video.clientWidth * 2), h: Math.max(2, video.clientHeight * 2) },
    { w: Math.max(2, video.clientWidth), h: Math.max(2, video.clientHeight) },
  ];
  let best = null;
  let bestScore = -1;
  for (const size of candidates) {
    const ctx = paintVideo(video, scratch, size.w, size.h);
    const score = photoScore(ctx, scratch.width, scratch.height);
    if (score > bestScore) {
      bestScore = score;
      best = size;
      canvas.width = scratch.width;
      canvas.height = scratch.height;
      canvas.getContext("2d", { alpha: false, willReadFrequently: true }).drawImage(scratch, 0, 0);
    }
  }
  canvas.dataset.photoScore = String(Math.round(bestScore));
  return canvas;
}

function cropForPrint(frame, video) {
  const crop = reticleCrop(frame, video);
  const dest = workCanvas("backendCrop");
  const long = Math.max(crop.w, crop.h, 1);
  const scale = Math.min(3.2, Math.max(1.5, 1000 / long));
  copyRegion(frame, dest, crop.x, crop.y, crop.w, crop.h, scale, true);
  return dest;
}

function copyRegion(source, dest, sx, sy, sw, sh, scale, smooth) {
  dest.width = Math.max(1, Math.round(sw * scale));
  dest.height = Math.max(1, Math.round(sh * scale));
  const ctx = dest.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingEnabled = Boolean(smooth);
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, dest.width, dest.height);
  return dest;
}

function rotateCanvas90(source, dest) {
  dest.width = source.height;
  dest.height = source.width;
  const ctx = dest.getContext("2d", { willReadFrequently: true });
  ctx.save();
  ctx.translate(dest.width, 0);
  ctx.rotate(Math.PI / 2);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(source, 0, 0);
  ctx.restore();
  return dest;
}

function workCanvas(name) {
  workCanvas.map = workCanvas.map || {};
  if (!workCanvas.map[name]) workCanvas.map[name] = document.createElement("canvas");
  return workCanvas.map[name];
}

function clampRect(x, y, w, h, maxW, maxH) {
  let sx = Math.max(0, Math.floor(x));
  let sy = Math.max(0, Math.floor(y));
  let sw = Math.max(12, Math.floor(w));
  let sh = Math.max(12, Math.floor(h));
  if (sx + sw > maxW) sw = Math.max(12, maxW - sx);
  if (sy + sh > maxH) sh = Math.max(12, maxH - sy);
  return { x: sx, y: sy, w: sw, h: sh };
}

function reticleCrop(frame, video) {
  const wrap = video && video.parentElement;
  const reticle = document.getElementById("scan-reticle");
  if (!wrap || !video || !reticle || reticle.hidden) {
    const mx = Math.floor(frame.width * 0.12);
    const my = Math.floor(frame.height * 0.18);
    return clampRect(mx, my, frame.width - mx * 2, frame.height - my * 2, frame.width, frame.height);
  }
  const fit = window.getComputedStyle(video).objectFit || "cover";
  const wrapW = wrap.clientWidth;
  const wrapH = wrap.clientHeight;
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  const scale = fit === "cover" ? Math.max(wrapW / vw, wrapH / vh) : Math.min(wrapW / vw, wrapH / vh);
  const offX = (wrapW - vw * scale) / 2;
  const offY = (wrapH - vh * scale) / 2;
  const wrapRect = wrap.getBoundingClientRect();
  const retRect = reticle.getBoundingClientRect();
  const rx = retRect.left - wrapRect.left;
  const ry = retRect.top - wrapRect.top;
  const frameScaleX = frame.width / vw;
  const frameScaleY = frame.height / vh;
  const x = ((rx - offX) / scale) * frameScaleX;
  const y = ((ry - offY) / scale) * frameScaleY;
  const w = (retRect.width / scale) * frameScaleX;
  const h = (retRect.height / scale) * frameScaleY;
  return clampRect(x, y, w, h, frame.width, frame.height);
}

function enhancePrint(canvas) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = image.data;
  const count = data.length / 4;
  const hist = new Uint32Array(256);
  for (let i = 0; i < data.length; i += 4) {
    const luma = (data[i] * 77 + data[i + 1] * 150 + data[i + 2] * 29) >> 8;
    data[i] = luma;
    hist[luma] += 1;
  }
  const lowTarget = count * 0.02;
  const highTarget = count * 0.98;
  let acc = 0;
  let lo = 0;
  let hi = 255;
  for (let value = 0; value < 256; value += 1) {
    acc += hist[value];
    if (acc >= lowTarget) {
      lo = value;
      break;
    }
  }
  acc = 0;
  for (let value = 0; value < 256; value += 1) {
    acc += hist[value];
    if (acc >= highTarget) {
      hi = value;
      break;
    }
  }
  if (hi <= lo) hi = lo + 1;
  const stretch = 255 / (hi - lo);
  for (let i = 0; i < data.length; i += 4) {
    const stretched = Math.max(0, Math.min(255, Math.round((data[i] - lo) * stretch)));
    data[i] = data[i + 1] = data[i + 2] = stretched;
  }
  ctx.putImageData(image, 0, 0);
  if (canvas.width * canvas.height < 900000) sharpenCanvas(canvas);
  return canvas;
}

function sharpenCanvas(canvas) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const src = image.data;
  const copy = new Uint8ClampedArray(src);
  const width = canvas.width;
  const height = canvas.height;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const i = (y * width + x) * 4;
      const value = 5 * copy[i] - copy[i - 4] - copy[i + 4] - copy[i - width * 4] - copy[i + width * 4];
      const clipped = value < 0 ? 0 : value > 255 ? 255 : value;
      src[i] = src[i + 1] = src[i + 2] = clipped;
    }
  }
  ctx.putImageData(image, 0, 0);
}

function isMatrixFormat(format) {
  const key = String(format || "").toUpperCase().replace(/[\s_-]/g, "");
  return key.includes("QR") || key.includes("DATAMATRIX") || key.includes("PDF417") || key.includes("AZTEC");
}

function decodeWithJsQR(canvas) {
  const decoder = typeof jsQR === "function" ? jsQR : window.jsQR;
  if (typeof decoder !== "function") return null;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const width = canvas.width;
  const height = canvas.height;
  if (!width || !height) return null;
  const full = ctx.getImageData(0, 0, width, height);
  const result = decoder(full.data, width, height, { inversionAttempts: "attemptBoth" });
  if (result && result.data) return { value: result.data, format: "QR_CODE" };
  return null;
}

function createBarcodeDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    return new BarcodeDetector({
      formats: [
        "aztec",
        "code_128",
        "code_39",
        "code_93",
        "codabar",
        "data_matrix",
        "ean_13",
        "ean_8",
        "itf",
        "pdf417",
        "qr_code",
        "upc_a",
        "upc_e",
      ],
    });
  } catch (err) {
    try {
      return new BarcodeDetector();
    } catch (inner) {
      return null;
    }
  }
}

async function decodeWithDetector(source) {
  if (!cameraState.detector || !source) return null;
  try {
    const codes = await cameraState.detector.detect(source);
    for (const code of codes) {
      const value = (code.rawValue || "").trim();
      if (value) return { value, format: String(code.format || "CODE").toUpperCase() };
    }
  } catch (err) {
    cameraState.detector = null;
  }
  return null;
}

function barcodeFormats() {
  const zxing = window.ZXing;
  return [
    zxing.BarcodeFormat.EAN_13,
    zxing.BarcodeFormat.EAN_8,
    zxing.BarcodeFormat.UPC_A,
    zxing.BarcodeFormat.UPC_E,
    zxing.BarcodeFormat.CODE_128,
    zxing.BarcodeFormat.CODE_39,
    zxing.BarcodeFormat.CODE_93,
    zxing.BarcodeFormat.CODABAR,
    zxing.BarcodeFormat.ITF,
    zxing.BarcodeFormat.QR_CODE,
    zxing.BarcodeFormat.DATA_MATRIX,
    zxing.BarcodeFormat.AZTEC,
    zxing.BarcodeFormat.PDF_417,
  ];
}

function makeZxingReader(pure) {
  const zxing = window.ZXing;
  if (!zxing || !zxing.MultiFormatReader) return null;
  const reader = new zxing.MultiFormatReader();
  if (zxing.DecodeHintType && zxing.BarcodeFormat) {
    const hints = new Map();
    hints.set(zxing.DecodeHintType.TRY_HARDER, true);
    if (pure && zxing.DecodeHintType.PURE_BARCODE != null) {
      hints.set(zxing.DecodeHintType.PURE_BARCODE, true);
    }
    hints.set(zxing.DecodeHintType.POSSIBLE_FORMATS, barcodeFormats());
    reader.setHints(hints);
  }
  return reader;
}

function getZxingReader() {
  if (!cameraState.zxingReader) cameraState.zxingReader = makeZxingReader(false);
  return cameraState.zxingReader;
}

function getZxingPureReader() {
  if (!cameraState.zxingPure) cameraState.zxingPure = makeZxingReader(true);
  return cameraState.zxingPure;
}

function zxingFormatName(result) {
  const zxing = window.ZXing;
  try {
    const raw = result.getBarcodeFormat();
    if (zxing && zxing.BarcodeFormat && zxing.BarcodeFormat[raw] != null) {
      return String(zxing.BarcodeFormat[raw]);
    }
    return String(raw);
  } catch (err) {
    return "CODE";
  }
}

function decodeWithZxing(canvas, binarizerKind, reader) {
  const zxing = window.ZXing;
  const active = reader || getZxingReader();
  if (!active || !zxing || !zxing.HTMLCanvasElementLuminanceSource) return null;
  const Binarizer = binarizerKind === "global" && zxing.GlobalHistogramBinarizer
    ? zxing.GlobalHistogramBinarizer
    : zxing.HybridBinarizer;
  if (!Binarizer) return null;
  try {
    const source = new zxing.HTMLCanvasElementLuminanceSource(canvas);
    const attempts = [new zxing.BinaryBitmap(new Binarizer(source))];
    if (typeof source.invert === "function") {
      attempts.push(new zxing.BinaryBitmap(new Binarizer(source.invert())));
    }
    for (const bitmap of attempts) {
      try {
        const result = active.decode(bitmap);
        active.reset();
        const value = result.getText();
        if (value) return { value, format: zxingFormatName(result) };
      } catch (err) {
        active.reset();
      }
    }
  } catch (err) {
    try {
      active.reset();
    } catch (resetErr) {
      /* ignore */
    }
  }
  return null;
}

function decodeCanvasSet(canvas) {
  return (
    decodeWithZxing(canvas, "global", getZxingPureReader()) ||
    decodeWithZxing(canvas, "global") ||
    decodeWithZxing(canvas, "hybrid") ||
    decodeWithJsQR(canvas)
  );
}

function decodePrinted(frame, video) {
  const crop = reticleCrop(frame, video);
  const print = workCanvas("print");
  const scale = Math.max(2, Math.min(3.2, 900 / Math.max(crop.w, 1)));
  copyRegion(frame, print, crop.x, crop.y, crop.w, crop.h, scale, false);
  enhancePrint(print);
  let found = decodeCanvasSet(print);
  if (found) return found;

  const band = workCanvas("band");
  const offsets = [0.08, 0.28, 0.48, 0.68];
  const idx = cameraState.frames % offsets.length;
  const y = Math.floor(print.height * offsets[idx]);
  const h = Math.max(36, Math.floor(print.height * 0.32));
  copyRegion(print, band, 0, y, print.width, Math.min(h, print.height - y), 1, false);
  found = decodeWithZxing(band, "global", getZxingPureReader()) || decodeWithZxing(band, "global");
  if (found) return found;

  if (cameraState.frames % 2 === 0) {
    const rotated = workCanvas("rotated");
    rotateCanvas90(print, rotated);
    found = decodeCanvasSet(rotated);
    if (found) return found;
  }

  const raw = workCanvas("raw");
  copyRegion(frame, raw, crop.x, crop.y, crop.w, crop.h, scale, false);
  return decodeCanvasSet(raw) || decodeWithZxing(frame, "hybrid") || decodeWithJsQR(frame);
}

async function decodeFrame(canvas, video) {
  const fromVideo = await decodeWithDetector(video);
  if (fromVideo) return fromVideo;
  const fromCanvas = await decodeWithDetector(canvas);
  if (fromCanvas) return fromCanvas;
  const found = decodePrinted(canvas, video);
  if (found) return found;
  const print = workCanvas.map && workCanvas.map.print;
  if (print) {
    const fromPrint = await decodeWithDetector(print);
    if (fromPrint) return fromPrint;
  }
  return null;
}

function showDecodePreview(canvas) {
  const debug = document.getElementById("scan-debug");
  if (!debug || !canvas) return;
  const ctx = debug.getContext("2d");
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, debug.width, debug.height);
  ctx.drawImage(canvas, 0, 0, debug.width, debug.height);
}

async function scanCurrentFrame() {
  if (cameraState.busy || !cameraState.stream) return;
  const video = previewEl();
  cameraState.frames += 1;
  if (!video.videoWidth) {
    if (cameraState.frames % 15 === 0) {
      setScanHint("Camera is on but no video frames yet. Wait a second or pick another device.");
    }
    return;
  }
  cameraState.busy = true;
  try {
    const canvas = grabFrame(video);
    const crop = cropForPrint(canvas, video);
    showDecodePreview(crop);
    let found = null;
    try {
      found = await decodeOnBackend(crop);
      if (!found) found = await decodeOnBackend(canvas);
    } catch (err) {
      console.warn("Native decoder request failed", err);
    }
    if (!found && cameraState.frames % 3 === 0) {
      const qr = decodeWithJsQR(crop) || decodeWithJsQR(canvas);
      if (qr) found = qr;
    }
    if (found) {
      cameraState.misses = 0;
      if (!found.fromBackend) await reportScan(found.value, found.format);
      return;
    }
    cameraState.misses += 1;
    if (cameraState.frames === 1 || cameraState.frames % 15 === 0) {
      const debug = cameraState.lastDebug || {};
      const engine = debug.zxingcpp === true
        ? "zxing-cpp on"
        : debug.zxingcpp === false
          ? "zxing-cpp MISSING"
          : "waiting for decoder";
      const size = debug.width ? `${debug.width}x${debug.height}` : `${canvas.width}x${canvas.height}`;
      const brightness = debug.mean != null ? `, brightness ${Math.round(debug.mean)}` : "";
      const dead = debug.dead
        ? " Captured still is flat (not a real camera picture)."
        : debug.mean != null && debug.mean < 8
          ? " Captured frame is nearly black."
          : "";
      const dark = debug.mean != null && debug.mean < 70 && !debug.dead
        ? " Scene is dark — add a lamp and move the label a foot away from the camera."
        : "";
      setScanHint(
        `${engine}, ${size}${brightness}, ${cameraState.misses} misses.${dead}${dark} Printed codes need a sharp, well-lit label in the green box.`,
      );
    }
  } catch (err) {
    console.warn("scan frame failed", err);
    if (cameraState.frames % 20 === 0) {
      setScanHint(`Scan error: ${err && err.message ? err.message : err}`);
    }
  } finally {
    cameraState.busy = false;
  }
}

function yieldToUi() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function flashSnap() {
  const flash = document.getElementById("snap-flash");
  if (!flash) return;
  flash.hidden = false;
  flash.classList.add("on");
  setTimeout(() => {
    flash.classList.remove("on");
    setTimeout(() => {
      flash.hidden = true;
    }, 160);
  }, 80);
}

function blobToCanvas(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const canvas = workCanvas("stillfull");
      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;
      canvas.getContext("2d", { willReadFrequently: true }).drawImage(img, 0, 0);
      resolve(canvas);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read the still photo."));
    };
    img.src = url;
  });
}

async function captureStillCanvas() {
  const video = previewEl();
  if (!video || !video.videoWidth) {
    throw new Error("Camera is not producing frames yet.");
  }
  // Do not use ImageCapture.takePhoto() — on Linux that often ends the live track.
  return grabFrame(video);
}

function cloneTo(source, dest) {
  dest.width = source.width;
  dest.height = source.height;
  dest.getContext("2d", { willReadFrequently: true }).drawImage(source, 0, 0);
  return dest;
}

function collectStillTiles(source) {
  const tiles = [];
  const w = source.width;
  const h = source.height;
  tiles.push({ x: 0, y: 0, w, h, scale: Math.min(1, 1400 / Math.max(w, h)), label: "full" });
  tiles.push({ x: 0, y: 0, w, h, scale: Math.min(1, 720 / Math.max(w, h)), label: "full-small" });
  [0.06, 0.16, 0.26].forEach((inset, index) => {
    const x = Math.floor(w * inset);
    const y = Math.floor(h * inset);
    tiles.push({
      x,
      y,
      w: w - x * 2,
      h: h - y * 2,
      scale: 2.4,
      label: `center-${index + 1}`,
    });
  });
  for (let i = 0; i < 6; i += 1) {
    const y = Math.floor(h * (0.05 + i * 0.14));
    tiles.push({
      x: Math.floor(w * 0.04),
      y,
      w: Math.floor(w * 0.92),
      h: Math.max(48, Math.floor(h * 0.22)),
      scale: 2.6,
      label: `band-${i + 1}`,
    });
  }
  const tileW = Math.floor(w * 0.42);
  const tileH = Math.floor(h * 0.42);
  const stepX = Math.floor(w * 0.29);
  const stepY = Math.floor(h * 0.29);
  let tile = 0;
  for (let gy = 0; gy < 3; gy += 1) {
    for (let gx = 0; gx < 3; gx += 1) {
      tile += 1;
      tiles.push({
        x: gx * stepX,
        y: gy * stepY,
        w: tileW,
        h: tileH,
        scale: 2.2,
        label: `tile-${tile}`,
      });
    }
  }
  return tiles;
}

async function scanStillAggressively(source) {
  const variants = [source];
  const enhanced = cloneTo(source, workCanvas("stillEnhanced"));
  enhancePrint(enhanced);
  variants.push(enhanced);

  const tile = workCanvas("stillTile");
  let tried = 0;
  const total = collectStillTiles(source).length * variants.length;
  for (const variant of variants) {
    const fromDetector = await decodeWithDetector(variant);
    if (fromDetector && isMatrixFormat(fromDetector.format)) return fromDetector;
    const jobs = collectStillTiles(variant);
    for (const job of jobs) {
      const rect = clampRect(job.x, job.y, job.w, job.h, variant.width, variant.height);
      copyRegion(variant, tile, rect.x, rect.y, rect.w, rect.h, job.scale, false);
      tried += 1;
      if (tried % 4 === 0) {
        setScanHint(`Aggressive scan ${tried}/${total}: ${job.label} (${tile.width}x${tile.height})`);
        showDecodePreview(tile);
        await yieldToUi();
      }
      let found = await decodeWithDetector(tile);
      if (found && isMatrixFormat(found.format)) return found;
      found = decodeWithJsQR(tile);
      if (found) return found;
    }
  }
  return null;
}

async function snapAndScan(options = {}) {
  const auto = Boolean(options.auto);
  if (cameraState.snapping) return false;
  if (!cameraState.stream) {
    if (!auto) window.ScannerHub.say("Start the camera first, aim at the label, then click Snap & scan.", "warn");
    return false;
  }
  cameraState.snapping = true;
  cameraState.busy = true;
  const button = document.getElementById("btn-snap-scan");
  try {
    if (button && !auto) {
      window.ScannerHub.setButtonState(button, { label: "Snapping…", busy: true });
    }
    setScanHint(auto ? "Live scan missed. Taking a still photo…" : "Taking a still photo…");
    flashSnap();
    const still = await captureStillCanvas();
    showDecodePreview(still);
    window.ScannerHub.say(
      `Captured a ${still.width}x${still.height} still. Sending it to the native zxing decoder…`,
      "warn",
    );
    let found = await decodeOnBackend(still);
    if (!found) {
      setScanHint("Native decoder missed. Trying extra crops in the browser…");
      found = await scanStillAggressively(still);
      if (found) await reportScan(found.value, found.format);
    }
    if (found) {
      cameraState.misses = 0;
      setScanHint(`Still photo scanned ${found.value}`);
      return true;
    }
    if (!auto) {
      setScanHint("No code in that still. Hold the object still, fill the green box, and snap again.");
      window.ScannerHub.say("No barcode found in that photo. Try closer, flatter, and Snap & scan again.", "bad");
    }
    return false;
  } catch (err) {
    if (!auto) {
      window.ScannerHub.say(err && err.message ? err.message : "Could not take a still photo.", "bad");
    }
    return false;
  } finally {
    cameraState.snapping = false;
    cameraState.busy = false;
    if (button && !auto) window.ScannerHub.resetButtonSoon(button, 900);
  }
}

async function stopBrowserCamera() {
  const button = document.getElementById("btn-stop-camera");
  await window.ScannerHub.withButton(button, "Stopping camera…", async () => {
    stopScanLoop();
    stopTracks();
    showLivePreview(false);
    setCameraPill("Camera idle", "");
    setScanHint("Camera is off. Click Start camera to scan again.");
    window.ScannerHub.say("Camera stopped. Preview and live decoding are off.", "warn");
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("btn-start-camera").addEventListener("click", startBrowserCamera);
  document.getElementById("btn-snap-scan").addEventListener("click", () => snapAndScan());
  document.getElementById("btn-allow-camera").addEventListener("click", startBrowserCamera);
  document.getElementById("btn-stop-camera").addEventListener("click", stopBrowserCamera);
  document.getElementById("btn-refresh-cameras").addEventListener("click", async () => {
    const button = document.getElementById("btn-refresh-cameras");
    await window.ScannerHub.withButton(button, "Looking up cameras…", async () => {
      await listBrowserCameras(cameraState.deviceId);
      const count = Math.max(
        document.querySelectorAll("#camera-choices .camera-choice").length,
        document.getElementById("camera-select").options.length,
      );
      window.ScannerHub.say(`Camera list updated (${count} entries). Pick one, then Start camera.`, "ok");
    });
  });
  document.getElementById("camera-select").addEventListener("change", (event) => {
    if (!event.isTrusted) return;
    chooseCamera(selectDeviceId());
  });

  try {
    await listBrowserCameras();
    const count = document.getElementById("camera-select").options.length;
    window.ScannerHub.say(
      `Camera list is ready (${count} ${count === 1 ? "entry" : "entries"}). Select a device, then click Start camera.`,
      "ok",
    );
  } catch (err) {
    console.warn(err);
    window.ScannerHub.say("Could not list cameras yet. Click Start camera and Allow when asked.", "warn");
  }

  document.getElementById("scan-file").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    window.ScannerHub.say(`Reading ${file.name}…`, "warn");
    try {
      const found = await decodeImageFile(file);
      if (!found) {
        window.ScannerHub.say("No barcode or QR found in that image. Try a sharper, closer photo.", "bad");
        return;
      }
      await reportScan(found.value, found.format);
    } catch (err) {
      window.ScannerHub.say(err && err.message ? err.message : "Could not read that image.", "bad");
    }
  });
});

function selectDeviceId() {
  return document.getElementById("camera-select").value || "";
}

function decodeImageFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = async () => {
      URL.revokeObjectURL(url);
      try {
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth || img.width;
        canvas.height = img.naturalHeight || img.height;
        canvas.getContext("2d", { willReadFrequently: true }).drawImage(img, 0, 0);
        showDecodePreview(canvas);
        resolve(await scanStillAggressively(canvas));
      } catch (err) {
        reject(err);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not load that image."));
    };
    img.src = url;
  });
}
