const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
const history = Object.fromEntries(SYMBOLS.map((s) => [s, []]));
const lastMids = {};

const cardsEl = document.getElementById("cards");
const feedsEl = document.getElementById("feeds");
const rowsEl = document.getElementById("quote-rows");
const arbRowsEl = document.getElementById("arb-rows");
const arbCountEl = document.getElementById("arb-count");
const connRowsEl = document.getElementById("conn-rows");
const wsPill = document.getElementById("ws-pill");
const clockEl = document.getElementById("clock");
const FEED_NAMES = ["binance", "coinbase", "kraken", "shakepay"];
let lastFeeds = [];
let wsLive = false;
let lastTablePaint = 0;
let lastConnPaint = 0;

function fmt(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtSize(n) {
  if (n == null) return "—";
  if (n >= 1000) return fmt(n, 1);
  return fmt(n, 4);
}

function prettySymbol(symbol) {
  return symbol.replace("USDT", "/USDT");
}

function setPill(el, connected, label) {
  el.classList.toggle("live", connected);
  el.classList.toggle("down", !connected);
  el.textContent = label;
}

function updateClock() {
  clockEl.textContent = new Date().toISOString().slice(11, 19) + " UTC";
}
setInterval(updateClock, 1000);
updateClock();

function sparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = Math.max(1, Math.round(canvas.clientWidth * 2));
  const h = Math.max(1, Math.round(canvas.clientHeight * 2));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  ctx.clearRect(0, 0, w, h);
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 6) - 3;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  const up = values[values.length - 1] >= values[0];
  ctx.strokeStyle = up ? "#7dba8e" : "#d97a78";
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

function renderFeeds(feeds = []) {
  const names = feeds.length ? feeds.map((f) => f.name) : FEED_NAMES;
  const byName = Object.fromEntries((feeds || []).map((f) => [f.name, f]));
  feedsEl.innerHTML = names
    .map((name) => {
      const feed = byName[name];
      const connected = feed ? feed.connected : false;
      const label = connected || !feed ? name : `${name} down`;
      const cls = feed ? (connected ? "live" : "down") : "";
      return `<div class="feed-pill ${cls}"><span class="dot"></span>${label}</div>`;
    })
    .join("");
}

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(sec).padStart(2, "0")}s`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

function parseTime(iso) {
  if (!iso) return null;
  const direct = new Date(iso);
  if (!Number.isNaN(direct.getTime())) return direct;
  const trimmed = String(iso).replace(/(\.\d{3})\d+/, "$1");
  const fallback = new Date(trimmed);
  if (!Number.isNaN(fallback.getTime())) return fallback;
  return null;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtQuoteTime(iso) {
  const at = parseTime(iso);
  if (!at) return "—";
  const ms = Date.now() - at.getTime();
  if (ms < 5000) return "just now";
  return `${fmtDuration(ms / 1000)} ago`;
}

function renderConnectionHistory(feeds = []) {
  const rows = (feeds.length ? feeds : FEED_NAMES.map((name) => ({ name, connected: false }))).map((feed) => {
    const status = feed.connected ? "up" : "down";
    return `
      <tr>
        <td>${escapeHtml(feed.name)}</td>
        <td class="${feed.connected ? "bid-px" : "ask-px"}">${status}</td>
        <td class="mono">${feed.reconnects || 0}</td>
        <td class="mono">${fmtQuoteTime(feed.last_quote_at)}</td>
        <td class="mono">${fmtQuoteTime(feed.disconnected_since)}</td>
      </tr>`;
  });
  connRowsEl.innerHTML = rows.join("");
}

function cardHtml(symbol) {
  return `<article class="card" data-symbol="${symbol}">
    <div class="card-top">
      <div class="symbol">${prettySymbol(symbol)}</div>
      <canvas class="spark" data-symbol="${symbol}"></canvas>
    </div>
    <div class="mid" data-mid>—</div>
    <p class="muted" data-wait>No quotes yet from connected venues.</p>
    <div class="bbo" data-bbo hidden>
      <div class="bid">
        <span>Best bid</span>
        <strong data-bid>—</strong>
        <div class="exchange" data-bid-ex></div>
      </div>
      <div class="ask">
        <span>Best ask</span>
        <strong data-ask>—</strong>
        <div class="exchange" data-ask-ex></div>
      </div>
    </div>
    <div class="card-foot" data-foot hidden>
      <span data-spread></span>
      <span data-ts></span>
    </div>
  </article>`;
}

function ensureCards() {
  if (cardsEl.querySelector("[data-symbol]")) return;
  cardsEl.innerHTML = SYMBOLS.map(cardHtml).join("");
}

function renderCards(prices) {
  ensureCards();
  for (const symbol of SYMBOLS) {
    const article = cardsEl.querySelector(`[data-symbol="${symbol}"]`);
    const price = prices[symbol];
    const wait = article.querySelector("[data-wait]");
    const bbo = article.querySelector("[data-bbo]");
    const foot = article.querySelector("[data-foot]");
    const midEl = article.querySelector("[data-mid]");
    if (!price) {
      wait.hidden = false;
      bbo.hidden = true;
      foot.hidden = true;
      midEl.textContent = "—";
      continue;
    }
    wait.hidden = true;
    bbo.hidden = false;
    foot.hidden = false;
    const prev = lastMids[symbol];
    midEl.classList.remove("flash-up", "flash-down");
    if (prev != null && price.mid !== prev) {
      void midEl.offsetWidth;
      midEl.classList.add(price.mid > prev ? "flash-up" : "flash-down");
    }
    midEl.textContent = fmt(price.mid, 2);
    article.querySelector("[data-bid]").textContent = fmt(price.bid, 2);
    article.querySelector("[data-bid-ex]").textContent = price.bid_exchange;
    article.querySelector("[data-ask]").textContent = fmt(price.ask, 2);
    article.querySelector("[data-ask-ex]").textContent = price.ask_exchange;
    article.querySelector("[data-spread]").textContent = `spread ${fmt(price.spread, 2)} · ${fmt(price.spread_bps, 1)} bps`;
    article.querySelector("[data-ts]").textContent = new Date(price.ts).toISOString().slice(11, 19);
    if (price.mid !== prev) {
      const series = history[symbol];
      series.push(price.mid);
      if (series.length > 60) series.shift();
      lastMids[symbol] = price.mid;
      sparkline(article.querySelector("canvas.spark"), series);
    }
  }
}

function renderTable(prices) {
  const rows = [];
  for (const symbol of SYMBOLS) {
    const price = prices[symbol];
    if (!price || !price.quotes) continue;
    for (const q of price.quotes) {
      const bestBid = q.exchange === price.bid_exchange ? "best-bid" : "";
      const bestAsk = q.exchange === price.ask_exchange ? "best-ask" : "";
      const received = parseTime(q.received_at);
      const ageMs = received ? Date.now() - received.getTime() : 0;
      rows.push(`
        <tr class="${bestBid} ${bestAsk}">
          <td>${prettySymbol(symbol)}</td>
          <td>${q.exchange}</td>
          <td class="num">${fmt(q.bid, 2)}</td>
          <td class="num">${fmtSize(q.bid_size)}</td>
          <td class="num">${fmt(q.ask, 2)}</td>
          <td class="num">${fmtSize(q.ask_size)}</td>
          <td class="num">${fmt(q.ask - q.bid, 2)}</td>
          <td>${Math.max(0, Math.round(ageMs / 1000))}s</td>
        </tr>`);
    }
  }
  rowsEl.innerHTML = rows.length
    ? rows.join("")
    : `<tr><td colspan="8" class="empty">Waiting for the first quotes…</td></tr>`;
}

function findArbs(prices) {
  const arbs = [];
  for (const symbol of SYMBOLS) {
    const price = prices[symbol];
    if (!price || !price.quotes) continue;
    for (const buy of price.quotes) {
      for (const sell of price.quotes) {
        if (buy.exchange === sell.exchange) continue;
        const edge = sell.bid - buy.ask;
        if (edge <= 0) continue;
        const mid = (sell.bid + buy.ask) / 2;
        arbs.push({
          symbol,
          buyExchange: buy.exchange,
          sellExchange: sell.exchange,
          ask: buy.ask,
          bid: sell.bid,
          edge,
          edgeBps: mid ? (edge / mid) * 10000 : 0,
        });
      }
    }
  }
  arbs.sort((a, b) => b.edgeBps - a.edgeBps);
  return arbs;
}

function renderArbs(prices) {
  const arbs = findArbs(prices);
  arbCountEl.textContent = arbs.length ? String(arbs.length) : "";
  if (!arbs.length) {
    arbRowsEl.innerHTML = `<tr><td colspan="7" class="empty">No crossed books right now.</td></tr>`;
    return;
  }
  arbRowsEl.innerHTML = arbs
    .map(
      (arb) => `
        <tr>
          <td>${prettySymbol(arb.symbol)}</td>
          <td>${arb.buyExchange}</td>
          <td class="num ask-px">${fmt(arb.ask, 2)}</td>
          <td>${arb.sellExchange}</td>
          <td class="num bid-px">${fmt(arb.bid, 2)}</td>
          <td class="num edge">${fmt(arb.edge, 2)}</td>
          <td class="num edge">${fmt(arb.edgeBps, 1)}</td>
        </tr>`
    )
    .join("");
}

function applySnapshot(payload) {
  const prices = payload.prices || payload;
  lastFeeds = payload.feeds || lastFeeds;
  renderFeeds(lastFeeds);
  renderCards(prices);
  const now = Date.now();
  if (now - lastTablePaint >= 250) {
    lastTablePaint = now;
    renderTable(prices);
    renderArbs(prices);
  }
  if (now - lastConnPaint >= 1000) {
    lastConnPaint = now;
    renderConnectionHistory(lastFeeds);
  }
}

async function poll() {
  if (wsLive) return;
  try {
    const [prices, health] = await Promise.all([
      fetch("/prices").then((r) => r.json()),
      fetch("/health").then((r) => r.json()),
    ]);
    applySnapshot({ prices, feeds: health.feeds });
  } catch (err) {
    setPill(wsPill, false, "poll failed");
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/prices`);
  ws.onopen = () => {
    wsLive = true;
    setPill(wsPill, true, "live");
  };
  ws.onmessage = (event) => {
    setPill(wsPill, true, "live");
    applySnapshot(JSON.parse(event.data));
  };
  ws.onclose = () => {
    wsLive = false;
    setPill(wsPill, false, "reconnecting");
    setTimeout(connectWs, 1500);
  };
  ws.onerror = () => ws.close();
}

renderFeeds([]);
renderConnectionHistory([]);
connectWs();
setInterval(poll, 4000);
bindHeaderTips();

function bindHeaderTips() {
  const tip = document.createElement("div");
  tip.className = "header-tip";
  document.body.appendChild(tip);

  function hide() {
    tip.classList.remove("show");
  }

  function show(th) {
    const text = th.getAttribute("data-tip");
    if (!text) return;
    tip.textContent = text;
    const rect = th.getBoundingClientRect();
    const left = Math.min(Math.max(rect.left + rect.width / 2, 140), window.innerWidth - 140);
    tip.style.left = `${left}px`;
    tip.style.top = `${rect.bottom + 8}px`;
    tip.classList.add("show");
    const tipHeight = tip.getBoundingClientRect().height;
    if (rect.bottom + 8 + tipHeight > window.innerHeight - 8) {
      tip.style.top = `${Math.max(8, rect.top - tipHeight - 8)}px`;
    }
  }

  document.querySelectorAll("th[data-tip]").forEach((th) => {
    th.addEventListener("mouseenter", () => show(th));
    th.addEventListener("mouseleave", hide);
    th.addEventListener("focus", () => show(th));
    th.addEventListener("blur", hide);
  });
}
