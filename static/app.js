const elements = {
  scoreboardBody: document.querySelector("#scoreboard-body"),
  eventFeed: document.querySelector("#event-feed"),
  connectionStatus: document.querySelector("#connection-status"),
  leaderName: document.querySelector("#leader-name"),
  leaderScore: document.querySelector("#leader-score"),
  activeServices: document.querySelector("#active-services"),
  participantCount: document.querySelector("#participant-count"),
  scoreCountdown: document.querySelector("#score-countdown"),
  scoringRule: document.querySelector("#scoring-rule"),
  lastUpdated: document.querySelector("#last-updated"),
  resetButton: document.querySelector("#reset-button"),
  toast: document.querySelector("#toast"),
};

let socket;
let reconnectTimer;
let pingTimer;
let countdownTimer;
let scoreInterval = null;
let nextScoreAt = 0;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = text;
  return element;
}

function formatTime(timestamp, includeDate = false) {
  if (!timestamp) return "Never";
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) return "Unknown";
  return value.toLocaleString([], includeDate
    ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }
    : { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function relativeTime(timestamp) {
  if (!timestamp) return "Never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 5) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

function titleCase(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusPill(status) {
  const active = status === "green";
  return createElement(
    "span",
    `status-pill ${active ? "status-green" : "status-red"}`,
    active ? "Active" : "Inactive",
  );
}

function renderParticipants(participants) {
  elements.scoreboardBody.replaceChildren();
  if (!participants.length) {
    const row = createElement("tr");
    const cell = createElement("td", "empty-state", "No participants configured");
    cell.colSpan = 9;
    row.append(cell);
    elements.scoreboardBody.append(row);
    return;
  }

  participants.forEach((participant) => {
    const row = createElement("tr");

    const rankCell = createElement("td", "rank-column");
    rankCell.append(createElement("span", "rank-badge", participant.rank));

    const participantCell = createElement("td");
    participantCell.append(createElement("span", "participant-name", participant.display_name));

    const ipCell = createElement("td", "router-ip", participant.router_ip);

    const webuiCell = createElement("td");
    webuiCell.append(statusPill(participant.services.webui?.status));
    const radiusCell = createElement("td");
    radiusCell.append(statusPill(participant.services.radius?.status));
    const tacacsCell = createElement("td");
    tacacsCell.append(statusPill(participant.services.tacacs?.status));

    const greenCell = createElement("td", "centered");
    const serviceCount = Object.keys(participant.services || {}).length;
    greenCell.append(
      createElement("span", "green-count", `${participant.green_services_count}/${serviceCount}`),
    );

    const scoreCell = createElement("td", "score-column");
    scoreCell.append(createElement("span", "score", participant.score.toLocaleString()));

    const seenCell = createElement("td", "seen-time", relativeTime(participant.last_seen));
    seenCell.title = participant.last_seen ? formatTime(participant.last_seen, true) : "No events received";

    row.append(
      rankCell,
      participantCell,
      ipCell,
      webuiCell,
      radiusCell,
      tacacsCell,
      greenCell,
      scoreCell,
      seenCell,
    );
    elements.scoreboardBody.append(row);
  });
}

function renderEvents(events) {
  elements.eventFeed.replaceChildren();
  if (!events.length) {
    const empty = createElement("div", "feed-empty");
    empty.append(
      createElement("span", "feed-empty-icon", "↯"),
      createElement("p", "", "Waiting for authentication events"),
    );
    elements.eventFeed.append(empty);
    return;
  }

  events.slice(0, 30).forEach((event) => {
    const item = createElement("article", `event-item event-${event.status}`);
    const topline = createElement("div", "event-topline");
    topline.append(
      createElement("span", "event-name", event.participant_name),
      createElement("time", "event-time", formatTime(event.timestamp)),
    );

    const description = createElement("p", "event-description");
    description.append(
      createElement("span", "event-service", event.service),
      document.createTextNode(` · ${titleCase(event.event_type)}`),
    );

    item.append(topline, description);
    if (event.raw) {
      const raw = createElement("p", "event-raw", event.raw);
      raw.title = event.raw;
      item.append(raw);
    }
    elements.eventFeed.append(item);
  });
}

function renderState(state) {
  const summary = state.summary || {};
  const scoring = state.scoring || {};
  const participants = state.participants || [];

  elements.leaderName.textContent = summary.leader || "—";
  elements.leaderScore.textContent = `${Number(summary.leader_score || 0).toLocaleString()} points`;
  elements.activeServices.textContent =
    `${summary.active_services || 0} / ${summary.maximum_active_services || 0}`;
  elements.participantCount.textContent = summary.participant_count || 0;

  scoreInterval = Number(scoring.score_interval_seconds || 60);
  nextScoreAt = state.next_score_at
    ? Number(state.next_score_at) * 1000
    : Date.now() + scoreInterval * 1000;
  elements.scoringRule.textContent =
    `+${scoring.points_per_service_per_minute || 0} points per green service`;
  elements.lastUpdated.textContent = `Updated ${formatTime(state.updated_at)}`;

  renderParticipants(participants);
  renderEvents(state.recent_events || []);
}

function setConnection(status) {
  const text = elements.connectionStatus.querySelector("span:last-child");
  elements.connectionStatus.className = `connection-badge connection-${status}`;
  if (status === "live") text.textContent = "Live";
  else if (status === "offline") text.textContent = "Reconnecting";
  else text.textContent = "Connecting";
}

function connectWebSocket() {
  clearTimeout(reconnectTimer);
  clearInterval(pingTimer);
  setConnection("pending");

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

  socket.addEventListener("open", () => {
    setConnection("live");
    pingTimer = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
  });

  socket.addEventListener("message", (message) => {
    try {
      renderState(JSON.parse(message.data));
    } catch (error) {
      console.error("Invalid scoreboard update", error);
    }
  });

  socket.addEventListener("close", () => {
    clearInterval(pingTimer);
    setConnection("offline");
    reconnectTimer = window.setTimeout(connectWebSocket, 2000);
  });

  socket.addEventListener("error", () => socket.close());
}

async function loadInitialState() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderState(await response.json());
  } catch (error) {
    showToast(`Could not load scoreboard: ${error.message}`, true);
  }
}

function updateCountdown() {
  if (!scoreInterval) {
    elements.scoreCountdown.textContent = "—";
    return;
  }
  const remaining = Math.max(0, Math.ceil((nextScoreAt - Date.now()) / 1000));
  elements.scoreCountdown.textContent = `${remaining}s`;
  if (remaining === 0) nextScoreAt = Date.now() + scoreInterval * 1000;
}

let toastTimer;
function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast visible${isError ? " error" : ""}`;
  toastTimer = window.setTimeout(() => {
    elements.toast.className = "toast";
  }, 3000);
}

elements.resetButton.addEventListener("click", async () => {
  const confirmed = window.confirm("Reset all scores, statuses, and event history?");
  if (!confirmed) return;

  elements.resetButton.disabled = true;
  try {
    const response = await fetch("/api/reset", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderState(await response.json());
    showToast("Scoreboard reset");
  } catch (error) {
    showToast(`Reset failed: ${error.message}`, true);
  } finally {
    elements.resetButton.disabled = false;
  }
});

loadInitialState();
connectWebSocket();
updateCountdown();
countdownTimer = window.setInterval(updateCountdown, 1000);
