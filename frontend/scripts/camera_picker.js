function cameraPreviewUrl() {
  return `/api/camera/preview?t=${Date.now()}`;
}

function showPreview(running) {
  const img = document.getElementById("preview");
  const empty = document.getElementById("preview-empty");
  if (running) {
    img.src = cameraPreviewUrl();
    img.classList.add("visible");
    empty.style.display = "none";
  } else {
    img.removeAttribute("src");
    img.classList.remove("visible");
    empty.style.display = "grid";
  }
}

async function loadCameras(selectedIndex) {
  const select = document.getElementById("camera-select");
  const data = await window.ScannerHub.api("/cameras");
  const cameras = data.cameras || [];
  select.innerHTML = "";
  if (!cameras.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No camera found";
    select.appendChild(option);
    return;
  }
  for (const camera of cameras) {
    const option = document.createElement("option");
    option.value = String(camera.index);
    option.textContent = camera.label || camera.name;
    if (Number(selectedIndex) === camera.index) option.selected = true;
    select.appendChild(option);
  }
}

async function startSelectedCamera() {
  const select = document.getElementById("camera-select");
  const index = Number(select.value);
  if (Number.isNaN(index)) return;
  const result = await window.ScannerHub.api("/camera/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index, start: true }),
  });
  showPreview(Boolean(result.camera && result.camera.running));
  await window.ScannerHub.refreshStatus();
}

async function stopCamera() {
  await window.ScannerHub.api("/camera/stop", { method: "POST" });
  showPreview(false);
  await window.ScannerHub.refreshStatus();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("btn-start-camera").addEventListener("click", startSelectedCamera);
  document.getElementById("btn-stop-camera").addEventListener("click", stopCamera);
  document.getElementById("btn-refresh-cameras").addEventListener("click", () => loadCameras());

  try {
    const status = await window.ScannerHub.api("/status");
    const settings = await window.ScannerHub.api("/settings");
    await loadCameras(settings.camera_index);
    showPreview(Boolean(status.camera && status.camera.running));
  } catch (err) {
    console.error(err);
    await loadCameras();
  }
});
