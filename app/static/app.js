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
  if (lastFeeds.length) renderConnectionHistory(lastFeeds);
}
setInterval(updateClock, 1000);
updateClock();

function sparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = (canvas.width = canvas.clientWidth * 2);
  const h = (canvas.height = canvas.clientHeight * 2);
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

function feedTiming(feed) {
  const now = Date.now();
  const completed = Number(feed.up_seconds || 0);
  if (feed.connected) {
    const started = parseTime(feed.connected_since);
    const session = started ? (now - started.getTime()) / 1000 : null;
    return { down: false, session, total: completed + Math.max(0, session || 0) };
  }
  const ended = parseTime(feed.disconnected_since);
  const downFor = ended ? (now - ended.getTime()) / 1000 : null;
  return { down: true, session: downFor, total: completed };
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
    const timing = feedTiming(feed);
    const status = feed.connected ? "up" : "down";
    let session = "—";
    if (feed.connected && timing.session != null) session = fmtDuration(timing.session);
    else if (!feed.connected && timing.session != null) session = `down ${fmtDuration(timing.session)}`;
    const uptime = timing.total >= 1 ? fmtDuration(timing.total) : "—";
    const error = feed.last_error ? escapeHtml(feed.last_error) : "—";
    return `
      <tr>
        <td>${escapeHtml(feed.name)}</td>
        <td class="${feed.connected ? "bid-px" : "ask-px"}">${status}</td>
        <td class="num">${session}</td>
        <td class="num">${uptime}</td>
        <td class="num">${feed.reconnects || 0}</td>
        <td>${fmtQuoteTime(feed.last_quote_at)}</td>
        <td class="err" title="${error}">${error}</td>
      </tr>`;
  });
  connRowsEl.innerHTML = rows.join("");
}

function renderCards(prices) {
  cardsEl.innerHTML = SYMBOLS.map((symbol) => {
    const price = prices[symbol];
    if (!price) {
      return `<article class="card"><div class="card-top"><div class="symbol">${prettySymbol(
        symbol
      )}</div><span class="muted">waiting</span></div><div class="mid">—</div><p class="muted">No quotes yet from connected venues.</p></article>`;
    }
        const prev = lastMids[symbol];
        const flash = prev == null ? "" : price.mid > prev ? "flash-up" : price.mid < prev ? "flash-down" : "";
        lastMids[symbol] = price.mid;
        const series = history[symbol];
        series.push(price.mid);
        if (series.length > 60) series.shift();
        return `
      <article class="card" data-symbol="${symbol}">
        <div class="card-top">
          <div class="symbol">${prettySymbol(symbol)}</div>
          <canvas class="spark" data-symbol="${symbol}"></canvas>
        </div>
        <div class="mid ${flash}">${fmt(price.mid, 2)}</div>
        <div class="bbo">
          <div class="bid">
            <span>Best bid</span>
            <strong>${fmt(price.bid, 2)}</strong>
            <div class="exchange">${price.bid_exchange}</div>
          </div>
          <div class="ask">
            <span>Best ask</span>
            <strong>${fmt(price.ask, 2)}</strong>
            <div class="exchange">${price.ask_exchange}</div>
          </div>
        </div>
        <div class="card-foot">
          <span>spread ${fmt(price.spread, 2)} · ${fmt(price.spread_bps, 1)} bps</span>
          <span>${new Date(price.ts).toISOString().slice(11, 19)}</span>
        </div>
      </article>`;
  }).join("");

  cardsEl.querySelectorAll("canvas.spark").forEach((canvas) => {
    sparkline(canvas, history[canvas.dataset.symbol] || []);
  });
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
  renderConnectionHistory(lastFeeds);
  renderCards(prices);
  renderTable(prices);
  renderArbs(prices);
}

async function poll() {
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
  ws.onopen = () => setPill(wsPill, true, "live");
  ws.onmessage = (event) => {
    setPill(wsPill, true, "live");
    applySnapshot(JSON.parse(event.data));
  };
  ws.onclose = () => {
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
