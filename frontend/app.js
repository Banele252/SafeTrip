const POLL_MS = 2000;
const STALE_MS = 60000;

const token = new URLSearchParams(location.search).get("token") || "";
const $ = (id) => document.getElementById(id);

// Keep the token from the page URL on every request to the Pi.
function withToken(path) {
  const url = new URL(path, location.origin);
  if (token) url.searchParams.set("token", token);
  return url.pathname + url.search;
}

async function getJson(path) {
  const response = await fetch(withToken(path), { cache: "no-store" });
  if (response.status === 401) throw new Error("unauthorized");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : "—";
}

function setBadge(text, kind) {
  const badge = $("badge");
  badge.textContent = text;
  badge.className = `badge ${kind}`;
}

function renderState(data) {
  const status = data.status || {};

  $("description").textContent = data.latest ? data.latest.description : "No detections yet";
  $("description-time").textContent = data.latest ? `Recorded ${formatTime(data.latest.timestamp)}` : "";

  $("pending").textContent = data.pending;
  $("sent-total").textContent = status.sent_total ?? "—";
  $("last-success").textContent = formatTime(status.last_success);

  const location = status.location;
  $("location").textContent = location
    ? `${location.lat.toFixed(5)}, ${location.lon.toFixed(5)} (${location.source})`
    : "Unknown";
  $("api-host").textContent = status.api_host ? `Sending to ${status.api_host}` : "";

  const errorLine = $("last-error");
  errorLine.hidden = !status.last_error;
  errorLine.textContent = status.last_error ? `Last error: ${status.last_error}` : "";

  if (!status.updated_at) {
    setBadge("Waiting for uploader", "");
  } else if (Date.now() - Date.parse(status.updated_at) > STALE_MS) {
    setBadge("Uploader not responding", "warn");
  } else if (status.state === "error") {
    setBadge("Retrying / offline", "bad");
  } else {
    setBadge("Up to date", "good");
  }
}

function renderLog(records) {
  const list = $("log");
  list.replaceChildren();

  if (!records.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "No detections yet";
    list.append(empty);
    return;
  }

  for (const record of records) {
    const item = document.createElement("li");

    const time = document.createElement("time");
    time.textContent = formatTime(record.timestamp);

    const tag = document.createElement("span");
    tag.className = `tag ${record.sent ? "sent" : "pending"}`;
    tag.textContent = record.sent ? "sent" : "pending";

    const text = document.createElement("span");
    text.className = "text";
    text.textContent = record.description;

    item.append(time, tag, text);
    list.append(item);
  }
}

function refreshSnapshot() {
  const image = $("snapshot");
  image.onload = () => {
    image.hidden = false;
    $("snapshot-empty").hidden = true;
  };
  image.onerror = () => {
    image.hidden = true;
    $("snapshot-empty").hidden = false;
  };
  image.src = withToken(`/latest.jpg?t=${Date.now()}`);
}

async function poll() {
  try {
    const [state, records] = await Promise.all([
      getJson("/api/state"),
      getJson("/api/detections?limit=50"),
    ]);
    renderState(state);
    renderLog(records);
    refreshSnapshot();
  } catch (error) {
    setBadge(error.message === "unauthorized" ? "Token required" : "Dashboard offline", "bad");
  }
  setTimeout(poll, POLL_MS);
}

poll();
