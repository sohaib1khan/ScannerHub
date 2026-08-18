async function loadSettingsForm() {
  const settings = await window.ScannerHub.api("/settings");
  document.getElementById("dedupe").value = settings.dedupe_window_seconds;
  document.getElementById("hid-enabled").checked = Boolean(settings.hid_listener_enabled);
}

async function saveSettings() {
  await window.ScannerHub.api("/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dedupe_window_seconds: Number(document.getElementById("dedupe").value),
      hid_listener_enabled: document.getElementById("hid-enabled").checked,
    }),
  });
  await window.ScannerHub.refreshStatus();
}

async function uploadSound(source, file) {
  const body = new FormData();
  body.append("source", source);
  body.append("file", file);
  await fetch("/api/settings/sound", { method: "POST", body });
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("sound-camera").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadSound("camera", file);
  });
  document.getElementById("sound-hid").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadSound("external_scanner", file);
  });
  document.querySelectorAll("[data-test-sound]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.getAttribute("data-test-sound");
      await window.ScannerHub.api(`/settings/sound/test?source=${encodeURIComponent(source)}`, {
        method: "POST",
      });
    });
  });
  try {
    await loadSettingsForm();
  } catch (err) {
    console.error(err);
  }
});
