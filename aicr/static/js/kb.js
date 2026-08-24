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

async function loadStats() {
  try {
    const s = await api('/api/kb/stats');
    const el = $('#kbStats');
    el.innerHTML = `
      <div class="settings-row"><label>状态</label><span>${s.enabled ? '✅ 已启用' : '⛔ 未启用（审查时不注入知识库上下文）'}</span></div>
      <div class="settings-row"><label>向量库</label><span>${s.backend === 'remote' ? '远程服务' : '本地内嵌'} · collection=${s.collection}</span></div>
      <div class="settings-row"><label>已入库向量</label><span>${s.points}</span></div>
      <div class="settings-row"><label>Embedding 模型</label><span>${s.embedding_model}</span></div>`;
  } catch (err) {
    $('#kbStats').innerHTML = `<div class="empty"><div class="big">⚠️</div>${err.message}</div>`;
  }
}

function setBusy(on, text) {
  $('#loading').style.display = on ? 'flex' : 'none';
  $('#loadingText').textContent = text || '';
  $('#btnIngest').disabled = on;
  $('#btnSearch').disabled = on;
  $('#btnClear').disabled = on;
}

async function doIngest() {
  const path = $('#ingestPath').value.trim();
  if (!path) { toast('请填写目录/文件路径', 'error'); return; }
  const body = { path, recreate: $('#recreate').checked };
  setBusy(true, '正在向量化并入库（首次需下载 embedding 模型，可能较慢）...');
  try {
    const s = await api('/api/kb/ingest', { method: 'POST', body: JSON.stringify(body) });
    toast(`摄入完成：${s.files} 个文件 → ${s.chunks} 个块 → ${s.points} 个向量`, 'success');
    loadStats();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function doSearch() {
  const query = $('#searchQuery').value.trim();
  if (!query) { toast('请输入查询内容', 'error'); return; }
  const top_k = parseInt($('#searchK').value, 10) || 5;
  setBusy(true, '正在检索...');
  try {
    const d = await api('/api/kb/search', {
      method: 'POST', body: JSON.stringify({ query, top_k }),
    });
    const el = $('#searchResults');
    if (!d.results.length) {
      el.innerHTML = '<div class="empty"><div class="big">🔍</div>未检索到相关内容，请先摄入知识库</div>';
      return;
    }
    el.innerHTML = d.results.map((r, i) => `
      <div class="batch-head">
        <span class="badge">${i + 1}</span>
        <span class="batch-file">${r.source}</span>
        <span class="dim">[${r.kind}] score=${r.score.toFixed(3)}</span>
      </div>
      <pre class="batch-body">${escapeHtml(r.text || '')}</pre>`).join('');
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function doClear() {
  if (!confirm('确定清空整个知识库？此操作不可恢复。')) return;
  try {
    await api('/api/kb', { method: 'DELETE' });
    toast('知识库已清空', 'success');
    loadStats();
    $('#searchResults').innerHTML = '';
  } catch (err) {
    toast(err.message, 'error');
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function init() {
  $('#btnIngest').addEventListener('click', doIngest);
  $('#btnSearch').addEventListener('click', doSearch);
  $('#btnClear').addEventListener('click', doClear);
  $('#searchQuery').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
  setBusy(false);
  refreshStatus();
  loadStats();
}

document.addEventListener('DOMContentLoaded', init);
