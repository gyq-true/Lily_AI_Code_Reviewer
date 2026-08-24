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

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// 简单的 Markdown 代码块 + 换行渲染（避免引入额外依赖）
function renderMarkdown(text) {
  const esc = escapeHtml(text);
  return esc
    .replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="chat-code"><code>${code}</code></pre>`)
    .replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>')
    .replace(/\n/g, '<br>');
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

let sessionId = null;
let busy = false;

function appendMessage(role, content) {
  const log = $('#chatLog');
  const wrap = document.createElement('div');
  wrap.className = 'chat-msg ' + (role === 'user' ? 'chat-msg-user' : 'chat-msg-assistant');
  const body = document.createElement('div');
  body.className = 'chat-bubble';
  if (role === 'assistant') body.innerHTML = renderMarkdown(content);
  else body.textContent = content;
  wrap.appendChild(body);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return body;
}

function showThinking() {
  $('#thinking').style.display = 'block';
  $('#thinkingLabel').textContent = '思考中…';
  $('#thinkingBody').textContent = '';
}

function hideThinking(reasoning, finishReason) {
  const box = $('#thinking');
  if (!reasoning) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  $('#thinkingLabel').textContent = finishReason === 'length' || finishReason === 'max_tokens'
    ? '思考内容（已触发续写）' : '思考内容';
  $('#thinkingBody').textContent = reasoning;
}

async function send() {
  const input = $('#chatInput');
  const message = input.value.trim();
  if (!message || busy) return;

  busy = true;
  $('#btnSend').disabled = true;
  appendMessage('user', message);
  input.value = '';
  showThinking();

  try {
    const payload = { message };
    if (sessionId) payload.session_id = sessionId;
    const data = await api('/api/chat', { method: 'POST', body: JSON.stringify(payload) });
    sessionId = data.session_id;
    appendMessage('assistant', data.reply || '(无回复内容)');
    hideThinking(data.reasoning, data.finish_reason);
  } catch (err) {
    hideThinking('', null);
    appendMessage('assistant', '⚠️ 请求失败：' + err.message);
    toast(err.message, 'error');
  } finally {
    busy = false;
    $('#btnSend').disabled = false;
    input.focus();
  }
}

async function reset() {
  if (sessionId) {
    try { await api('/api/chat/' + sessionId, { method: 'DELETE' }); } catch { /* 忽略 */ }
  }
  sessionId = null;
  $('#chatLog').innerHTML = '';
  $('#thinking').style.display = 'none';
  $('#chatInput').value = '';
  toast('已开启新对话', 'success');
  $('#chatInput').focus();
}

function init() {
  $('#btnSend').addEventListener('click', send);
  $('#btnReset').addEventListener('click', reset);
  const input = $('#chatInput');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  const toggle = $('#thinkingToggle');
  if (toggle) toggle.addEventListener('click', () => $('#thinking').classList.toggle('open'));
  refreshStatus();
}

document.addEventListener('DOMContentLoaded', init);
