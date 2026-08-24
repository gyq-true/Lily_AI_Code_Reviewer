'use strict';

const $ = (sel) => document.querySelector(sel);

let toastTimer = null;
function toast(message, type = 'info') {
  const el = $('#toast');
  el.textContent = message;
  el.className = 'toast show ' + (type === 'info' ? '' : type);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3600);
}

async function api(path, options = {}) {
  const resp = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || data.error || `请求失败 [${resp.status}]`);
  return data;
}

async function refreshStatus() {
  const chip = $('#statusChip'), text = $('#statusText');
  try {
    const d = await api('/api/health');
    chip.className = 'status-chip ' + (d.configured ? 'ok' : 'fail');
    text.textContent = d.configured ? `${d.provider} 已配置` : `${d.provider} 未配置 Key`;
  } catch {
    chip.className = 'status-chip fail';
    text.textContent = '服务异常';
  }
}

const FIELD_DEFS = [
  { key: 'api_key', label: 'API Key', type: 'password', ph: 'sk-...', envHint: true },
  { key: 'base_url', label: 'API 地址', type: 'text', ph: '' },
  { key: 'model', label: '模型', type: 'text', ph: '' },
];

function renderProviderSections(data) {
  const wrap = $('#providerSections');
  const current = data.provider;
  wrap.innerHTML = Object.entries(data.providers).map(([name, p]) => `
    <div class="provider-section ${name === current ? 'active' : ''}" data-provider="${name}">
      <h3>
        ${p.label}
        <span class="tag">${name}</span>
        ${p.needs_key
          ? `<span class="key-state ${p.has_api_key ? 'ok' : 'no'}">${p.has_api_key ? 'Key 已配置 (' + p.api_key_masked + ')' : '未配置 Key'}</span>`
          : '<span class="key-state ok">无需 Key</span>'}
      </h3>
      ${FIELD_DEFS.filter((f) => f.key !== 'api_key' || p.needs_key).map((f) => `
        <div class="settings-row">
          <label>${f.label}${f.envHint ? ' <small style="color:var(--text-dim)">(也可用 .env / 环境变量配置)</small>' : ''}</label>
          <input type="${f.type}" data-provider="${name}" data-field="${f.key}"
                 placeholder="${f.ph || (p[f.key] || '')}" autocomplete="off">
        </div>`).join('')}
    </div>`).join('');

  const sel = $('#provider');
  if (!sel.options.length) {
    Object.entries(data.providers).forEach(([name, p]) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = `${p.label}`;
      sel.appendChild(opt);
    });
    sel.addEventListener('change', () => highlightActive(sel.value));
  }
  sel.value = current;
}

function highlightActive(name) {
  $$('.provider-section').forEach((el) =>
    el.classList.toggle('active', el.dataset.provider === name));
}

async function loadSettings() {
  try {
    const data = await api('/api/settings');
    renderProviderSections(data);
    $('#temperature').value = data.temperature;
    $('#tempVal').textContent = data.temperature;
    $('#max_tokens').value = data.max_tokens;
    $('#timeout_ms').value = data.timeout_ms;
    const kb = data.kb || {};
    $('#kb_enabled').checked = !!kb.enabled;
    $('#kb_qdrant_url').value = kb.qdrant_url || '';
    $('#kb_qdrant_api_key').placeholder = kb.has_qdrant_api_key ? '已配置 (' + kb.qdrant_api_key_masked + ')' : '仅远程服务需要';
    $('#kb_collection').value = kb.collection || 'aicr_kb';
    $('#kb_embedding_model').value = kb.embedding_model || '';
    $('#kb_top_k').value = kb.top_k || 5;
    $('#kb_chunk_size').value = kb.chunk_size || 800;
    $('#kb_chunk_overlap').value = kb.chunk_overlap || 100;
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function saveSettings() {
  // 分 provider 段提交 + 通用参数
  const body = { provider: $('#provider').value, temperature: parseFloat($('#temperature').value) };
  const maxTokens = parseInt($('#max_tokens').value, 10);
  const timeoutMs = parseInt($('#timeout_ms').value, 10);
  if (!isNaN(maxTokens)) body.max_tokens = maxTokens;
  if (!isNaN(timeoutMs)) body.timeout_ms = timeoutMs;

  // provider 段字段  for (const name of ['deepseek', 'openai', 'anthropic', 'ollama']) {
    const section = {};
    const sectionEl = document.querySelector(`.provider-section[data-provider="${name}"]`);
    if (!sectionEl) continue;
    sectionEl.querySelectorAll('input[data-field]').forEach((input) => {
      const v = input.value.trim();
      if (v) section[input.dataset.field] = v;
    });
    if (Object.keys(section).length) body[name] = section;
  }

  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(body) });
    toast('配置已保存', 'success');
    loadSettings();
    refreshStatus();
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function testConnection() {
  const provider = $('#provider').value;
  try {
    const r = await fetch('/api/providers/test?provider=' + encodeURIComponent(provider), { method: 'POST' });
    const d = await r.json();
    if (d.ok) toast(`连接成功！${provider} 回复：${d.reply}`, 'success');
    else toast(`连接失败：${d.error}`, 'error');
  } catch (err) {
    toast('连接失败：' + err.message, 'error');
  }
}

async function saveKbSettings() {
  const body = { kb_enabled: $('#kb_enabled').checked };
  const url = $('#kb_qdrant_url').value.trim();
  const key = $('#kb_qdrant_api_key').value.trim();
  const collection = $('#kb_collection').value.trim();
  const model = $('#kb_embedding_model').value.trim();
  if (url) body.kb_qdrant_url = url;
  if (key) body.kb_qdrant_api_key = key;
  if (collection) body.kb_collection = collection;
  if (model) body.kb_embedding_model = model;
  const topK = parseInt($('#kb_top_k').value, 10);
  const chunkSize = parseInt($('#kb_chunk_size').value, 10);
  const overlap = parseInt($('#kb_chunk_overlap').value, 10);
  if (!isNaN(topK)) body.kb_top_k = topK;
  if (!isNaN(chunkSize)) body.kb_chunk_size = chunkSize;
  if (!isNaN(overlap)) body.kb_chunk_overlap = overlap;
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(body) });
    toast('知识库配置已保存', 'success');
    loadSettings();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function init() {
  $('#temperature').addEventListener('input', (e) => { $('#tempVal').textContent = e.target.value; });
  $('#btnSave').addEventListener('click', saveSettings);
  $('#btnSaveParams').addEventListener('click', saveSettings);
  $('#btnSaveKb').addEventListener('click', saveKbSettings);
  $('#btnTest').addEventListener('click', testConnection);
  refreshStatus();
  loadSettings();
}

document.addEventListener('DOMContentLoaded', init);
