const $ = (id) => document.getElementById(id);
const POOL_TEXT = {
  stopped: "parado",
  starting: "arrancando",
  connecting: "conectando con el pool",
  connected: "conectado",
  reconnecting: "reintentando",
  auth_failed: "el pool rechazó la dirección",
  exited: "el minero se cerró",
};

const chart = $("chart");
const ctx = chart.getContext("2d");
let last = null;
let shownStop = "";

function formatRate(hs) {
  if (!hs) return "0 H/s";
  const units = [
    [1e18, "EH/s"],
    [1e15, "PH/s"],
    [1e12, "TH/s"],
    [1e9, "GH/s"],
    [1e6, "MH/s"],
    [1e3, "kH/s"],
  ];
  for (const [scale, name] of units) {
    if (hs >= scale) return `${(hs / scale).toFixed(2).replace(".", ",")} ${name}`;
  }
  return `${hs.toFixed(0)} H/s`;
}

function formatUptime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

function showNotice(text, kind) {
  const node = $("notice");
  if (!text) {
    node.hidden = true;
    node.textContent = "";
    node.className = "notice";
    return;
  }
  node.hidden = false;
  node.className = kind === "ok" ? "notice ok" : "notice";
  node.textContent = text;
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });
  let body = {};
  try {
    body = await response.json();
  } catch (_err) {
    body = {};
  }
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === "string"
      ? detail
      : "No pude completar esa acción.";
    throw new Error(message);
  }
  return body;
}

function draw(history) {
  const dpr = window.devicePixelRatio || 1;
  const width = chart.clientWidth;
  const height = 240;
  chart.width = Math.max(1, Math.floor(width * dpr));
  chart.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#f6f8f9";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#c5d0d6";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, height - 28);
  ctx.lineTo(width, height - 28);
  ctx.stroke();
  if (!history || history.length < 2) {
    ctx.fillStyle = "#5d6b78";
    ctx.font = "16px Avenir Next, Segoe UI, sans-serif";
    ctx.fillText("El gráfico se dibuja con el ritmo medido.", 16, 36);
    return;
  }
  const values = history.map((point) => point.hs);
  const max = Math.max(...values, 1);
  const left = 8;
  const right = width - 8;
  const top = 16;
  const bottom = height - 36;
  ctx.strokeStyle = "#c4511a";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = left + (index / (values.length - 1)) * (right - left);
    const y = bottom - (value / max) * (bottom - top);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#5d6b78";
  ctx.font = "14px Avenir Next, Segoe UI, sans-serif";
  ctx.fillText(`máximo de esta ventana ${formatRate(max)}`, 16, height - 10);
}

function renderOdds(data) {
  const node = $("odds-text");
  const odds = data.odds || {};
  if (!data.difficulty || data.difficulty.value == null) {
    node.textContent = data.difficulty && data.difficulty.error
      ? "No pude leer la dificultad en mempool.space. Reintento solo, sin salir de la máquina."
      : "Consultando la dificultad actual de la red.";
    return;
  }
  if (!data.running && !odds.ready) {
    node.textContent = `La dificultad ahora mismo es ${data.difficulty.value.toLocaleString("es-ES")}. Arranca el minero para convertir tu ritmo en una probabilidad.`;
    return;
  }
  if (!odds.ready) {
    node.textContent = "Todavía no hay un ritmo estable para calcular la probabilidad.";
    return;
  }
  node.textContent = `Con ${odds.hashrate_text} y dificultad ${odds.difficulty_text}, este iMac esperaría un bloque cada ${odds.years_text} años. En las próximas 24 horas la probabilidad es 1 entre ${odds.one_in_text}. Hacen falta ${odds.hashes_per_block_text} hashes para un bloque, y tu parte de la red es diminuta al lado de ${odds.network_hashrate_text}.`;
}

function render(data) {
  last = data;
  $("rate").textContent = data.running ? formatRate(data.hashrate_hs) : "0 H/s";
  $("average").textContent = data.hashrate_avg_hs
    ? (data.running
      ? `Media desde que se estabilizó: ${formatRate(data.hashrate_avg_hs)}`
      : `Última media, con el minero parado: ${formatRate(data.hashrate_avg_hs)}`)
    : "La media aparece unos segundos después del arranque, cuando pasa el primer pico.";
  $("pool").textContent = POOL_TEXT[data.pool] || data.pool || "parado";
  $("accepted").textContent = String(data.accepted ?? 0);
  $("rejected").textContent = String(data.rejected ?? 0);
  $("uptime").textContent = formatUptime(data.uptime_s);
  $("cpu").textContent = `${(data.cpu_percent || 0).toFixed(0)} %`;
  $("speed").textContent = data.speed_limit == null ? "sin dato" : `${data.speed_limit} de 100`;
  $("temp").textContent = data.cpu_temp_c == null ? "—" : `${Number(data.cpu_temp_c).toFixed(0)} °C`;
  $("temp").className = data.cpu_temp_c != null && data.cpu_temp_c >= 90 ? "temp hot" : "temp";
  $("temp-note").textContent = data.temp_note || "";
  const logs = data.logs || [];
  $("logs").textContent = logs.length ? logs.join("\n") : "Cuando arranque, las líneas aparecen aquí.";
  $("logs").scrollTop = $("logs").scrollHeight;
  $("start").disabled = !!data.running;
  $("stop").disabled = !data.running;
  $("address").disabled = !!data.running;
  if (data.level) selectLevel(data.level);
  if (data.running) shownStop = "";
  else if (data.pool === "exited" && shownStop !== "exited") {
    shownStop = "exited";
    showNotice("El minero se cerró solo. Las últimas líneas quedan abajo.");
  } else if (data.stop_reason && data.stop_reason !== shownStop) {
    shownStop = data.stop_reason;
    const thermal = /velocidad|temperatura|°C|núcleo/.test(data.stop_reason);
    showNotice(data.stop_reason, thermal ? "bad" : "ok");
  }
  renderOdds(data);
  draw(data.history || []);
}

async function refresh() {
  try {
    render(await api("/api/status"));
  } catch (err) {
    showNotice(err.message || "Perdí el contacto con el panel.");
  }
}

let selectedLevel = "medio";

function selectLevel(level) {
  selectedLevel = level;
  for (const name of ["bajo", "medio", "alto"]) {
    const button = $(`level-${name}`);
    if (button) button.setAttribute("aria-pressed", name === level ? "true" : "false");
  }
}

function levelHelp(cfg) {
  const cores = cfg.physical_cores || 8;
  const logical = cfg.logical_cpus || 16;
  return `Bajo usa 2 hilos, medio 4 y alto 8, uno por cada núcleo físico. Este iMac tiene ${cores} núcleos y ${logical} hilos. Alto calienta más; el panel para solo a 98 °C.`;
}

async function loadConfig() {
  const cfg = await api("/api/config");
  $("address").value = cfg.btc_address || "";
  selectLevel(cfg.level || "medio");
  $("thread-help").textContent = levelHelp(cfg);
  if (!cfg.miner_present) {
    showNotice("Falta bin/minerd. En la carpeta del proyecto ejecuta scripts/build-minerd.sh.");
  }
}

$("setup").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        btc_address: $("address").value,
        level: selectedLevel,
      }),
    });
    showNotice("Dirección guardada en este Mac. No se envía a ningún otro sitio.", "ok");
  } catch (err) {
    showNotice(err.message);
  }
});

document.querySelectorAll(".levels button").forEach((button) => {
  button.addEventListener("click", async () => {
    const level = button.dataset.level;
    selectLevel(level);
    try {
      const saved = await api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          btc_address: $("address").value,
          level,
        }),
      });
      showNotice(
        saved.restarted ? `Minando en ${level}.` : `Ritmo ${level} listo. Arranca cuando quieras.`,
        "ok",
      );
      await refresh();
    } catch (err) {
      showNotice(err.message);
    }
  });
});

$("start").addEventListener("click", async () => {
  showNotice("");
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        btc_address: $("address").value,
        level: selectedLevel,
      }),
    });
    await api("/api/start", {
      method: "POST",
      body: JSON.stringify({ level: selectedLevel }),
    });
    await refresh();
  } catch (err) {
    showNotice(err.message);
  }
});

$("stop").addEventListener("click", async () => {
  try {
    await api("/api/stop", { method: "POST", body: "{}" });
    await refresh();
  } catch (err) {
    showNotice(err.message);
  }
});

window.addEventListener("resize", () => {
  if (last) draw(last.history || []);
});

loadConfig().then(refresh).catch((err) => showNotice(err.message));
setInterval(refresh, 2000);
