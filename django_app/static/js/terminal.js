/**
 * ChronosMatch Real-Time Web Trading Terminal JavaScript
 * Handles live polling, Level 2 depth rendering, trade tape updates,
 * Chart.js streaming, and simulated order submission.
 */

let selectedSide = 'BUY';
let pollInterval = null;
let priceHistory = [];
let throughputHistory = [];
let timestamps = [];
let marketChart = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  initFormListeners();
  startPolling();
});

function initChart() {
  const ctx = document.getElementById('marketChart');
  if (!ctx) return;

  marketChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Market Price ($)',
          data: [],
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.1)',
          borderWidth: 2,
          pointRadius: 1,
          tension: 0.2,
          yAxisID: 'yPrice',
          fill: true,
        },
        {
          label: 'Throughput (ops/sec)',
          data: [],
          borderColor: '#06b6d4',
          borderWidth: 1.5,
          pointRadius: 0,
          borderDash: [4, 4],
          tension: 0.2,
          yAxisID: 'yOps',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        intersect: false,
        mode: 'index',
      },
      scales: {
        x: {
          display: true,
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#8b949e', font: { family: 'monospace', size: 10 } }
        },
        yPrice: {
          type: 'linear',
          display: true,
          position: 'left',
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#38bdf8', font: { family: 'monospace', size: 10 } }
        },
        yOps: {
          type: 'linear',
          display: true,
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#06b6d4', font: { family: 'monospace', size: 10 } }
        }
      },
      plugins: {
        legend: {
          labels: { color: '#8b949e', font: { size: 11 } }
        }
      }
    }
  });
}

function initFormListeners() {
  const priceInput = document.getElementById('order-price');
  const qtyInput = document.getElementById('order-quantity');

  function updateEstTotal() {
    const px = parseFloat(priceInput.value) || 0;
    const qty = parseInt(qtyInput.value, 10) || 0;
    const total = px * qty;
    document.getElementById('order-est-total').innerText = '$' + total.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  if (priceInput && qtyInput) {
    priceInput.addEventListener('input', updateEstTotal);
    qtyInput.addEventListener('input', updateEstTotal);
  }
}

function selectSide(side) {
  selectedSide = side;
  const buyBtn = document.getElementById('btn-side-buy');
  const sellBtn = document.getElementById('btn-side-sell');
  const submitBtn = document.getElementById('btn-order-submit');

  if (side === 'BUY') {
    buyBtn.classList.add('selected');
    sellBtn.classList.remove('selected');
    submitBtn.className = 'btn-submit buy';
    submitBtn.innerText = 'SUBMIT BUY ORDER';
  } else {
    sellBtn.classList.add('selected');
    buyBtn.classList.remove('selected');
    submitBtn.className = 'btn-submit sell';
    submitBtn.innerText = 'SUBMIT SELL ORDER';
  }
}

function startPolling() {
  fetchMarketData();
  pollInterval = setInterval(fetchMarketData, 500);
}

async function fetchMarketData() {
  try {
    const response = await fetch('/api/market-data/');
    if (!response.ok) {
      throw new Error(`HTTP error ${response.status}`);
    }
    const data = await response.json();
    updateUI(data);
    document.getElementById('connection-status').innerText = 'SYSTEM CONNECTED (Polling 500ms)';
    document.getElementById('connection-status').style.color = 'var(--bid-green)';
  } catch (err) {
    document.getElementById('connection-status').innerText = 'DISCONNECTED — Retrying...';
    document.getElementById('connection-status').style.color = 'var(--ask-red)';
  }
}

function updateUI(data) {
  // Engine & Simulator status pills
  const engStatus = data.engine_status || 'IDLE';
  const simRunning = data.simulator_running;
  
  document.getElementById('engine-status-text').innerText = engStatus;
  document.getElementById('sim-status-text').innerText = simRunning ? 'RUNNING' : 'IDLE';

  const simDot = document.getElementById('sim-dot');
  if (simRunning) {
    simDot.className = 'pulse-dot active';
  } else {
    simDot.className = 'pulse-dot';
  }

  // Ticker updates
  const bestBid = data.best_bid;
  const bestAsk = data.best_ask;
  const spread = data.spread;
  const lastPrice = data.last_price;

  document.getElementById('ticker-market-price').innerText = lastPrice !== null ? `$${lastPrice.toFixed(2)}` : '--.--';
  document.getElementById('ticker-best-bid').innerText = bestBid ? `$${bestBid[0].toFixed(2)}` : '--.--';
  document.getElementById('ticker-best-ask').innerText = bestAsk ? `$${bestAsk[0].toFixed(2)}` : '--.--';
  document.getElementById('ticker-spread').innerText = spread !== null ? `$${spread.toFixed(2)}` : '--.--';

  const metrics = data.metrics || {};
  document.getElementById('ticker-throughput').innerText = `${(metrics.throughput_ops || 0).toLocaleString('en-US', {maximumFractionDigits: 1})} ops/s`;
  document.getElementById('ticker-orders-count').innerText = (metrics.orders_processed || 0).toLocaleString('en-US');
  document.getElementById('ticker-trades-count').innerText = (metrics.trades_executed || 0).toLocaleString('en-US');

  // Book divider
  document.getElementById('book-spread-text').innerText = spread !== null ? `$${spread.toFixed(2)}` : 'N/A';
  document.getElementById('book-last-text').innerText = lastPrice !== null ? `$${lastPrice.toFixed(2)}` : 'N/A';

  // Render Order Book Tables
  renderOrderBook(data.depth || { bids: [], asks: [] });

  // Render Trades Tape
  renderTradesTape(data.recent_trades || []);

  // Latency Metrics
  const lat = metrics.latency || {};
  document.getElementById('lat-engine-mean').innerText = lat.match_mean_us !== undefined ? `${lat.match_mean_us.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-engine-p95').innerText = lat.match_p95_us !== undefined ? `${lat.match_p95_us.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-engine-p99').innerText = lat.match_p99_us !== undefined ? `${lat.match_p99_us.toFixed(2)} µs` : '-- µs';

  document.getElementById('lat-e2e-mean').innerText = lat.e2e_mean_us !== undefined ? `${lat.e2e_mean_us.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-e2e-p95').innerText = lat.e2e_p95_us !== undefined ? `${lat.e2e_p95_us.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-e2e-p99').innerText = lat.e2e_p99_us !== undefined ? `${lat.e2e_p99_us.toFixed(2)} µs` : '-- µs';

  // Telemetry Chart Stream
  updateChartData(lastPrice || (bestBid ? bestBid[0] : 100.0), metrics.throughput_ops || 0.0);
}

function renderOrderBook(depth) {
  const asksTbody = document.getElementById('order-book-asks');
  const bidsTbody = document.getElementById('order-book-bids');

  // Find max volume across top levels for depth bar normalization
  let maxQty = 1;
  depth.asks.forEach(a => { if (a.total_quantity > maxQty) maxQty = a.total_quantity; });
  depth.bids.forEach(b => { if (b.total_quantity > maxQty) maxQty = b.total_quantity; });

  // Render Asks (reversed so lowest ask is closest to spread divider)
  if (!depth.asks || depth.asks.length === 0) {
    asksTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-dim); padding: 15px;">No resting asks</td></tr>';
  } else {
    const reversedAsks = [...depth.asks].reverse();
    let askHtml = '';
    let cumQty = 0;
    reversedAsks.forEach(a => {
      cumQty += a.total_quantity;
      const pct = Math.min(100, Math.round((a.total_quantity / maxQty) * 100));
      askHtml += `
        <tr class="order-book-row ask">
          <td style="color: var(--ask-red); font-weight: 600;">$${a.price.toFixed(2)}</td>
          <td>${a.total_quantity.toLocaleString()}</td>
          <td>${cumQty.toLocaleString()}</td>
          <div class="depth-bar ask" style="width: ${pct}%;"></div>
        </tr>
      `;
    });
    asksTbody.innerHTML = askHtml;
  }

  // Render Bids (highest bid first, directly under spread divider)
  if (!depth.bids || depth.bids.length === 0) {
    bidsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-dim); padding: 15px;">No resting bids</td></tr>';
  } else {
    let bidHtml = '';
    let cumQty = 0;
    depth.bids.forEach(b => {
      cumQty += b.total_quantity;
      const pct = Math.min(100, Math.round((b.total_quantity / maxQty) * 100));
      bidHtml += `
        <tr class="order-book-row bid">
          <td style="color: var(--bid-green); font-weight: 600;">$${b.price.toFixed(2)}</td>
          <td>${b.total_quantity.toLocaleString()}</td>
          <td>${cumQty.toLocaleString()}</td>
          <div class="depth-bar bid" style="width: ${pct}%;"></div>
        </tr>
      `;
    });
    bidsTbody.innerHTML = bidHtml;
  }
}

function renderTradesTape(trades) {
  const container = document.getElementById('trades-tape');
  if (!trades || trades.length === 0) {
    container.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 25px;">No trades executed yet.</div>';
    return;
  }

  let html = '';
  // Most recent first
  const reversed = [...trades].reverse();
  reversed.forEach(t => {
    const d = new Date(t.timestamp_ns / 1000000);
    const timeStr = d.toTimeString().split(' ')[0] + '.' + String(d.getMilliseconds()).padStart(3, '0');
    html += `
      <div class="trade-row">
        <span>${timeStr}</span>
        <span class="trade-buy">TRADE</span>
        <span style="font-weight: 600;">$${t.price.toFixed(2)}</span>
        <span>${t.quantity.toLocaleString()} (B:#${t.buy_order_id} / S:#${t.sell_order_id})</span>
      </div>
    `;
  });
  container.innerHTML = html;
}

function updateChartData(price, throughput) {
  if (!marketChart) return;

  const now = new Date();
  const timeLabel = now.toTimeString().split(' ')[0];

  marketChart.data.labels.push(timeLabel);
  marketChart.data.datasets[0].data.push(price);
  marketChart.data.datasets[1].data.push(throughput);

  // Keep last 30 data points
  if (marketChart.data.labels.length > 30) {
    marketChart.data.labels.shift();
    marketChart.data.datasets[0].data.shift();
    marketChart.data.datasets[1].data.shift();
  }

  marketChart.update();
}

async function submitOrder() {
  const priceInput = document.getElementById('order-price');
  const qtyInput = document.getElementById('order-quantity');
  const log = document.getElementById('order-status-log');
  const submitBtn = document.getElementById('btn-order-submit');

  const price = parseFloat(priceInput.value);
  const qty = parseInt(qtyInput.value, 10);

  if (isNaN(price) || price <= 0) {
    log.className = 'action-log error';
    log.innerText = 'Validation error: Limit price must be greater than $0.00.';
    return;
  }

  if (isNaN(qty) || qty <= 0) {
    log.className = 'action-log error';
    log.innerText = 'Validation error: Quantity must be a positive integer.';
    return;
  }

  submitBtn.disabled = true;
  log.className = 'action-log';
  log.innerText = `Submitting ${selectedSide} order for ${qty} @ $${price.toFixed(2)}...`;

  try {
    const res = await fetch('/api/orders/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        side: selectedSide,
        price: price,
        quantity: qty
      })
    });

    const result = await res.json();
    if (res.ok && result.success) {
      log.className = 'action-log success';
      log.innerText = `Order #${result.order_id} executed! Status: ${result.status} | Trades: ${result.trades_count} | Filled: ${result.filled_quantity}/${qty}`;
      fetchMarketData();
    } else {
      log.className = 'action-log error';
      log.innerText = `Order rejected: ${result.error || 'Unknown engine error'}`;
    }
  } catch (err) {
    log.className = 'action-log error';
    log.innerText = `Network submission failure: ${err.message}`;
  } finally {
    submitBtn.disabled = false;
  }
}

async function startSimulator() {
  const ordersInput = document.getElementById('sim-orders-input');
  const rateInput = document.getElementById('sim-rate-input');
  const log = document.getElementById('sim-status-log');

  const orders = parseInt(ordersInput.value, 10) || 5000;
  const rate = parseInt(rateInput.value, 10) || 25000;

  log.className = 'action-log';
  log.innerText = `Starting market simulator (${orders.toLocaleString()} orders @ ${rate.toLocaleString()} ops/s)...`;

  try {
    const res = await fetch('/api/simulator/start/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ orders: orders, rate: rate })
    });
    const result = await res.json();
    if (res.ok && result.success) {
      log.className = 'action-log success';
      log.innerText = `Simulator active! Blasting ${orders.toLocaleString()} orders through IPC ring buffer.`;
      fetchMarketData();
    } else {
      log.className = 'action-log error';
      log.innerText = `Failed to start simulator: ${result.error || 'Unknown error'}`;
    }
  } catch (err) {
    log.className = 'action-log error';
    log.innerText = `Simulator control error: ${err.message}`;
  }
}

async function stopSimulator() {
  const log = document.getElementById('sim-status-log');
  log.className = 'action-log';
  log.innerText = 'Sending stop signal to simulator...';

  try {
    const res = await fetch('/api/simulator/stop/', { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.success) {
      log.className = 'action-log';
      log.innerText = 'Simulator stopped successfully.';
      fetchMarketData();
    } else {
      log.className = 'action-log error';
      log.innerText = `Stop failed: ${result.error || 'Unknown error'}`;
    }
  } catch (err) {
    log.className = 'action-log error';
    log.innerText = `Simulator stop error: ${err.message}`;
  }
}

async function resetBook() {
  if (!confirm('Are you sure you want to reset the Limit Order Book and trade tape?')) {
    return;
  }
  const log = document.getElementById('sim-status-log');
  try {
    const res = await fetch('/api/simulator/reset/', { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.success) {
      log.className = 'action-log success';
      log.innerText = 'Order book and trade history reset to clean initial state.';
      fetchMarketData();
    } else {
      log.className = 'action-log error';
      log.innerText = `Reset failed: ${result.error || 'Unknown error'}`;
    }
  } catch (err) {
    log.className = 'action-log error';
    log.innerText = `Reset error: ${err.message}`;
  }
}
