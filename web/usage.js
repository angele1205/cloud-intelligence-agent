/**
 * Usage Tab - Real-time Bedrock token/cost monitoring (bedrock-lens style)
 * Queries CloudWatch Logs Insights for model invocation data
 */
import { fetchAuthSession } from 'aws-amplify/auth';
import { SignatureV4 } from '@smithy/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';

const REGION = window.COSTOP_CONFIG?.region || 'us-east-1';
const LOG_GROUP = '/aws/bedrock/modelinvocations';

// Per-1000-token pricing (input/output) for common models
const MODEL_PRICING = {
  'anthropic.claude-sonnet-4-5-20250929-v1:0': { input: 0.003, output: 0.015, name: 'Claude Sonnet 4.5' },
  'us.anthropic.claude-sonnet-4-5-20250929-v1:0': { input: 0.003, output: 0.015, name: 'Claude Sonnet 4.5' },
  'anthropic.claude-sonnet-4-6': { input: 0.003, output: 0.015, name: 'Claude Sonnet 4.6' },
  'us.anthropic.claude-sonnet-4-6': { input: 0.003, output: 0.015, name: 'Claude Sonnet 4.6' },
  'anthropic.claude-haiku-4-5-20251001-v1:0': { input: 0.0008, output: 0.004, name: 'Claude Haiku 4.5' },
  'us.anthropic.claude-haiku-4-5-20251001-v1:0': { input: 0.0008, output: 0.004, name: 'Claude Haiku 4.5' },
  'anthropic.claude-3-5-sonnet-20241022-v2:0': { input: 0.003, output: 0.015, name: 'Claude 3.5 Sonnet v2' },
  'us.anthropic.claude-3-5-sonnet-20241022-v2:0': { input: 0.003, output: 0.015, name: 'Claude 3.5 Sonnet v2' },
  'anthropic.claude-3-haiku-20240307-v1:0': { input: 0.00025, output: 0.00125, name: 'Claude 3 Haiku' },
  'amazon.nova-micro-v1:0': { input: 0.000035, output: 0.00014, name: 'Nova Micro' },
  'amazon.nova-lite-v1:0': { input: 0.00006, output: 0.00024, name: 'Nova Lite' },
  'amazon.nova-pro-v1:0': { input: 0.0008, output: 0.0032, name: 'Nova Pro' },
};

let usageRefreshTimer = null;

function getTimeRange() {
  const range = document.getElementById('usageRange')?.value || 'today';
  const now = new Date();
  let start;

  switch (range) {
    case '30m': start = new Date(now.getTime() - 30 * 60 * 1000); break;
    case '1h': start = new Date(now.getTime() - 60 * 60 * 1000); break;
    case '6h': start = new Date(now.getTime() - 6 * 60 * 60 * 1000); break;
    case 'today': start = new Date(now.getFullYear(), now.getMonth(), now.getDate()); break;
    case 'yesterday':
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
      now.setHours(0, 0, 0, 0); // end at midnight today
      break;
    case 'week': start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000); break;
    default: start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }

  return {
    startTime: Math.floor(start.getTime() / 1000),
    endTime: Math.floor(now.getTime() / 1000)
  };
}

function getModelDisplayName(modelId) {
  if (!modelId) return 'Unknown';
  const pricing = MODEL_PRICING[modelId];
  if (pricing) return pricing.name;
  // Extract readable name from model ID
  const parts = modelId.replace('us.', '').split('.');
  if (parts.length >= 2) {
    const provider = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    const model = parts[1].replace(/-v\d.*/, '').replace(/-\d{8}.*/, '');
    return `${provider} ${model}`;
  }
  return modelId.substring(0, 40);
}

function getModelPricing(modelId) {
  if (!modelId) return { input: 0.003, output: 0.015 };
  // Direct match
  if (MODEL_PRICING[modelId]) return MODEL_PRICING[modelId];
  // Try without us. prefix
  const stripped = modelId.replace('us.', '');
  if (MODEL_PRICING[stripped]) return MODEL_PRICING[stripped];
  // Fuzzy match
  for (const [key, val] of Object.entries(MODEL_PRICING)) {
    if (modelId.includes(key.split('.')[1]?.split('-')[0] || '___')) return val;
  }
  // Default to Sonnet pricing
  return { input: 0.003, output: 0.015 };
}

function formatNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toLocaleString();
}

async function queryCloudWatchLogs(session, startTime, endTime) {
  const signer = new SignatureV4({
    service: 'logs',
    region: REGION,
    credentials: session.credentials,
    sha256: Sha256
  });

  const query = `fields @timestamp, modelId, input.inputTokenCount as inputTokens, output.outputTokenCount as outputTokens
| filter modelId != ""
| stats count(*) as invocations, sum(inputTokens) as totalInput, sum(outputTokens) as totalOutput by modelId
| sort totalInput desc`;

  // Start query
  const startBody = JSON.stringify({
    logGroupName: LOG_GROUP,
    startTime,
    endTime,
    queryString: query,
    limit: 1000
  });

  const startSigned = await signer.sign({
    method: 'POST',
    hostname: `logs.${REGION}.amazonaws.com`,
    path: '/',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'Logs_20140328.StartQuery',
      host: `logs.${REGION}.amazonaws.com`
    },
    body: startBody
  });

  const startRes = await fetch(`https://logs.${REGION}.amazonaws.com/`, {
    method: 'POST',
    headers: { ...startSigned.headers, 'X-Amz-Target': 'Logs_20140328.StartQuery', 'Content-Type': 'application/x-amz-json-1.1' },
    body: startBody
  });

  const startData = await startRes.json();
  if (!startData.queryId) throw new Error(startData.message || 'Failed to start query');

  // Poll for results
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));

    const getBody = JSON.stringify({ queryId: startData.queryId });
    const getSigned = await signer.sign({
      method: 'POST',
      hostname: `logs.${REGION}.amazonaws.com`,
      path: '/',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'Logs_20140328.GetQueryResults',
        host: `logs.${REGION}.amazonaws.com`
      },
      body: getBody
    });

    const getRes = await fetch(`https://logs.${REGION}.amazonaws.com/`, {
      method: 'POST',
      headers: { ...getSigned.headers, 'X-Amz-Target': 'Logs_20140328.GetQueryResults', 'Content-Type': 'application/x-amz-json-1.1' },
      body: getBody
    });

    const getData = await getRes.json();
    if (getData.status === 'Complete') {
      return getData.results || [];
    }
    if (getData.status === 'Failed' || getData.status === 'Cancelled') {
      throw new Error(`Query ${getData.status}`);
    }
  }
  throw new Error('Query timed out');
}

window.loadUsageData = async function () {
  const body = document.getElementById('usageBody');
  const summary = document.getElementById('usageSummary');
  const footer = document.getElementById('usageFooter');

  body.innerHTML = '<tr><td colspan="6" class="usage-loading">Loading invocation data...</td></tr>';
  summary.innerHTML = '';

  try {
    const session = await fetchAuthSession();
    const { startTime, endTime } = getTimeRange();
    const results = await queryCloudWatchLogs(session, startTime, endTime);

    if (!results || results.length === 0) {
      body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-faint);padding:40px">No invocations found in this time range</td></tr>';
      summary.innerHTML = '<div class="usage-stat"><div class="stat-label">Total Cost</div><div class="stat-value">$0.00</div></div>';
      footer.textContent = `Last updated: ${new Date().toLocaleTimeString()} • Log group: ${LOG_GROUP}`;
      return;
    }

    // Parse results
    const models = [];
    let totalInvocations = 0, totalInput = 0, totalOutput = 0, totalCost = 0;

    for (const row of results) {
      const fields = {};
      for (const field of row) {
        fields[field.field] = field.value;
      }
      const modelId = fields.modelId || 'unknown';
      const invocations = parseInt(fields.invocations || '0');
      const inputTokens = parseInt(fields.totalInput || '0');
      const outputTokens = parseInt(fields.totalOutput || '0');
      const pricing = getModelPricing(modelId);
      const cost = (inputTokens * pricing.input + outputTokens * pricing.output) / 1000;

      models.push({ modelId, invocations, inputTokens, outputTokens, cost });
      totalInvocations += invocations;
      totalInput += inputTokens;
      totalOutput += outputTokens;
      totalCost += cost;
    }

    // Sort by cost descending
    models.sort((a, b) => b.cost - a.cost);

    // Render summary
    const costClass = totalCost > 10 ? 'danger' : totalCost > 5 ? 'warning' : '';
    summary.innerHTML = `
      <div class="usage-stat"><div class="stat-label">Total Cost</div><div class="stat-value ${costClass}">$${totalCost.toFixed(2)}</div></div>
      <div class="usage-stat"><div class="stat-label">Invocations</div><div class="stat-value">${formatNumber(totalInvocations)}</div></div>
      <div class="usage-stat"><div class="stat-label">Input Tokens</div><div class="stat-value">${formatNumber(totalInput)}</div></div>
      <div class="usage-stat"><div class="stat-label">Output Tokens</div><div class="stat-value">${formatNumber(totalOutput)}</div></div>
      <div class="usage-stat"><div class="stat-label">Models Active</div><div class="stat-value">${models.length}</div></div>
    `;

    // Render table
    let tableHtml = '';
    for (const m of models) {
      const displayName = getModelDisplayName(m.modelId);
      const totalTokens = m.inputTokens + m.outputTokens;
      tableHtml += `<tr>
        <td class="model-name" title="${m.modelId}">${displayName}</td>
        <td>${m.invocations.toLocaleString()}</td>
        <td>${formatNumber(m.inputTokens)}</td>
        <td>${formatNumber(m.outputTokens)}</td>
        <td>${formatNumber(totalTokens)}</td>
        <td class="cost-cell">$${m.cost.toFixed(4)}</td>
      </tr>`;
    }
    // Totals row
    tableHtml += `<tr style="font-weight:700;border-top:2px solid var(--border)">
      <td class="model-name">TOTAL</td>
      <td>${totalInvocations.toLocaleString()}</td>
      <td>${formatNumber(totalInput)}</td>
      <td>${formatNumber(totalOutput)}</td>
      <td>${formatNumber(totalInput + totalOutput)}</td>
      <td class="cost-cell">$${totalCost.toFixed(4)}</td>
    </tr>`;

    body.innerHTML = tableHtml;
    footer.textContent = `Last updated: ${new Date().toLocaleTimeString()} • Log group: ${LOG_GROUP} • Pricing: on-demand rates`;

  } catch (e) {
    if (e.message.includes('ResourceNotFoundException') || e.message.includes('log group')) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-muted)">
        <strong>Invocation logging not enabled</strong><br><br>
        Run in your terminal:<br><code style="background:var(--date-header-bg);padding:4px 8px;border-radius:4px;font-size:12px">pip install bedrock-lens && bedrock-lens --setup</code><br><br>
        Or ask the agent: "Enable Bedrock invocation logging"
      </td></tr>`;
    } else {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:#EF4444">${e.message}</td></tr>`;
    }
    footer.textContent = `Error at ${new Date().toLocaleTimeString()}`;
  }
};

window.toggleUsageAutoRefresh = function () {
  const checked = document.getElementById('usageAutoRefresh')?.checked;
  if (checked) {
    loadUsageData();
    usageRefreshTimer = setInterval(loadUsageData, 30000);
  } else {
    if (usageRefreshTimer) clearInterval(usageRefreshTimer);
    usageRefreshTimer = null;
  }
};

// Tab switching
window.switchTab = function (tab) {
  const chatContainer = document.querySelector('.container');
  const usagePanel = document.getElementById('usagePanel');
  const tabs = document.querySelectorAll('.tab-btn');

  tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab));

  if (tab === 'usage') {
    chatContainer.style.display = 'none';
    usagePanel.style.display = 'flex';
    loadUsageData();
  } else {
    chatContainer.style.display = 'flex';
    usagePanel.style.display = 'none';
    if (usageRefreshTimer) {
      clearInterval(usageRefreshTimer);
      usageRefreshTimer = null;
      const cb = document.getElementById('usageAutoRefresh');
      if (cb) cb.checked = false;
    }
  }
};
