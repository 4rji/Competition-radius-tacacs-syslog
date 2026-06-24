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
  themeToggle: document.querySelector("#theme-toggle"),
  themeIcon: document.querySelector("#theme-icon"),
  themeLabel: document.querySelector("#theme-label"),
  themeColor: document.querySelector("#theme-color"),
  winnerButton: document.querySelector("#winner-button"),
  resetButton: document.querySelector("#reset-button"),
  winnerOverlay: document.querySelector("#winner-overlay"),
  winnerName: document.querySelector("#winner-name"),
  winnerScore: document.querySelector("#winner-score"),
  closeWinner: document.querySelector("#close-winner"),
  fireworksCanvas: document.querySelector("#fireworks-canvas"),
  toast: document.querySelector("#toast"),
};

const THEME_STORAGE_KEY = "digi-scoreboard-theme";

let socket;
let reconnectTimer;
let pingTimer;
let countdownTimer;
let scoreInterval = null;
let nextScoreAt = 0;
let currentParticipants = [];
let fireworksFrame;
let fireworksStopTimer;
let fireworksBurstTimer;

function applyTheme(theme, persist = false) {
  const selectedTheme = theme === "light" ? "light" : "dark";
  const switchTarget = selectedTheme === "dark" ? "light" : "dark";

  document.documentElement.dataset.theme = selectedTheme;
  elements.themeIcon.textContent = selectedTheme === "dark" ? "☀" : "☾";
  elements.themeLabel.textContent = `${titleCase(switchTarget)} mode`;
  elements.themeToggle.setAttribute("aria-label", `Switch to ${switchTarget} mode`);
  elements.themeToggle.title = `Switch to ${switchTarget} mode`;
  elements.themeColor.content = selectedTheme === "dark" ? "#101419" : "#f3f5f6";

  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, selectedTheme);
    } catch (_) {
      // Theme switching still works when storage is unavailable.
    }
  }
}

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

    const syslogCell = createElement("td");
    syslogCell.append(statusPill(participant.services.syslog?.status));
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
      syslogCell,
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
  currentParticipants = participants;

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
    `+${scoring.one_time_points || 10} first SYSLOG · +${scoring.points_per_service_per_minute || 0} every ${formatInterval(scoreInterval)} active`;
  elements.lastUpdated.textContent = `Updated ${formatTime(state.updated_at)}`;

  renderParticipants(participants);
  renderEvents(state.recent_events || []);
}

function formatInterval(seconds) {
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return `${minutes} min`;
  }
  return `${seconds} sec`;
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
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  elements.scoreCountdown.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
  if (remaining === 0) nextScoreAt = Date.now() + scoreInterval * 1000;
}

function launchFireworks() {
  const canvas = elements.fireworksCanvas;
  const context = canvas.getContext("2d");
  const particles = [];
  const colors = ["#82d653", "#ffd166", "#ff5d8f", "#61dafb", "#ffffff", "#b388ff"];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function resizeCanvas() {
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(window.innerWidth * scale);
    canvas.height = Math.floor(window.innerHeight * scale);
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    context.setTransform(scale, 0, 0, scale, 0, 0);
  }

  function burst(x, y, amount = 70) {
    for (let index = 0; index < amount; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 2.5 + Math.random() * 6;
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        alpha: 1,
        decay: 0.009 + Math.random() * 0.013,
        color: colors[Math.floor(Math.random() * colors.length)],
        size: 2 + Math.random() * 3,
      });
    }
  }

  function animate() {
    context.clearRect(0, 0, window.innerWidth, window.innerHeight);
    for (let index = particles.length - 1; index >= 0; index -= 1) {
      const particle = particles[index];
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.045;
      particle.vx *= 0.99;
      particle.alpha -= particle.decay;
      if (particle.alpha <= 0) {
        particles.splice(index, 1);
        continue;
      }
      context.globalAlpha = particle.alpha;
      context.fillStyle = particle.color;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;
    fireworksFrame = window.requestAnimationFrame(animate);
  }

  resizeCanvas();
  window.addEventListener("resize", resizeCanvas, { once: true });
  window.cancelAnimationFrame(fireworksFrame);
  clearTimeout(fireworksStopTimer);
  clearInterval(fireworksBurstTimer);

  burst(window.innerWidth * 0.2, window.innerHeight * 0.28, reducedMotion ? 25 : 75);
  burst(window.innerWidth * 0.8, window.innerHeight * 0.3, reducedMotion ? 25 : 75);
  burst(window.innerWidth * 0.5, window.innerHeight * 0.18, reducedMotion ? 25 : 90);
  animate();

  if (!reducedMotion) {
    fireworksBurstTimer = window.setInterval(() => {
      burst(
        window.innerWidth * (0.12 + Math.random() * 0.76),
        window.innerHeight * (0.12 + Math.random() * 0.4),
        65,
      );
    }, 550);
    fireworksStopTimer = window.setTimeout(() => window.clearInterval(fireworksBurstTimer), 4800);
  }
}

function showWinner() {
  const winner = currentParticipants[0];
  if (!winner) {
    showToast("No participants available", true);
    return;
  }
  elements.winnerName.textContent = winner.display_name;
  elements.winnerScore.textContent = `${Number(winner.score || 0).toLocaleString()} points`;
  elements.winnerOverlay.hidden = false;
  document.body.classList.add("celebrating");
  launchFireworks();
  elements.closeWinner.focus();
}

function closeWinner() {
  elements.winnerOverlay.hidden = true;
  document.body.classList.remove("celebrating");
  window.cancelAnimationFrame(fireworksFrame);
  clearTimeout(fireworksStopTimer);
  clearInterval(fireworksBurstTimer);
  elements.winnerButton.focus();
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

elements.themeToggle.addEventListener("click", () => {
  const currentTheme = document.documentElement.dataset.theme;
  applyTheme(currentTheme === "dark" ? "light" : "dark", true);
});

elements.winnerButton.addEventListener("click", showWinner);
elements.closeWinner.addEventListener("click", closeWinner);
elements.winnerOverlay.addEventListener("click", (event) => {
  if (event.target === elements.winnerOverlay) closeWinner();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.winnerOverlay.hidden) closeWinner();
});

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

applyTheme(document.documentElement.dataset.theme);
loadInitialState();
connectWebSocket();
updateCountdown();
countdownTimer = window.setInterval(updateCountdown, 1000);
