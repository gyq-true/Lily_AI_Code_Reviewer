'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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

function updateStats() {
  const code = $('#code').value;
  $('#lineCount').textContent = (code ? code.split('\n').length : 0) + ' 行';
  $('#charCount').textContent = code.length + ' 字符';
}

// ---------- 结果渲染 ----------
const SEVERITY_TEXT = { critical: '严重', major: '重要', minor: '一般', suggestion: '建议' };

function scoreClass(score) {
  return score >= 80 ? 'score-good' : score >= 60 ? 'score-mid' : 'score-bad';
}

function renderSingleReport(data, container) {
  const counts = { critical: 0, major: 0, minor: 0, suggestion: 0 };
  (data.issues || []).forEach((i) => { counts[i.severity] = (counts[i.severity] || 0) + 1; });
  const meta = data.meta || {};

  const issuesHtml = (data.issues || []).map((issue) => {
    const codeHtml = issue.code
      ? `<div class="fix-label">修复示例</div><pre class="code"><code>${escapeHtml(issue.code)}</code></pre>` : '';
    return `
      <div class="issue severity-${issue.severity}">
        <div class="issue-head">
          <span class="badge badge-${issue.severity}">${SEVERITY_TEXT[issue.severity] || issue.severity}</span>
          <span class="issue-title">${escapeHtml(issue.title)}</span>
          ${issue.category ? `<span class="tag">${escapeHtml(issue.category)}</span>` : ''}
          ${issue.line ? `<span class="issue-line">第 ${issue.line} 行</span>` : ''}
          <span class="chevron">▼</span>
        </div>
        <div class="issue-body">
          ${issue.description ? `<div class="desc">${escapeHtml(issue.description)}</div>` : ''}
          ${issue.suggestion ? `<div class="fix-label">改进建议</div><div class="desc">${escapeHtml(issue.suggestion)}</div>` : ''}
          ${codeHtml}
        </div>
      </div>`;
  }).join('');

  const highlightsHtml = (data.highlights || []).length
    ? `<ul class="highlights">${data.highlights.map((h) => `<li>${escapeHtml(h)}</li>`).join('')}</ul>`
    : '<div class="empty" style="padding:12px">未标注亮点</div>';
  const recsHtml = (data.recommendations || []).length
    ? `<ol class="recommendations">${data.recommendations.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ol>`
    : '<div class="empty" style="padding:12px">暂无建议</div>';

  container.innerHTML = `
    <div class="result-header">
      <div class="score-ring" style="--score:${data.score}"><div class="score-num">${data.score}</div></div>
      <div class="result-title">
        <h2>代码质量评分</h2>
        <p>${escapeHtml(data.summary || '')}</p>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><div class="stat-num">${counts.critical}</div><div class="stat-label">严重</div></div>
      <div class="stat"><div class="stat-num">${counts.major}</div><div class="stat-label">重要</div></div>
      <div class="stat"><div class="stat-num">${counts.minor}</div><div class="stat-label">一般</div></div>
      <div class="stat"><div class="stat-num">${counts.suggestion}</div><div class="stat-label">建议</div></div>
      <div class="stat"><div class="stat-num">${meta.line_count ?? '-'}</div><div class="stat-label">行数</div></div>
      <div class="stat"><div class="stat-num">${meta.elapsed_ms ? (meta.elapsed_ms / 1000).toFixed(1) + 's' : '-'}</div><div class="stat-label">耗时</div></div>
      ${meta.id ? `<div class="stat"><div class="stat-num" style="font-size:11px;font-family:var(--mono);line-height:44px">${meta.id}</div><div class="stat-label">运行 ID</div></div>` : ''}
    </div>
    <div class="card" style="background:var(--bg-3);margin-top:16px">
      <div class="card-title">✓ 亮点</div>${highlightsHtml}
    </div>
    <div class="card" style="background:var(--bg-3)">
      <div class="card-title">问题清单（${data.issues ? data.issues.length : 0} 个）</div>
      ${issuesHtml || '<div class="empty" style="padding:12px">未发现问题，代码质量不错！</div>'}
    </div>
    <div class="card" style="background:var(--bg-3)">
      <div class="card-title">改进建议</div>${recsHtml}
    </div>`;
}

function renderBatch(payload) {
  const body = $('#resultBody');
  const results = payload.results || [];
  body.innerHTML = `
    <div class="result-header">
      <div class="score-ring" style="--score:${payload.avg_score ?? 0}"><div class="score-num">${payload.avg_score ?? '-'}</div></div>
      <div class="result-title">
        <h2>批量审查完成（共 ${payload.total} 个文件）</h2>
        <p>平均评分 ${payload.avg_score ?? '-'}，点击文件展开详情</p>
      </div>
    </div>
    <div style="margin-top:16px">
      ${results.map((r, i) => `
        <div class="batch-file" data-i="${i}">
          <div class="batch-head">
            <div class="h-score ${scoreClass(r.score)}" style="width:38px;height:38px;font-size:13px">${r.score}</div>
            <span class="fname">${escapeHtml(r.file || r.meta?.filename || '未知文件')}</span>
            <span class="h-issues">${r.error ? '⚠ 审查失败' : (r.issueCount ?? r.issues?.length ?? 0) + ' 个问题'}</span>
            <span class="chevron">▼</span>
          </div>
          <div class="batch-body"></div>
        </div>`).join('')}
    </div>`;

  $$('#resultBody .batch-file').forEach((el) => {
    const head = el.querySelector('.batch-head');
    const inner = el.querySelector('.batch-body');
    head.addEventListener('click', () => {
      if (!inner.dataset.rendered) {
        renderSingleReport(results[+el.dataset.i], inner);
        inner.querySelectorAll('.issue .issue-head').forEach((h) =>
          h.addEventListener('click', () => h.closest('.issue').classList.toggle('open')));
        inner.dataset.rendered = '1';
      }
      el.classList.toggle('open');
    });
    // 默认展开第一个
    if (+el.dataset.i === 0) head.click();
  });
}

function showResult(payload) {
  if (payload && payload.batch) renderBatch(payload);
  else renderSingleReport(payload, $('#resultBody'));
  $('#result').style.display = 'block';
  $('#result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---------- 运行记录 ----------
async function loadHistory() {
  try {
    const list = await api('/api/runs');
    const c = $('#historyList');
    if (!list.length) {
      c.innerHTML = '<div class="empty"><div class="big">📄</div>暂无运行记录</div>';
      return;
    }
    c.innerHTML = list.map((m) => `
      <div class="history-item" data-id="${m.id}">
        <div class="h-score ${m.status === 'error' ? 'score-bad' : scoreClass(m.score ?? 0)}">${m.status === 'error' ? '✗' : (m.score ?? '-')}</div>
        <div class="h-info">
          <div class="h-name">${escapeHtml(m.filename || m.path || '粘贴的代码')}</div>
          <div class="h-meta">
            <span>${escapeHtml(m.provider || '')}/${escapeHtml(m.model || '')}</span>
            <span>${escapeHtml(m.created_at || '')}</span>
            <span>${escapeHtml(m.status)}</span>
          </div>
        </div>
        <span class="h-issues">${m.issue_count ?? 0} 个问题</span>
        <button class="btn btn-danger btn-sm del-btn" data-del="${m.id}">删除</button>
      </div>`).join('');

    $$('.history-item').forEach((el) => {
      el.addEventListener('click', async (e) => {
        if (e.target.closest('.del-btn')) return;
        try {
          const rec = await api('/api/runs/' + el.dataset.id);
          if (rec.report) { showResult({ ...rec.report, meta: rec.meta }); toast('已载入历史报告', 'success'); }
          else toast('该记录无完整报告', 'error');
        } catch (err) { toast(err.message, 'error'); }
      });
    });
    $$('.del-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('确定删除这条运行记录？')) return;
        try { await api('/api/runs/' + btn.dataset.del, { method: 'DELETE' }); toast('已删除', 'success'); loadHistory(); }
        catch (err) { toast(err.message, 'error'); }
      });
    });
  } catch (err) {
    $('#historyList').innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

// ---------- 审查动作 ----------
let busy = false;

function commonBody() {
  return {
    filename: $('#filename').value.trim() || null,
    language: $('#language').value || null,
    focus: $$('#focusGroup input:checked').map((el) => el.value),
    mode: $('#multiMode').checked ? 'multi' : 'single',
  };
}

async function doRequest(path, payload) {
  busy = true;
  $('#btnReview').disabled = true;
  $('#btnIcon').textContent = '审查中...';
  $('#loading').classList.add('show');
  try {
    const data = await api(path, { method: 'POST', body: JSON.stringify(payload) });
    showResult(data);
    toast('审查完成', 'success');
    loadHistory();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    busy = false;
    $('#btnReview').disabled = false;
    $('#btnIcon').textContent = '开始审查';
    $('#loading').classList.remove('show');
  }
}

function init() {
  $('#code').addEventListener('input', updateStats);

  $('#btnReview').addEventListener('click', () => {
    const code = $('#code').value.trim();
    if (!code) return toast('请先输入或上传要审查的代码', 'error');
    doRequest('/api/review', { code, ...commonBody() });
  });

  $('#btnClear').addEventListener('click', () => {
    $('#code').value = ''; $('#filename').value = ''; updateStats();
    $('#result').style.display = 'none'; toast('已清空', 'info');
  });

  $('#btnUpload').addEventListener('click', () => $('#fileInput').click());
  $('#fileInput').addEventListener('change', async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    if (files.length === 1) {
      const f = files[0];
      $('#filename').value = f.name;
      $('#code').value = await f.text();
      updateStats();
      toast(`已载入：${f.name}，点击“开始审查”`, 'success');
      return;
    }
    const contents = [];
    for (const f of files) contents.push({ name: f.name, content: await f.text() });
    doRequest('/api/review/files', { files: contents, ...commonBody() });
  });

  $('#btnScanDir').addEventListener('click', () => {
    const p = $('#scanPath').value.trim();
    if (!p) return toast('请输入服务器上的目录路径', 'error');
    doRequest('/api/review/batch', { path: p, ...commonBody() });
  });

  $('#btnGitDiff').addEventListener('click', () => {
    const repo = $('#gitRepo').value.trim();
    if (!repo) return toast('请输入 git 仓库路径', 'error');
    doRequest('/api/review/batch', { git_repo: repo, git_staged: $('#gitStaged').checked, ...commonBody() });
  });

  refreshStatus();
  updateStats();
  loadHistory();
}

document.addEventListener('DOMContentLoaded', init);
