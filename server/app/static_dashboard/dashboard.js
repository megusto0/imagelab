const ui = {
  tableBody: document.getElementById("images-table"),
  previewImage: document.getElementById("preview-image"),
  previewMeta: document.getElementById("preview-meta"),
  metricWindow: document.getElementById("metric-window"),
  metricThroughput: document.getElementById("metric-throughput"),
  metricRtt: document.getElementById("metric-rtt"),
  metricFec: document.getElementById("metric-fec"),
  events: document.getElementById("events-log"),
  refreshBtn: document.getElementById("refresh-btn"),
  noiseForm: document.getElementById("noise-form"),
  noiseSummary: document.getElementById("noise-summary"),
  stageEntries: document.getElementById("stage-entries"),
  progressList: document.getElementById("progress-list"),
  chartCanvas: document.getElementById("chart-throughput"),
};

const state = {
  stageMetrics: new Map(),
  progress: new Map(),
  noise: null,
};

const chartData = {
  labels: [],
  values: [],
};

const throughputChart = new Chart(ui.chartCanvas.getContext("2d"), {
  type: "line",
  data: {
    labels: chartData.labels,
    datasets: [
      {
        label: "кбит/с",
        data: chartData.values,
        borderColor: "#5ed0ff",
        fill: false,
        tension: 0.35,
      },
    ],
  },
  options: {
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: { beginAtZero: true, ticks: { color: "rgba(255,255,255,0.6)" } },
    },
  },
});

const EVENT_TITLES = {
  handshake: "Рукопожатие",
  upload_init: "Старт загрузки",
  chunk: "Чанк",
  upload_progress: "Прогресс",
  stage_metrics: "Этап",
  image_ready: "Завершено",
  noise_config: "Помехи",
  событие: "Сообщение",
  ошибка: "Ошибка",
};

function parseEventData(raw) {
  if (raw === undefined || raw === null || raw === "") return null;
  try {
    return JSON.parse(raw);
  } catch (error) {
    return String(raw);
  }
}

function formatBytes(bytes) {
  if (typeof bytes !== "number" || Number.isNaN(bytes)) {
    return "—";
  }
  if (bytes < 1024) return `${bytes} Б`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} КБ`;
  return `${(kb / 1024).toFixed(2)} МБ`;
}

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function badgeClass(type) {
  if (!type) return "";
  if (type.includes("error")) return "badge--error";
  if (type === "image_ready") return "badge--success";
  return "";
}

function pushEvent(type, data) {
  const entry = document.createElement("li");
  const header = document.createElement("div");
  header.className = "event-header";

  const badge = document.createElement("span");
  badge.className = `badge ${badgeClass(type)}`.trim();
  badge.textContent = EVENT_TITLES[type] || type;

  const time = document.createElement("span");
  time.textContent = new Date().toLocaleTimeString();

  header.append(badge, time);
  entry.appendChild(header);

  if (data !== null && data !== undefined) {
    if (typeof data === "string") {
      const body = document.createElement("p");
      body.textContent = data;
      entry.appendChild(body);
    } else {
      const pre = document.createElement("pre");
      pre.className = "event-json";
      pre.textContent = JSON.stringify(data, null, 2);
      entry.appendChild(pre);
    }
  }

  ui.events.prepend(entry);
  while (ui.events.children.length > 60) {
    ui.events.removeChild(ui.events.lastChild);
  }
}

function renderNoiseSummary() {
  if (!state.noise) {
    ui.noiseSummary.innerHTML = "<p>Загрузка параметров…</p>";
    return;
  }
  const { loss, ber, duplicate, reorder } = state.noise;
  ui.noiseSummary.innerHTML = `
    <strong>Текущие значения</strong><br />
    Потери: ${(loss * 100).toFixed(1)}% • BER: ${ber} • Дубликаты: ${(duplicate * 100).toFixed(
    1
  )}% • Перестановка: ${(reorder * 100).toFixed(1)}%
  `;
}

function renderProgress() {
  const entries = Array.from(state.progress.values()).sort((a, b) => b.updatedAt - a.updatedAt);
  ui.progressList.innerHTML = "";
  if (!entries.length) {
    const placeholder = document.createElement("li");
    placeholder.className = "progress-empty";
    placeholder.textContent = "Нет активных загрузок";
    ui.progressList.appendChild(placeholder);
    return;
  }

  entries.forEach((item) => {
    const li = document.createElement("li");
    li.className = "progress-item";

    const header = document.createElement("header");
    const title = document.createElement("span");
    title.textContent = item.fileId;
    const percent = document.createElement("strong");
    percent.textContent = item.progress != null ? formatPercent(item.progress) : "—";
    header.append(title, percent);

    const bar = document.createElement("div");
    bar.className = "progress-bar";
    const fill = document.createElement("span");
    fill.style.width = item.progress != null ? `${(item.progress * 100).toFixed(1)}%` : "0";
    bar.appendChild(fill);

    const meta = document.createElement("div");
    meta.className = "progress-meta";
    meta.innerHTML = `
      <span>Принято: ${item.receivedData}/${item.expected ?? "?"}</span>
      <span>Избыточность: ${item.receivedParity}</span>
      <span>Потеряно: ${item.missingTotal}</span>
    `;

    li.append(header, bar, meta);
    ui.progressList.appendChild(li);
  });
}

const STAGE_ORDER = ["init", "fec", "encryption", "compression", "final"];
const STAGE_TITLES = {
  init: "Инициализация",
  fec: "FEC",
  encryption: "Шифрование",
  compression: "Сжатие",
  final: "Финал",
};

function describeStage(stage, metrics = {}) {
  switch (stage) {
    case "init":
      return `Чанк ${formatBytes(metrics.chunk_size_bytes || 0)} • FEC ${
        metrics.fec_mode
      }${metrics.fec_mode === "rs" ? ` (${metrics.fec_k}/${metrics.fec_n})` : ""} • Шифрование ${
        metrics.encryption_enabled ? "вкл" : "выкл"
      }`;
    case "fec":
      return `Режим: ${metrics.mode} • Исправлено: ${metrics.corrected ?? 0}`;
    case "encryption":
      if (!metrics.enabled) return "Отключено";
      return `AES-GCM • Вход: ${formatBytes(metrics.input_bytes)} • Выход: ${formatBytes(
        metrics.output_bytes
      )}`;
    case "compression":
      if (!metrics.enabled) return "Отключено";
      return `${metrics.algorithm} • Вход: ${formatBytes(metrics.input_bytes)} • Выход: ${formatBytes(
        metrics.output_bytes
      )}`;
    case "final": {
      const matches = metrics.matches_expected_size;
      const matchLabel = matches == null ? "—" : matches ? "совпадает" : "не совпадает";
      return `Итог: ${formatBytes(metrics.size_bytes)} • Ожидалось: ${formatBytes(
        metrics.expected_size_bytes
      )} • ${matchLabel}`;
    }
    default:
      return JSON.stringify(metrics);
  }
}

function renderStageMetrics() {
  const entries = Array.from(state.stageMetrics.values()).sort(
    (a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)
  );
  ui.stageEntries.innerHTML = "";
  if (!entries.length) {
    ui.stageEntries.innerHTML = "<p>Пока нет данных. Загрузите изображение, чтобы увидеть этапы.</p>";
    return;
  }

  entries.forEach((entry) => {
    const card = document.createElement("article");
    card.className = "stage-card";
    const title = document.createElement("h3");
    title.textContent = entry.filename || entry.fileId;
    card.appendChild(title);

    const list = document.createElement("dl");
    STAGE_ORDER.forEach((stage) => {
      if (!entry.stages[stage]) return;
      const dt = document.createElement("dt");
      dt.textContent = STAGE_TITLES[stage] || stage;
      const dd = document.createElement("dd");
      dd.textContent = describeStage(stage, entry.stages[stage]);
      list.append(dt, dd);
    });

    card.appendChild(list);
    ui.stageEntries.appendChild(card);
  });
}

function recordStageMetrics(fileId, stage, metrics) {
  const existing = state.stageMetrics.get(fileId) || {
    fileId,
    stages: {},
    updatedAt: Date.now(),
    filename: null,
  };
  const updatedStages = { ...existing.stages, [stage]: metrics };
  const filename = metrics && metrics.filename ? metrics.filename : existing.filename;
  state.stageMetrics.set(fileId, {
    ...existing,
    stages: updatedStages,
    filename,
    updatedAt: Date.now(),
  });
  renderStageMetrics();
}

function applyImageStagesFromList(list) {
  list.forEach((item) => {
    const existing = state.stageMetrics.get(item.file_id) || {
      fileId: item.file_id,
      stages: {},
      filename: item.filename,
      updatedAt: Date.parse(item.uploaded_at) || Date.now(),
    };
    const stages = { ...existing.stages, ...item.stages };
    state.stageMetrics.set(item.file_id, {
      ...existing,
      stages,
      filename: item.filename,
      updatedAt: Date.parse(item.uploaded_at) || Date.now(),
    });
  });
  renderStageMetrics();
}

function showPreview(item) {
  ui.previewImage.src = `/api/image/${item.file_id}/raw`;
  ui.previewMeta.textContent = JSON.stringify(item.stages, null, 2);
}

async function fetchMetrics() {
  try {
    const response = await fetch("/api/metrics");
    if (!response.ok) throw new Error(`metrics ${response.status}`);
    const data = await response.json();
    ui.metricWindow.textContent = `${data.window_seconds} с`;
    ui.metricThroughput.textContent = `${data.throughput_kbps.toFixed(2)} кбит/с`;
    ui.metricRtt.textContent = `${data.average_rtt_ms.toFixed(2)} мс`;
    ui.metricFec.textContent = `${data.fec.mode} (исправлено: ${data.fec.corrected})`;

    const timeLabel = new Date().toLocaleTimeString();
    chartData.labels.push(timeLabel);
    chartData.values.push(data.throughput_kbps);
    if (chartData.labels.length > 30) {
      chartData.labels.shift();
      chartData.values.shift();
    }
    throughputChart.update();
  } catch (error) {
    pushEvent("ошибка", error.message);
  }
}

async function fetchImages() {
  try {
    const response = await fetch("/api/images");
    if (!response.ok) throw new Error(`images ${response.status}`);
    const images = await response.json();
    renderTable(images);
    applyImageStagesFromList(images);
  } catch (error) {
    pushEvent("ошибка", error.message);
  }
}

async function fetchNoise() {
  try {
    const response = await fetch("/api/config/channel");
    if (!response.ok) throw new Error(`noise ${response.status}`);
    state.noise = await response.json();
    renderNoiseSummary();
    if (state.noise) {
      ui.noiseForm.loss.value = (state.noise.loss * 100).toFixed(0);
      ui.noiseForm.ber.value = state.noise.ber;
      ui.noiseForm.duplicate.value = (state.noise.duplicate * 100).toFixed(0);
      ui.noiseForm.reorder.value = (state.noise.reorder * 100).toFixed(0);
    }
  } catch (error) {
    pushEvent("ошибка", error.message);
  }
}

function renderTable(images) {
  ui.tableBody.innerHTML = "";
  images.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.file_id}</td>
      <td>${item.filename}</td>
      <td>${Math.round((item.size_bytes || 0) / 1024)} КБ</td>
      <td>${new Date(item.uploaded_at).toLocaleString()}</td>
    `;
    row.addEventListener("click", () => showPreview(item));
    ui.tableBody.appendChild(row);
  });
}

async function updateNoise(event) {
  event.preventDefault();
  const formData = new FormData(ui.noiseForm);
  const body = {
    loss: Number(formData.get("loss")) / 100,
    ber: Number(formData.get("ber")),
    duplicate: Number(formData.get("duplicate")) / 100,
    reorder: Number(formData.get("reorder")) / 100,
  };
  try {
    const response = await fetch("/api/config/channel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`noise ${response.status}`);
    state.noise = await response.json();
    renderNoiseSummary();
    pushEvent("noise_config", state.noise);
  } catch (error) {
    pushEvent("ошибка", error.message);
  }
}

function handleUploadProgress(data) {
  if (!data || !data.file_id) return;
  state.progress.set(data.file_id, {
    fileId: data.file_id,
    expected: data.expected ?? null,
    receivedData: data.received_data ?? 0,
    receivedParity: data.received_parity ?? 0,
    receivedTotal: data.received_total ?? 0,
    missingTotal: data.missing_total ?? 0,
    bytes: data.bytes ?? 0,
    progress: typeof data.progress === "number" ? data.progress : null,
    updatedAt: Date.now(),
  });
  renderProgress();
}

function handleImageReady(data) {
  if (data && data.file_id) {
    state.progress.delete(data.file_id);
    renderProgress();
  }
  fetchImages();
}

function initSse() {
  try {
    const source = new EventSource("/api/events");

    source.onmessage = (event) => {
      const data = parseEventData(event.data);
      if (data) pushEvent("событие", data);
    };

    source.addEventListener("handshake", (event) => {
      const data = parseEventData(event.data);
      pushEvent("handshake", data);
    });

    source.addEventListener("upload_init", (event) => {
      const data = parseEventData(event.data);
      pushEvent("upload_init", data);
    });

    source.addEventListener("chunk", (event) => {
      const data = parseEventData(event.data);
      pushEvent("chunk", data);
    });

    source.addEventListener("upload_progress", (event) => {
      const data = parseEventData(event.data);
      handleUploadProgress(data);
    });

    source.addEventListener("stage_metrics", (event) => {
      const data = parseEventData(event.data);
      if (data && data.file_id && data.stage) {
        recordStageMetrics(data.file_id, data.stage, data.metrics || {});
        pushEvent("stage_metrics", data);
      }
    });

    source.addEventListener("noise_config", (event) => {
      const data = parseEventData(event.data);
      if (data) {
        state.noise = data;
        renderNoiseSummary();
        pushEvent("noise_config", data);
      }
    });

    source.addEventListener("image_ready", (event) => {
      const data = parseEventData(event.data);
      pushEvent("image_ready", data);
      handleImageReady(data);
    });
  } catch (error) {
    pushEvent("ошибка", `SSE: ${error.message}`);
  }
}

function bindUi() {
  ui.refreshBtn.addEventListener("click", () => {
    fetchImages();
    fetchMetrics();
    fetchNoise();
  });
  ui.noiseForm.addEventListener("submit", updateNoise);
}

bindUi();
initSse();
fetchImages();
fetchMetrics();
fetchNoise();
renderProgress();
renderStageMetrics();
setInterval(fetchMetrics, 5000);
