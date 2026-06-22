const form = document.querySelector("#bootstrap-form");
const runButton = document.querySelector("#run-button");
const resetButton = document.querySelector("#reset-button");
const statusEl = document.querySelector("#status");
const responseEl = document.querySelector("#response-json");
const runIdEl = document.querySelector("#run-id");
const appVersionEl = document.querySelector("#app-version");
const sdkVersionEl = document.querySelector("#sdk-version");
const cliVersionEl = document.querySelector("#cli-version");
const bootstrapLink = document.querySelector("#bootstrap-link");
const reviewLink = document.querySelector("#review-link");
const previews = {
  source: document.querySelector("#source-preview"),
  candidate: document.querySelector("#candidate-preview"),
  west: document.querySelector("#west-preview"),
};

const initialValues = Object.fromEntries(new FormData(form).entries());
let pollTimer = null;

loadAppInfo();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  stopPolling();
  const payload = formPayload();
  setStatus("Submitting", "running");
  setBusy(true);
  setResponse(payload);

  try {
    const response = await fetch("/bootstrap-anchors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    renderResult(data);
    if (data.pollUrl && data.status !== "completed") {
      setStatus(statusLabel(data), "running");
      pollRun(data.pollUrl);
    } else {
      setStatus("Completed", "done");
      setBusy(false);
    }
  } catch (error) {
    setStatus(error.message || "Failed", "error");
    setBusy(false);
  } finally {
  }
});

resetButton.addEventListener("click", () => {
  stopPolling();
  for (const [key, value] of Object.entries(initialValues)) {
    const field = form.elements.namedItem(key);
    if (field) field.value = value;
  }
  clearResult();
  setStatus("Ready", "");
  setBusy(false);
});

async function loadAppInfo() {
  try {
    const response = await fetch("/app-info", { cache: "no-store" });
    const data = await response.json();
    const deployment = data.deploymentId ? String(data.deploymentId).slice(0, 8) : "local";
    appVersionEl.textContent = `v${data.version || data.appVersion || "unknown"} · ${deployment}`;
    sdkVersionEl.textContent = `v${data.sdkVersion || "unknown"}`;
    cliVersionEl.textContent = `v${data.cliVersion || "unknown"}`;
  } catch (_error) {
    appVersionEl.textContent = "unavailable";
    sdkVersionEl.textContent = "unavailable";
    cliVersionEl.textContent = "unavailable";
  }
}

function pollRun(path) {
  pollTimer = window.setTimeout(async () => {
    try {
      const response = await fetch(path, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      renderResult(data);
      if (data.status === "completed") {
        stopPolling();
        setStatus("Completed", "done");
        setBusy(false);
        return;
      }
      if (data.status === "failed") {
        stopPolling();
        setStatus(data.error || "Failed", "error");
        setBusy(false);
        return;
      }
      setStatus(statusLabel(data), "running");
      pollRun(path);
    } catch (error) {
      stopPolling();
      setStatus(error.message || "Polling failed", "error");
      setBusy(false);
    }
  }, 3000);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function formPayload() {
  const data = Object.fromEntries(new FormData(form).entries());
  const directions = String(data.directions || "w")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const payload = {
    characterId: String(data.characterId || "character").trim(),
    runLabel: String(data.runLabel || data.characterId || "character").trim(),
    candidateFacing: String(data.candidateFacing || "front").trim(),
    directions: directions.length ? directions : ["w"],
    kColors: Number(data.kColors || 64),
    candidatePromptPreset: String(data.candidatePromptPreset || "lobit-v1").trim(),
    pixelSnapAnchor: String(data.pixelSnapAnchor || "true") !== "false",
    gameView: String(data.gameView || "platformer").trim(),
    anchorRole: String(data.anchorRole || "character").trim(),
  };

  const sourceImage = String(data.sourceImage || "").trim();
  const sourcePrompt = String(data.sourcePrompt || "").trim();
  if (sourceImage) {
    payload.sourceImage = sourceImage;
  } else {
    payload.sourcePrompt = sourcePrompt;
  }

  const candidatePrompt = String(data.candidatePrompt || "").trim();
  if (candidatePrompt) {
    payload.candidatePrompt = candidatePrompt;
  }
  const anchorContext = String(data.anchorContext || "").trim();
  if (anchorContext) {
    payload.anchorContext = anchorContext;
  }
  return payload;
}

function renderResult(data) {
  setResponse(data);
  runIdEl.textContent = data.runId || "-";
  setArtifactLink(bootstrapLink, data.artifactUrls?.["bootstrap-json"]);
  setArtifactLink(reviewLink, data.artifactUrls?.review);
  setPreview(previews.source, data.artifactUrls?.source);
  setPreview(previews.candidate, data.artifactUrls?.candidate || data.artifactUrls?.["candidate-front"] || data.artifactUrls?.["candidate-s"]);
  setPreview(previews.west, data.artifactUrls?.["anchor-w"] || data.anchors?.w);
}

function clearResult() {
  responseEl.textContent = "{}";
  runIdEl.textContent = "-";
  setArtifactLink(bootstrapLink, "");
  setArtifactLink(reviewLink, "");
  for (const preview of Object.values(previews)) {
    preview.removeAttribute("src");
  }
}

function setPreview(element, path) {
  if (!path) {
    element.removeAttribute("src");
    return;
  }
  element.src = path;
}

function setArtifactLink(element, path) {
  if (!path) {
    element.textContent = "-";
    element.removeAttribute("href");
    return;
  }
  element.textContent = path;
  element.href = path;
}

function setResponse(value) {
  responseEl.textContent = JSON.stringify(value, null, 2);
}

function setBusy(value) {
  runButton.disabled = value;
  resetButton.disabled = false;
}

function setStatus(text, state) {
  statusEl.textContent = text;
  if (state) {
    statusEl.dataset.state = state;
  } else {
    delete statusEl.dataset.state;
  }
}

function statusLabel(data) {
  const status = data.status || "running";
  const runId = data.runId ? ` · ${data.runId}` : "";
  return `${status}${runId}`;
}
