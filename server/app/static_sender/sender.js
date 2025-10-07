const state = {
  file: null,
  handshake: null,
  sessionId: null,
};

const ui = {
  fileInput: document.getElementById("file-input"),
  fileLabel: document.getElementById("file-label"),
  preview: document.getElementById("preview"),
  handshakeBtn: document.getElementById("btn-handshake"),
  uploadBtn: document.getElementById("btn-upload-once"),
  compressionToggle: document.getElementById("compression-toggle"),
  compressionLevel: document.getElementById("compression-level"),
  compressionLevelValue: document.getElementById("compression-level-value"),
  encryptionToggle: document.getElementById("encryption-toggle"),
  fecMode: document.getElementById("fec-mode"),
  rsN: document.getElementById("rs-n"),
  rsK: document.getElementById("rs-k"),
  chunkSize: document.getElementById("chunk-size"),
  progressBar: document.getElementById("progress-bar"),
  log: document.getElementById("log"),
  events: document.getElementById("events"),
};

function logLine(message) {
  const timestamp = new Date().toLocaleTimeString();
  ui.log.textContent = `[${timestamp}] ${message}\n` + ui.log.textContent;
}

function setProgress(value) {
  ui.progressBar.style.width = `${Math.round(value * 100)}%`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

function base64ToArrayBuffer(str) {
  const binary = atob(str);
  const len = binary.length;
  const buffer = new ArrayBuffer(len);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < len; i += 1) {
    view[i] = binary.charCodeAt(i);
  }
  return buffer;
}

function nonceFromBase(baseBigInt, sequence) {
  const limit = (1n << 96n) - 1n;
  const value = (baseBigInt + BigInt(sequence)) & limit;
  const bytes = new Uint8Array(12);
  for (let i = 0; i < 12; i += 1) {
    bytes[11 - i] = Number((value >> BigInt(i * 8)) & 0xffn);
  }
  return bytes;
}

async function performHandshake() {
  if (
    !window.crypto ||
    !window.crypto.subtle ||
    typeof window.crypto.subtle.generateKey !== "function"
  ) {
    logLine("⚠️ Браузер не поддерживает WebCrypto, шифрование недоступно.");
    return;
  }
  try {
    ui.handshakeBtn.disabled = true;
    logLine("Запускаю рукопожатие...");

    const keyPair = await crypto.subtle.generateKey(
      {
        name: "X25519",
        namedCurve: "X25519",
      },
      true,
      ["deriveBits"]
    );

    const publicKeyRaw = await crypto.subtle.exportKey("raw", keyPair.publicKey);
    const clientPublicKey = arrayBufferToBase64(publicKeyRaw);

    const handshakeResponse = await fetch("/api/handshake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_public_key: clientPublicKey }),
    });

    if (!handshakeResponse.ok) {
      throw new Error(`Ошибка рукопожатия: ${handshakeResponse.status}`);
    }

    const handshakeData = await handshakeResponse.json();
    const serverPublic = base64ToArrayBuffer(handshakeData.server_public_key);
    const serverPublicKey = await crypto.subtle.importKey(
      "raw",
      serverPublic,
      { name: "X25519", namedCurve: "X25519" },
      false,
      []
    );

    const sharedSecret = await crypto.subtle.deriveBits(
      {
        name: "X25519",
        public: serverPublicKey,
      },
      keyPair.privateKey,
      256
    );

    const hkdfKey = await crypto.subtle.importKey("raw", sharedSecret, "HKDF", false, [
      "deriveKey",
    ]);

    const salt = base64ToArrayBuffer(handshakeData.salt);
    const info = new TextEncoder().encode("image-http-lab-handshake");
    const aesKey = await crypto.subtle.deriveKey(
      { name: "HKDF", hash: "SHA-256", salt, info },
      hkdfKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt"]
    );

    const nonceBaseBytes = new Uint8Array(base64ToArrayBuffer(handshakeData.nonce_base));
    let base = 0n;
    nonceBaseBytes.forEach((byte) => {
      base = (base << 8n) | BigInt(byte);
    });

    state.handshake = {
      aesKey,
      nonceBase: base,
      sessionId: handshakeData.session_id,
    };
    state.sessionId = handshakeData.session_id;

    logLine(`Сессия установлена: ${handshakeData.session_id}`);
  } catch (error) {
    logLine(`⚠️ ${error.message}`);
  } finally {
    ui.handshakeBtn.disabled = false;
  }
}

function handleFileChange(event) {
  const file = event.target.files[0];
  if (!file) {
    state.file = null;
    ui.fileLabel.textContent = "Выберите файл";
    ui.preview.innerHTML = "";
    return;
  }
  state.file = file;
  ui.fileLabel.textContent = `${file.name} (${Math.round(file.size / 1024)} КБ)`;

  const reader = new FileReader();
  reader.onload = (e) => {
    ui.preview.innerHTML = `<img src="${e.target.result}" alt="Превью" />`;
  };
  reader.readAsDataURL(file);
}

function gatherPipeline() {
  const compressionEnabled = ui.compressionToggle.checked;
  const compressionLevel = Number(ui.compressionLevel.value);
  const encryptionEnabled = ui.encryptionToggle.checked;
  const fecMode = ui.fecMode.value;

  const pipeline = {
    compression: {
      enabled: compressionEnabled,
      level: compressionLevel,
      algorithm: "deflate",
    },
    encryption: {
      enabled: encryptionEnabled,
      session_id: encryptionEnabled ? state.sessionId : null,
    },
    fec: {
      mode: fecMode,
      n: Number(ui.rsN.value),
      k: Number(ui.rsK.value),
    },
  };

  return pipeline;
}

async function compressIfNeeded(bytes, pipeline) {
  if (!pipeline.compression.enabled || !("CompressionStream" in window)) {
    if (!("CompressionStream" in window) && pipeline.compression.enabled) {
      logLine("CompressionStream недоступен, сжатие пропускается.");
    }
    return { data: bytes, level: pipeline.compression.level };
  }

  const cs = new CompressionStream("deflate-raw");
  const writer = cs.writable.getWriter();
  await writer.write(bytes);
  await writer.close();
  const compressed = new Uint8Array(await new Response(cs.readable).arrayBuffer());
  return { data: compressed, level: pipeline.compression.level };
}

async function encryptIfNeeded(bytes, pipeline) {
  if (!pipeline.encryption.enabled) {
    return { data: bytes, parts: [bytes] };
  }
  if (!window.crypto || !window.crypto.subtle) {
    throw new Error("WebCrypto недоступен, шифрование невозможно.");
  }
  if (!state.handshake || !state.handshake.aesKey) {
    throw new Error("Сначала выполните рукопожатие.");
  }

  const nonce = nonceFromBase(state.handshake.nonceBase, 0);
  const encrypted = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, state.handshake.aesKey, bytes)
  );
  return { data: encrypted, parts: [encrypted] };
}

async function sendChunk(fileId, chunkBytes, sequence, total, pipeline, meta) {
  const body = {
    file_id: fileId,
    session_id: pipeline.encryption.enabled ? state.sessionId : null,
    sequence,
    total_sequences: total,
    payload: arrayBufferToBase64(chunkBytes.buffer),
    is_parity: false,
    meta,
  };

  const response = await fetch("/api/chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Чанк ${sequence} не принят: ${text}`);
  }
}

async function sendFile() {
  if (!state.file) {
    logLine("Выберите файл перед отправкой.");
    return;
  }

  const pipeline = gatherPipeline();
  if (pipeline.encryption.enabled && !state.handshake) {
    logLine("Выполните рукопожатие перед включением шифрования.");
    return;
  }

  try {
    ui.uploadBtn.disabled = true;
    setProgress(0);
    logLine("Читаю файл...");

    const fileBytes = new Uint8Array(await state.file.arrayBuffer());
    const compressed = await compressIfNeeded(fileBytes, pipeline);
    const encrypted = await encryptIfNeeded(compressed.data, pipeline);

    const chunkSizeBytes = Number(ui.chunkSize.value) * 1024;
    const totalChunks = Math.max(1, Math.ceil(encrypted.data.byteLength / chunkSizeBytes));

    const initResponse = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: state.file.name,
        mime_type: state.file.type || "application/octet-stream",
        pipeline,
        session_id: pipeline.encryption.enabled ? state.sessionId : null,
      }),
    });

    if (!initResponse.ok) {
      const text = await initResponse.text();
      throw new Error(`Ошибка инициализации: ${text}`);
    }

    const initData = await initResponse.json();
    logLine(`Загрузка "${state.file.name}" началась, файл_id: ${initData.file_id}`);

    const meta = {
      original_size: fileBytes.byteLength,
      compressed_size: compressed.data.byteLength,
      encrypted_size: encrypted.data.byteLength,
      chunk_size: chunkSizeBytes,
    };

    for (let seq = 0; seq < totalChunks; seq += 1) {
      const start = seq * chunkSizeBytes;
      const end = Math.min(start + chunkSizeBytes, encrypted.data.byteLength);
      const chunk = encrypted.data.slice(start, end);
      await sendChunk(initData.file_id, chunk, seq, totalChunks, pipeline, meta);
      setProgress((seq + 1) / totalChunks);
    }

    const finishResponse = await fetch("/api/finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: initData.file_id }),
    });

    if (!finishResponse.ok) {
      const text = await finishResponse.text();
      throw new Error(`Финализация не удалась: ${text}`);
    }

    const finishData = await finishResponse.json();
    logLine(`Готово! Файл сохранён: ${finishData["сохранён"]}`);
  } catch (error) {
    logLine(`⚠️ ${error.message}`);
  } finally {
    ui.uploadBtn.disabled = false;
    setProgress(0);
  }
}

function initEventStream() {
  try {
    const source = new EventSource("/api/events");
    source.onmessage = (event) => {
      pushEventRow("сообщение", event.data);
    };
    source.addEventListener("handshake", (event) => pushEventRow("рукопожатие", event.data));
    source.addEventListener("chunk", (event) => pushEventRow("чанк", event.data));
    source.addEventListener("image_ready", (event) => pushEventRow("готово", event.data));
    source.onerror = () => pushEventRow("ошибка", "Проблема с SSE");
  } catch (error) {
    logLine(`SSE недоступно: ${error.message}`);
  }
}

function pushEventRow(type, payload) {
  const li = document.createElement("li");
  li.textContent = `${type}: ${payload}`;
  ui.events.prepend(li);
  while (ui.events.children.length > 30) {
    ui.events.removeChild(ui.events.lastChild);
  }
}

function bindUi() {
  ui.fileInput.addEventListener("change", handleFileChange);
  ui.handshakeBtn.addEventListener("click", performHandshake);
  ui.uploadBtn.addEventListener("click", sendFile);
  ui.compressionLevel.addEventListener("input", (event) => {
    ui.compressionLevelValue.textContent = event.target.value;
  });
}

bindUi();
initEventStream();
logLine("Готов к работе.");

if (
  !window.crypto ||
  !window.crypto.subtle ||
  typeof window.crypto.subtle.generateKey !== "function" ||
  typeof window.crypto.subtle.encrypt !== "function"
) {
  ui.handshakeBtn.disabled = true;
  ui.encryptionToggle.checked = false;
  ui.encryptionToggle.disabled = true;
  logLine("⚠️ WebCrypto недоступен — шифрование отключено.");
}
