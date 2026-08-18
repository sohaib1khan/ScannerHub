async function loadSettingsForm() {
  const settings = await window.ScannerHub.api("/settings");
  document.getElementById("dedupe").value = settings.dedupe_window_seconds;
  document.getElementById("hid-enabled").checked = Boolean(settings.hid_listener_enabled);
  await loadSoundPickers();
}

async function loadSoundPickers(preferIds) {
  const data = await window.ScannerHub.api("/settings/sounds");
  window.ScannerHub.setSoundCatalog(data.sounds || [], data.selected || {});
  const assigned = data.selected || {};
  fillSoundSelect("sound-camera-select", data.sounds, (preferIds && preferIds.camera) || assigned.camera);
  fillSoundSelect("sound-hid-select", data.sounds, (preferIds && preferIds.external_scanner) || assigned.external_scanner);
  updateUsingLabel("camera", assigned.camera, data.sounds);
  updateUsingLabel("external_scanner", assigned.external_scanner, data.sounds);
}

function soundLabel(sounds, soundId) {
  const item = (sounds || []).find((entry) => entry.id === soundId || entry.file === soundId);
  return item ? item.label : soundId || "High beep";
}

function updateUsingLabel(source, soundId, sounds) {
  const el = document.getElementById(source === "camera" ? "sound-camera-using" : "sound-hid-using");
  if (el) el.textContent = `In use: ${soundLabel(sounds || window.ScannerHub.soundCatalog, soundId)}`;
}

function fillSoundSelect(id, sounds, selected) {
  const select = document.getElementById(id);
  if (!select) return;
  const current = selected || "";
  select.innerHTML = "";
  (sounds || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.builtin ? item.label : `${item.label} (added)`;
    if (item.id === current || item.file === current) option.selected = true;
    select.appendChild(option);
  });
}

function sourceSelectId(source) {
  return source === "camera" ? "sound-camera-select" : "sound-hid-select";
}

function previewSoundId(source) {
  return document.getElementById(sourceSelectId(source)).value;
}

async function saveSettings() {
  const button = document.getElementById("btn-save-settings");
  const dedupe = Number(document.getElementById("dedupe").value);
  const hid = document.getElementById("hid-enabled").checked;
  const assigned = window.ScannerHub.selectedSounds || {};
  await window.ScannerHub.withButton(button, "Saving settings…", async () => {
    await window.ScannerHub.api("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dedupe_window_seconds: dedupe,
        hid_listener_enabled: hid,
        sounds: {
          camera: assigned.camera,
          external_scanner: assigned.external_scanner,
        },
      }),
    });
    await window.ScannerHub.refreshStatus();
    await loadSoundPickers();
    window.ScannerHub.say(
      `Settings saved. Duplicate scans within ${dedupe}s are ignored. Hardware listener is ${hid ? "on" : "off"}.`,
      "ok",
    );
  });
}

async function assignSound(source) {
  const soundId = previewSoundId(source);
  const label = source === "camera" ? "camera" : "hardware scanner";
  await window.ScannerHub.api("/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sounds: { [source]: soundId } }),
  });
  window.ScannerHub.setSoundCatalog(window.ScannerHub.soundCatalog, {
    ...window.ScannerHub.selectedSounds,
    [source]: soundId,
  });
  updateUsingLabel(source, soundId);
  window.ScannerHub.say(`Assigned ${soundLabel(window.ScannerHub.soundCatalog, soundId)} to ${label} scans.`, "ok");
}

async function uploadSound(source, file) {
  const label = source === "camera" ? "camera" : "hardware scanner";
  window.ScannerHub.say(`Adding ${file.name} so you can test it…`, "warn");
  const body = new FormData();
  body.append("source", source);
  body.append("file", file);
  const response = await fetch("/api/settings/sound", { method: "POST", body });
  if (!response.ok) {
    window.ScannerHub.say(`Could not upload ${label} sound. Use a .wav, .mp3, or .ogg file.`, "bad");
    return;
  }
  const data = await response.json();
  await loadSoundPickers({ [source]: data.id });
  playPreview(source);
  window.ScannerHub.say(
    `${file.name} is ready to preview. Click Test again if you missed it, then Use to assign it to ${label} scans.`,
    "ok",
  );
  return data;
}

function playPreview(source) {
  const soundId = previewSoundId(source);
  if (window.ScannerHub.playSoundId) window.ScannerHub.playSoundId(soundId, source);
  window.ScannerHub.api(
    `/settings/sound/test?source=${encodeURIComponent(source)}&sound=${encodeURIComponent(soundId)}`,
    { method: "POST" },
  ).catch(() => {});
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("sound-camera-select").addEventListener("change", () => playPreview("camera"));
  document.getElementById("sound-hid-select").addEventListener("change", () => playPreview("external_scanner"));
  document.getElementById("sound-camera").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadSound("camera", file);
  });
  document.getElementById("sound-hid").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadSound("external_scanner", file);
  });
  document.getElementById("btn-refresh-sounds").addEventListener("click", async () => {
    const button = document.getElementById("btn-refresh-sounds");
    await window.ScannerHub.withButton(button, "Reloading sounds…", async () => {
      await loadSoundPickers();
      window.ScannerHub.say("Sound list reloaded from data/sounds/.", "ok");
    });
  });
  document.querySelectorAll("[data-test-sound]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.getAttribute("data-test-sound");
      await window.ScannerHub.withButton(button, "Testing…", async () => {
        playPreview(source);
        window.ScannerHub.say("Preview only — click Use to assign this sound.", "ok");
      });
    });
  });
  document.querySelectorAll("[data-assign-sound]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.getAttribute("data-assign-sound");
      await window.ScannerHub.withButton(button, "Assigning…", async () => {
        await assignSound(source);
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
