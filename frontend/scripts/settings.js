async function loadSettingsForm() {
  const settings = await window.ScannerHub.api("/settings");
  document.getElementById("dedupe").value = settings.dedupe_window_seconds;
  document.getElementById("hid-enabled").checked = Boolean(settings.hid_listener_enabled);
}

async function saveSettings() {
  const button = document.getElementById("btn-save-settings");
  const dedupe = Number(document.getElementById("dedupe").value);
  const hid = document.getElementById("hid-enabled").checked;
  await window.ScannerHub.withButton(button, "Saving settings…", async () => {
    await window.ScannerHub.api("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dedupe_window_seconds: dedupe,
        hid_listener_enabled: hid,
      }),
    });
    await window.ScannerHub.refreshStatus();
    window.ScannerHub.say(
      `Settings saved. Duplicate scans within ${dedupe}s are ignored. Hardware listener is ${hid ? "on" : "off"}.`,
      "ok",
    );
  });
}

async function uploadSound(source, file) {
  const label = source === "camera" ? "camera" : "hardware scanner";
  window.ScannerHub.say(`Uploading ${label} sound (${file.name})…`, "warn");
  const body = new FormData();
  body.append("source", source);
  body.append("file", file);
  const response = await fetch("/api/settings/sound", { method: "POST", body });
  if (!response.ok) {
    window.ScannerHub.say(`Could not upload ${label} sound. Use a .wav, .mp3, or .ogg file.`, "bad");
    return;
  }
  window.ScannerHub.say(`${label} sound replaced with ${file.name}. Next scan from that source will use it.`, "ok");
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
      const label = source === "camera" ? "camera" : "hardware scanner";
      await window.ScannerHub.withButton(button, "Playing beep…", async () => {
        if (window.ScannerHub.playScanBeep) window.ScannerHub.playScanBeep(source);
        try {
          await window.ScannerHub.api(`/settings/sound/test?source=${encodeURIComponent(source)}`, {
            method: "POST",
          });
        } catch (err) {
          /* Client beep already played. Backend speaker is optional. */
        }
        window.ScannerHub.say(`Played the ${label} beep in this browser. Turn the tab sound up if you heard nothing.`, "ok");
      });
    });
  });
  try {
    await loadSettingsForm();
  } catch (err) {
    console.error(err);
    window.ScannerHub.say("Could not load settings from the backend.", "bad");
  }
});
