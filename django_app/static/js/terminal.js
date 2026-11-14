/**
 * ============================================================================
 * ChronosMatch Institutional Dark Trading Terminal — JavaScript
 * Real-Time Telemetry Streaming, L2 Order Book, Execution & Simulator Controls
 * ============================================================================
 */

// Centralized Frontend API Configuration
const API_ENDPOINTS = {
  HEALTH: '/api/health/',
  MARKET: '/api/market/',
  ORDERBOOK: '/api/orderbook/',
  TRADES: '/api/trades/',
  METRICS: '/api/metrics/',
  SWEEPS: '/api/sweeps/',
  MARKET_DATA: '/api/market-data/',
  SUBMIT_ORDER: '/api/orders/',
  SIMULATOR_START: '/api/simulator/start/',
  SIMULATOR_STOP: '/api/simulator/stop/',
  SIMULATOR_RESET: '/api/simulator/reset/',
};

let selectedSide = 'BUY';
let orderType = 'LIMIT';
let pollInterval = null;
let marketChart = null;
let chartMode = 'price'; // 'price' or 'latency'
let lastPrice = null;
let lastBestBid = null;
let lastBestAsk = null;
let lastSweepsCount = 0;

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  initFormListeners();
  initKeyboardShortcuts();
  startPolling();
});

// ============================================================================
// Chart Initialization & Telemetry
// ============================================================================
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
          backgroundColor: 'rgba(56, 189, 248, 0.08)',
          borderWidth: 2,
          pointRadius: 1.5,
          tension: 0.15,
          yAxisID: 'yPrimary',
          fill: true,
        },
        {
          label: 'Throughput (ops/sec)',
          data: [],
          borderColor: '#10b981',
          borderWidth: 1.5,
          pointRadius: 0,
          borderDash: [3, 3],
          tension: 0.2,
          yAxisID: 'ySecondary',
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
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: { color: '#64748b', font: { family: 'monospace', size: 10 }, maxTicksLimit: 8 }
        },
        yPrimary: {
          type: 'linear',
          display: true,
          position: 'left',
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: { color: '#38bdf8', font: { family: 'monospace', size: 10 } }
        },
        ySecondary: {
          type: 'linear',
          display: true,
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#10b981', font: { family: 'monospace', size: 10 } }
        }
      },
      plugins: {
        legend: {
          position: 'top',
          align: 'end',
          labels: { color: '#94a3b8', boxWidth: 12, font: { size: 10, family: 'monospace' } }
        },
        tooltip: {
          backgroundColor: 'rgba(18, 24, 36, 0.95)',
          borderColor: '#2c3e5a',
          borderWidth: 1,
          titleFont: { family: 'monospace', size: 11 },
          bodyFont: { family: 'monospace', size: 11 },
        }
      }
    }
  });
}

function switchChartMode(mode) {
  chartMode = mode;
  const btnPrice = document.getElementById('tab-chart-price');
  const btnLat = document.getElementById('tab-chart-latency');

  if (mode === 'price') {
    btnPrice.classList.add('active');
    btnLat.classList.remove('active');
    if (marketChart) {
      marketChart.data.datasets[0].label = 'Market Price ($)';
      marketChart.data.datasets[0].borderColor = '#38bdf8';
      marketChart.data.datasets[0].backgroundColor = 'rgba(56, 189, 248, 0.08)';
      marketChart.data.datasets[1].label = 'Throughput (ops/sec)';
      marketChart.data.datasets[1].borderColor = '#10b981';
      marketChart.options.scales.yPrimary.ticks.color = '#38bdf8';
      marketChart.options.scales.ySecondary.ticks.color = '#10b981';
      marketChart.update();
    }
  } else {
    btnLat.classList.add('active');
    btnPrice.classList.remove('active');
    if (marketChart) {
      marketChart.data.datasets[0].label = 'Engine Match Latency (µs)';
      marketChart.data.datasets[0].borderColor = '#f59e0b';
      marketChart.data.datasets[0].backgroundColor = 'rgba(245, 158, 11, 0.08)';
      marketChart.data.datasets[1].label = 'Pipeline E2E Latency (µs)';
      marketChart.data.datasets[1].borderColor = '#a855f7';
      marketChart.options.scales.yPrimary.ticks.color = '#f59e0b';
      marketChart.options.scales.ySecondary.ticks.color = '#a855f7';
      marketChart.update();
    }
  }
}

function updateChartStream(price, throughput, engineLat, e2eLat) {
  if (!marketChart) return;

  const now = new Date();
  const timeLabel = now.toTimeString().split(' ')[0];

  marketChart.data.labels.push(timeLabel);

  if (chartMode === 'price') {
    marketChart.data.datasets[0].data.push(price);
    marketChart.data.datasets[1].data.push(throughput);
  } else {
    marketChart.data.datasets[0].data.push(engineLat);
    marketChart.data.datasets[1].data.push(e2eLat);
  }

  // Keep last 40 data points
  if (marketChart.data.labels.length > 40) {
    marketChart.data.labels.shift();
    marketChart.data.datasets[0].data.shift();
    marketChart.data.datasets[1].data.shift();
  }

  marketChart.update();
}

// ============================================================================
// Order Entry & Side Selection
// ============================================================================
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
    submitBtn.className = 'btn-execute-order buy';
    submitBtn.innerHTML = '<span>SUBMIT BUY ORDER</span>';
  } else {
    sellBtn.classList.add('selected');
    buyBtn.classList.remove('selected');
    submitBtn.className = 'btn-execute-order sell';
    submitBtn.innerHTML = '<span>SUBMIT SELL ORDER</span>';
  }

  if (orderType === 'MARKET') {
    autofillMarketPrice();
  }
}

function setOrderType(type) {
  orderType = type;
  const btnLimit = document.getElementById('tab-order-limit');
  const btnMarket = document.getElementById('tab-order-market');
  const priceGroup = document.getElementById('group-order-price');
  const priceInput = document.getElementById('order-price');
  const typeHint = document.getElementById('order-type-hint');

  if (type === 'LIMIT') {
    btnLimit.classList.add('active');
    btnMarket.classList.remove('active');
    typeHint.innerText = 'LIMIT';
    priceInput.removeAttribute('readonly');
  } else {
    btnMarket.classList.add('active');
    btnLimit.classList.remove('active');
    typeHint.innerText = 'MARKET';
    autofillMarketPrice();
  }
}

function autofillMarketPrice() {
  const priceInput = document.getElementById('order-price');
  if (selectedSide === 'BUY' && lastBestAsk) {
    priceInput.value = lastBestAsk[0].toFixed(2);
  } else if (selectedSide === 'SELL' && lastBestBid) {
    priceInput.value = lastBestBid[0].toFixed(2);
  } else if (lastPrice) {
    priceInput.value = lastPrice.toFixed(2);
  } else {
    priceInput.value = '100.00';
  }
  priceInput.dispatchEvent(new Event('input'));
}

function setQuickQty(qty) {
  const qtyInput = document.getElementById('order-quantity');
  const current = parseInt(qtyInput.value, 10) || 0;
  qtyInput.value = current + qty;
  qtyInput.dispatchEvent(new Event('input'));
}

function setSimRate(rate) {
  const rateInput = document.getElementById('sim-rate-input');
  rateInput.value = rate;
}

// Click-to-trade on any row in the Order Book
function clickPriceRow(price, defaultSide) {
  const priceInput = document.getElementById('order-price');
  priceInput.value = Number(price).toFixed(2);
  priceInput.dispatchEvent(new Event('input'));
  if (defaultSide) {
    selectSide(defaultSide);
  }
  showToast(`Auto-filled price $${Number(price).toFixed(2)} into Order Entry`, 'info');
}

// ============================================================================
// Order Submission
// ============================================================================
async function submitOrder() {
  const priceInput = document.getElementById('order-price');
  const qtyInput = document.getElementById('order-quantity');
  const submitBtn = document.getElementById('btn-order-submit');

  const price = parseFloat(priceInput.value);
  const qty = parseInt(qtyInput.value, 10);

  if (isNaN(price) || price <= 0) {
    showToast('Validation Error: Limit price must be greater than $0.00', 'error');
    priceInput.focus();
    return;
  }

  if (isNaN(qty) || qty <= 0) {
    showToast('Validation Error: Quantity must be a positive integer', 'error');
    qtyInput.focus();
    return;
  }

  submitBtn.disabled = true;
  const originalHtml = submitBtn.innerHTML;
  submitBtn.innerHTML = '<span>Matching in Cython Engine...</span>';

  try {
    const res = await fetch(API_ENDPOINTS.SUBMIT_ORDER, {
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
      if (result.status === 'FILLED') {
        showToast(`Order #${result.order_id} FILLED! Matched ${result.filled_quantity} shares @ $${result.price.toFixed(2)}`, 'success');
      } else if (result.status === 'PARTIALLY_FILLED') {
        showToast(`Order #${result.order_id} PARTIALLY FILLED: ${result.filled_quantity}/${qty} shares. Remainder resting in book`, 'warn');
      } else {
        showToast(`Order #${result.order_id} placed as RESTING ${selectedSide} limit on book`, 'info');
      }
      fetchMarketData();
    } else {
      showToast(`Order Rejected: ${result.error || 'Matching Engine error'}`, 'error');
    }
  } catch (err) {
    showToast(`Network submission failure: ${err.message}`, 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = originalHtml;
  }
}

// ============================================================================
// Market Simulator Controls
// ============================================================================
async function startSimulator() {
  const ordersInput = document.getElementById('sim-orders-input');
  const rateInput = document.getElementById('sim-rate-input');

  const orders = parseInt(ordersInput.value, 10) || 5000;
  const rate = parseInt(rateInput.value, 10) || 25000;

  showToast(`Starting simulator: ${orders.toLocaleString()} orders @ ${rate.toLocaleString()} ops/s...`, 'info');

  try {
    const res = await fetch(API_ENDPOINTS.SIMULATOR_START, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ orders: orders, rate: rate })
    });
    const result = await res.json();
    if (res.ok && result.success) {
      showToast(`Firehose active! Streaming ${orders.toLocaleString()} orders through IPC RingBuffer`, 'success');
      fetchMarketData();
    } else {
      showToast(`Failed: ${result.error || result.message || 'Error starting simulator'}`, 'error');
    }
  } catch (err) {
    showToast(`Simulator network error: ${err.message}`, 'error');
  }
}

async function stopSimulator() {
  try {
    const res = await fetch(API_ENDPOINTS.SIMULATOR_STOP, { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.success) {
      showToast('Simulator stopped successfully', 'info');
      fetchMarketData();
    } else {
      showToast(`Stop failed: ${result.message || 'Unknown error'}`, 'error');
    }
  } catch (err) {
    showToast(`Stop error: ${err.message}`, 'error');
  }
}

async function resetBook() {
  if (!confirm('Reset the Limit Order Book and trade execution tape to clean initial state?')) {
    return;
  }
  try {
    const res = await fetch(API_ENDPOINTS.SIMULATOR_RESET, { method: 'POST' });
    const result = await res.json();
    if (res.ok && result.success) {
      showToast('Order Book and Trade tape reset to clean state', 'success');
      fetchMarketData();
    } else {
      showToast(`Reset failed: ${result.message || 'Unknown error'}`, 'error');
    }
  } catch (err) {
    showToast(`Reset error: ${err.message}`, 'error');
  }
}

// ============================================================================
// Real-Time Polling & UI Render Loop
// ============================================================================
function startPolling() {
  fetchMarketData();
  pollInterval = setInterval(fetchMarketData, 500);
}

async function fetchMarketData() {
  const t0 = performance.now();
  try {
    const response = await fetch(API_ENDPOINTS.MARKET_DATA);
    const pingMs = Math.round(performance.now() - t0);

    if (!response.ok) {
      throw new Error(`HTTP error ${response.status}`);
    }
    const data = await response.json();
    updateUI(data);

    // Update connection status
    const connBadge = document.getElementById('connection-status');
    if (connBadge) {
      connBadge.innerText = `FEED CONNECTED (${pingMs}ms &bull; 500ms)`;
      connBadge.style.color = 'var(--bid-green-light)';
      connBadge.style.borderColor = 'var(--bid-green-border)';
    }

    const pingDetail = document.getElementById('health-detail-ping');
    if (pingDetail) {
      pingDetail.innerText = `Polling ping: ${pingMs}ms &bull; Zero drop`;
    }
  } catch (err) {
    const connBadge = document.getElementById('connection-status');
    if (connBadge) {
      connBadge.innerText = 'FEED DISCONNECTED — Retrying...';
      connBadge.style.color = 'var(--ask-red-light)';
      connBadge.style.borderColor = 'var(--ask-red-border)';
    }
  }
}

function updateUI(data) {
  // Engine & Simulator states
  const engStatus = data.engine_status || 'ONLINE';
  const simRunning = data.simulator_running;
  
  document.getElementById('engine-status-text').innerText = engStatus;
  document.getElementById('sim-status-text').innerText = simRunning ? 'RUNNING' : 'IDLE';

  const simDot = document.getElementById('sim-dot');
  const simBadge = document.getElementById('sim-badge-status');
  if (simRunning) {
    simDot.className = 'pulse-dot active';
    if (simBadge) { simBadge.innerText = 'Active Firehose'; simBadge.style.color = 'var(--bid-green-light)'; }
  } else {
    simDot.className = 'pulse-dot';
    if (simBadge) { simBadge.innerText = 'Idle'; simBadge.style.color = 'var(--text-muted)'; }
  }

  // Ticker updates
  lastBestBid = data.best_bid;
  lastBestAsk = data.best_ask;
  const spread = data.spread;
  lastPrice = data.last_price;

  document.getElementById('ticker-market-price').innerText = lastPrice !== null ? `$${lastPrice.toFixed(2)}` : '--.--';
  document.getElementById('ticker-best-bid').innerText = lastBestBid ? `$${lastBestBid[0].toFixed(2)} (${lastBestBid[1].toLocaleString()})` : '--.--';
  document.getElementById('ticker-best-ask').innerText = lastBestAsk ? `$${lastBestAsk[0].toFixed(2)} (${lastBestAsk[1].toLocaleString()})` : '--.--';
  
  if (spread !== null) {
    document.getElementById('ticker-spread').innerText = `$${spread.toFixed(2)}`;
    document.getElementById('book-spread-text').innerText = `$${spread.toFixed(2)}`;
  } else {
    document.getElementById('ticker-spread').innerText = '--.--';
    document.getElementById('book-spread-text').innerText = 'N/A';
  }

  // Price Delta Badge
  const deltaBadge = document.getElementById('ticker-price-delta');
  if (data.price_change !== undefined && data.price_change_pct !== undefined) {
    const sign = data.price_change >= 0 ? '+' : '';
    deltaBadge.innerText = `${sign}$${data.price_change.toFixed(2)} (${sign}${data.price_change_pct.toFixed(2)}%)`;
    deltaBadge.className = data.price_change >= 0 ? 'price-delta-badge up' : 'price-delta-badge down';
  }

  // Session High / Low
  const highLowElem = document.getElementById('ticker-high-low');
  if (highLowElem) {
    const h = data.session_high !== null && data.session_high !== undefined ? `$${data.session_high.toFixed(2)}` : '--';
    const l = data.session_low !== null && data.session_low !== undefined ? `$${data.session_low.toFixed(2)}` : '--';
    highLowElem.innerText = `${h} / ${l}`;
  }

  // Mid & Last Price
  const midPrice = (lastBestBid && lastBestAsk) ? ((lastBestBid[0] + lastBestAsk[0]) / 2.0).toFixed(2) : '--';
  document.getElementById('book-mid-text').innerText = midPrice !== '--' ? `$${midPrice}` : '--';
  document.getElementById('book-last-text').innerText = lastPrice !== null ? `$${lastPrice.toFixed(2)}` : '--';

  const metrics = data.metrics || {};
  document.getElementById('ticker-throughput').innerText = `${(metrics.throughput_ops || 0).toLocaleString('en-US', {maximumFractionDigits: 1})} ops/s`;
  document.getElementById('ticker-orders-count').innerText = (metrics.orders_processed || 0).toLocaleString('en-US');
  document.getElementById('ticker-trades-count').innerText = (metrics.trades_executed || 0).toLocaleString('en-US');

  // Render Level 2 Order Book Depth
  renderOrderBook(data.depth || { bids: [], asks: [] });

  // Render Recent Trade Tape
  renderTradesTape(data.recent_trades || []);

  // Latency Metrics (Microseconds)
  const lat = metrics.latency || {};
  const mMean = lat.match_mean_us !== undefined ? lat.match_mean_us : 0.0;
  const mP95 = lat.match_p95_us !== undefined ? lat.match_p95_us : 0.0;
  const mP99 = lat.match_p99_us !== undefined ? lat.match_p99_us : 0.0;

  const eMean = lat.e2e_mean_us !== undefined ? lat.e2e_mean_us : 0.0;
  const eP95 = lat.e2e_p95_us !== undefined ? lat.e2e_p95_us : 0.0;
  const eP99 = lat.e2e_p99_us !== undefined ? lat.e2e_p99_us : 0.0;

  document.getElementById('lat-engine-mean').innerText = mMean > 0 ? `${mMean.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-engine-p95').innerText = mP95 > 0 ? `${mP95.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-engine-p99').innerText = mP99 > 0 ? `${mP99.toFixed(2)} µs` : '-- µs';

  document.getElementById('lat-e2e-mean').innerText = eMean > 0 ? `${eMean.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-e2e-p95').innerText = eP95 > 0 ? `${eP95.toFixed(2)} µs` : '-- µs';
  document.getElementById('lat-e2e-p99').innerText = eP99 > 0 ? `${eP99.toFixed(2)} µs` : '-- µs';

  // System Health Badges
  if (data.system_health) {
    const sh = data.system_health;
    const simBadge = document.getElementById('health-badge-sim');
    if (simBadge) {
      simBadge.innerText = sh.market_simulator.status;
      simBadge.className = sh.market_simulator.status === 'RUNNING' ? 'health-status-badge ok' : 'health-status-badge idle';
    }
    const lobDetail = document.getElementById('health-detail-lob');
    if (lobDetail && sh.order_book) {
      lobDetail.innerText = `Price-Time FIFO &bull; ${sh.order_book.levels || 0} active levels`;
    }
  }

  // Whale Sweeps Alert Update
  const totalSweeps = metrics.total_sweeps_detected || 0;
  const sweepBadge = document.getElementById('sweep-total-badge');
  if (sweepBadge) {
    sweepBadge.innerText = `${totalSweeps.toLocaleString()} Sweeps Detected`;
  }
  const sweepBox = document.getElementById('whale-sweep-alert-box');
  if (sweepBox && metrics.last_sweep) {
    const sw = metrics.last_sweep;
    sweepBox.style.background = 'rgba(245, 158, 11, 0.08)';
    sweepBox.style.borderColor = 'rgba(245, 158, 11, 0.3)';
    sweepBox.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
        <span style="font-weight: 700; color: #f59e0b;">ALERT: WHALE SWEEP #${sw.order_id} (${sw.side})</span>
        <span style="color: var(--text-dim); font-size: 10px;">${new Date().toLocaleTimeString()}</span>
      </div>
      <div style="color: #fff;">
        Incoming aggressive <strong>${sw.side}</strong> swept <strong style="color: #38bdf8;">${sw.levels_swept} price levels</strong> (${sw.total_quantity.toLocaleString()} shares) from <strong>$${sw.start_price.toFixed(2)}</strong> to <strong>$${sw.end_price.toFixed(2)}</strong> across ${sw.trades_count} executions.
      </div>
    `;
    if (totalSweeps > lastSweepsCount && lastSweepsCount > 0) {
      showToast(`Whale Sweep Alert: Order #${sw.order_id} swept ${sw.levels_swept} levels!`, 'warn');
    }
  }
  lastSweepsCount = totalSweeps;

  // Footer Uptime
  const uptimeElem = document.getElementById('footer-uptime');
  if (uptimeElem && data.uptime_sec !== undefined) {
    uptimeElem.innerText = `Uptime: ${data.uptime_sec}s`;
  }

  // Telemetry Chart Stream
  updateChartStream(
    lastPrice || (lastBestBid ? lastBestBid[0] : 100.0),
    metrics.throughput_ops || 0.0,
    mMean,
    eMean
  );
}

// ============================================================================
// Order Book Side-by-Side Institutional Depth Renderer
// ============================================================================
function renderOrderBook(depth) {
  const bidsTbody = document.getElementById('order-book-bids');
  const asksTbody = document.getElementById('order-book-asks');

  // Compute max cumulative size for depth visualizer bars
  let maxQty = 1;
  let cumBids = 0;
  let cumAsks = 0;

  depth.bids.forEach(b => { cumBids += b.total_quantity; });
  depth.asks.forEach(a => { cumAsks += a.total_quantity; });
  maxQty = Math.max(cumBids, cumAsks, 1);

  // Render BUY Bids (Highest price first)
  if (!depth.bids || depth.bids.length === 0) {
    bidsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-dim); padding: 30px;">Awaiting Bids...</td></tr>';
  } else {
    let bidHtml = '';
    let rollingQty = 0;
    depth.bids.forEach(b => {
      rollingQty += b.total_quantity;
      const pct = Math.min(100, Math.round((rollingQty / maxQty) * 100));
      bidHtml += `
        <tr class="book-row bid" onclick="clickPriceRow(${b.price}, 'SELL')" title="Click to fill SELL limit at $${b.price.toFixed(2)}">
          <td>$${b.price.toFixed(2)}</td>
          <td>${b.total_quantity.toLocaleString()}</td>
          <td>${rollingQty.toLocaleString()}</td>
          <div class="depth-bar bid" style="width: ${pct}%;"></div>
        </tr>
      `;
    });
    bidsTbody.innerHTML = bidHtml;
  }

  // Render SELL Asks (Lowest price first)
  if (!depth.asks || depth.asks.length === 0) {
    asksTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-dim); padding: 30px;">Awaiting Asks...</td></tr>';
  } else {
    let askHtml = '';
    let rollingQty = 0;
    depth.asks.forEach(a => {
      rollingQty += a.total_quantity;
      const pct = Math.min(100, Math.round((rollingQty / maxQty) * 100));
      askHtml += `
        <tr class="book-row ask" onclick="clickPriceRow(${a.price}, 'BUY')" title="Click to fill BUY limit at $${a.price.toFixed(2)}">
          <td>$${a.price.toFixed(2)}</td>
          <td>${a.total_quantity.toLocaleString()}</td>
          <td>${rollingQty.toLocaleString()}</td>
          <div class="depth-bar ask" style="width: ${pct}%;"></div>
        </tr>
      `;
    });
    asksTbody.innerHTML = askHtml;
  }
}

// ============================================================================
// Executed Trade Tape Renderer
// ============================================================================
function renderTradesTape(trades) {
  const container = document.getElementById('trades-tape');
  if (!trades || trades.length === 0) {
    container.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 35px;">Awaiting trade executions...</div>';
    return;
  }

  let html = '';
  // Most recent executions first
  const reversed = [...trades].reverse();
  reversed.forEach(t => {
    const d = new Date(t.timestamp_ns / 1000000);
    const timeStr = d.toTimeString().split(' ')[0] + '.' + String(d.getMilliseconds()).padStart(3, '0');
    const totalVal = (t.price * t.quantity).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    
    html += `
      <div class="trade-row-item">
        <span style="color: var(--text-muted); font-size: 10px;">${timeStr}</span>
        <span><span class="badge-trade-side buy">FILL</span></span>
        <span style="font-weight: 700; color: #fff; text-align: right;">$${t.price.toFixed(2)}</span>
        <span style="text-align: right;">${t.quantity.toLocaleString()}</span>
        <span style="text-align: right; color: var(--accent-cyan);">$${totalVal}</span>
        <span style="text-align: center; color: var(--text-dim); font-size: 10px;">B:#${t.buy_order_id} / S:#${t.sell_order_id}</span>
        <span style="text-align: center;"><span class="badge-trade-side buy" style="background: rgba(16, 185, 129, 0.1);">MATCHED</span></span>
      </div>
    `;
  });
  container.innerHTML = html;
}

// ============================================================================
// Toast Notifications
// ============================================================================
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 200);
  }, 4000);
}

// ============================================================================
// Modal & Demo Guide Walkthrough
// ============================================================================
function openDemoModal() {
  const modal = document.getElementById('demo-modal');
  if (modal) modal.classList.add('open');
}

function closeDemoModal() {
  const modal = document.getElementById('demo-modal');
  if (modal) modal.classList.remove('open');
}

function closeDemoModalOnBackdrop(e) {
  if (e.target && e.target.id === 'demo-modal') {
    closeDemoModal();
  }
}

function scrollToSection(id) {
  const elem = document.getElementById(id);
  if (elem) {
    elem.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ============================================================================
// Keyboard Navigation Shortcuts
// ============================================================================
function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // If typing in an input, do not trigger single key shortcuts
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
      return;
    }

    if (e.key === 'b' || e.key === 'B') {
      selectSide('BUY');
      showToast('Switched side to BUY (Bid)', 'info');
    } else if (e.key === 's' || e.key === 'S') {
      selectSide('SELL');
      showToast('Switched side to SELL (Ask)', 'info');
    } else if (e.key === 'Escape') {
      closeDemoModal();
    }
  });
}
