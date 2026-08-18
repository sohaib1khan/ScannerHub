const cameraState = {
  stream: null,
  scanTimer: null,
  detector: null,
  deviceId: null,
  busy: false,
};

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
}

async function releaseBackendCamera() {
  try {
    await window.ScannerHub.api("/camera/stop", { method: "POST" });
  } catch (err) {
    console.warn("Could not release backend camera", err);
  }
}

async function listBrowserCameras(selectedId) {
  const select = document.getElementById("camera-select");
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    select.innerHTML = `<option value="">Camera list not supported in this browser</option>`;
    return;
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter((device) => device.kind === "videoinput");
  select.innerHTML = "";
  if (!cameras.length) {
    select.innerHTML = `<option value="">No camera found</option>`;
    return;
  }
  cameras.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || `Camera ${index + 1}`;
    if (selectedId && device.deviceId === selectedId) option.selected = true;
    select.appendChild(option);
  });
}

function stopTracks() {
  if (!cameraState.stream) return;
  cameraState.stream.getTracks().forEach((track) => track.stop());
  cameraState.stream = null;
  previewEl().srcObject = null;
}

function stopScanLoop() {
  if (cameraState.scanTimer) {
    clearInterval(cameraState.scanTimer);
    cameraState.scanTimer = null;
  }
}

async function startBrowserCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showPermissionHelp("This browser cannot access a camera. Use Chrome or Firefox on http://127.0.0.1:8765/");
    return;
  }

  await releaseBackendCamera();
  stopScanLoop();
  stopTracks();

  const select = document.getElementById("camera-select");
  const deviceId = select.value || undefined;
  const constraints = deviceId
    ? { video: { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false }
    : { video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false };

  setCameraPill("Waiting for permission", "warn");

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (err) {
    if (deviceId) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      } catch (retryErr) {
        handleGetUserMediaError(retryErr);
        return;
      }
    } else {
      handleGetUserMediaError(err);
      return;
    }
  }

  cameraState.stream = stream;
  const video = previewEl();
  video.srcObject = stream;
  video.muted = true;
  try {
    await video.play();
  } catch (err) {
    console.warn(err);
  }

  const track = stream.getVideoTracks()[0];
  cameraState.deviceId = track ? track.getSettings().deviceId : deviceId;
  await listBrowserCameras(cameraState.deviceId);
  showLivePreview(true);
  setCameraPill(track && track.label ? track.label : "Camera on", "ok");
  startScanLoop();
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
  if ("BarcodeDetector" in window) {
    try {
      cameraState.detector = new BarcodeDetector({
        formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e", "codabar", "itf"],
      });
    } catch (err) {
      cameraState.detector = null;
    }
  }
  cameraState.scanTimer = setInterval(scanCurrentFrame, 280);
}

async function scanCurrentFrame() {
  if (cameraState.busy || !cameraState.stream) return;
  const video = previewEl();
  if (!video.videoWidth) return;
  cameraState.busy = true;
  try {
    if (cameraState.detector) {
      const codes = await cameraState.detector.detect(video);
      for (const code of codes) {
        const value = (code.rawValue || "").trim();
        if (!value) continue;
        await window.ScannerHub.api("/scans/manual", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            value,
            source: "camera",
            format: (code.format || "QR").toUpperCase(),
          }),
        });
      }
      if (codes.length) return;
    }
    await sendFrameToBackend(video);
  } catch (err) {
    console.warn("scan frame failed", err);
  } finally {
    cameraState.busy = false;
  }
}

function sendFrameToBackend(video) {
  const canvas = sendFrameToBackend.canvas || document.createElement("canvas");
  sendFrameToBackend.canvas = canvas;
  const maxWidth = 960;
  const scale = video.videoWidth > maxWidth ? maxWidth / video.videoWidth : 1;
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => {
    canvas.toBlob(async (blob) => {
      if (!blob) {
        resolve();
        return;
      }
      const body = new FormData();
      body.append("file", blob, "frame.jpg");
      try {
        await fetch("/api/camera/frame", { method: "POST", body });
      } catch (err) {
        console.warn(err);
      }
      resolve();
    }, "image/jpeg", 0.7);
  });
}

async function stopBrowserCamera() {
  stopScanLoop();
  stopTracks();
  showLivePreview(false);
  setCameraPill("Camera idle", "");
  await releaseBackendCamera();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("btn-start-camera").addEventListener("click", startBrowserCamera);
  document.getElementById("btn-allow-camera").addEventListener("click", startBrowserCamera);
  document.getElementById("btn-stop-camera").addEventListener("click", stopBrowserCamera);
  document.getElementById("btn-refresh-cameras").addEventListener("click", async () => {
    if (!cameraState.stream) {
      await startBrowserCamera();
      return;
    }
    await listBrowserCameras(cameraState.deviceId);
  });
  document.getElementById("camera-select").addEventListener("change", () => {
    if (cameraState.stream) startBrowserCamera();
  });

  await releaseBackendCamera();
  try {
    await listBrowserCameras();
  } catch (err) {
    console.warn(err);
  }
});
