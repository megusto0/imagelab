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
  chartCanvas: document.getElementById("chart-throughput"),
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
      },
    ],
  },
  options: {},
});

function pushEvent(type, payload) {
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()} — ${type}: ${payload}`;
  ui.events.prepend(li);
  while (ui.events.children.length > 40) {
    ui.events.removeChild(ui.events.lastChild);
  }
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
    if (chartData.labels.length > 20) {
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

async function showPreview(item) {
  ui.previewImage.src = `/api/image/${item.file_id}/raw`;
  ui.previewMeta.textContent = JSON.stringify(item.stages, null, 2);
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
    const data = await response.json();
    pushEvent("помехи", JSON.stringify(data));
  } catch (error) {
    pushEvent("ошибка", error.message);
  }
}

function initSse() {
  try {
    const source = new EventSource("/api/events");
    source.onmessage = (event) => pushEvent("событие", event.data);
    source.addEventListener("upload_init", (event) =>
      pushEvent("загрузка", event.data)
    );
    source.addEventListener("image_ready", (event) => {
      pushEvent("готово", event.data);
      fetchImages();
    });
  } catch (error) {
    pushEvent("ошибка", `SSE: ${error.message}`);
  }
}

function bindUi() {
  ui.refreshBtn.addEventListener("click", () => {
    fetchImages();
    fetchMetrics();
  });
  ui.noiseForm.addEventListener("submit", updateNoise);
}

bindUi();
initSse();
fetchImages();
fetchMetrics();
setInterval(fetchMetrics, 5000);
