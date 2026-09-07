'use strict';
const P = globalThis.Prototype;
const state = P.create();
const app = document.getElementById('app');
let route = '';
let search = '', statusFilter = 'all', toastTimer, submitting = false;
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const statusLabel = t => t.status === 'open' ? '待处理' : '已处理';
function toast(text) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('visible'), 3200);
}
function confirmAction(title, text, preview = '') {
  const dialog = document.getElementById('confirm-dialog');
  if (dialog.open) return Promise.resolve(false);
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-text').textContent = text;
  document.getElementById('confirm-preview').textContent = preview;
  dialog.returnValue = 'cancel';
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true }));
}
async function allowLeave() {
  if (submitting) return false;
  if (!P.dirty(state)) return true;
  if (!await confirmAction('有尚未提交的内容', '离开将丢弃当前输入，草稿采纳并不代表已发送。')) return false;
  P.current(state).editor = '';
  state.customerInput = '';
  return true;
}
function messages(items) {
  return items.map(m => `<article class="message ${esc(m.role)}"><div class="sender">${({ customer: '客户 · 虚构', ai: '智能助手 · 模拟', human: '人工客服 · 演示坐席', system: '服务提示' })[m.role]}</div><div class="bubble">${esc(m.text)}</div></article>`).join('');
}
function shell(content, active) {
  return `<header class="agent-header"><div class="brand"><span class="brand-mark">知</span>知序 <span class="muted">/ 坐席工作空间</span></div><nav aria-label="坐席导航"><a ${active === 'inbox' ? 'aria-current="page"' : ''} href="#/agent/inbox">处理台</a><a ${active === 'review' ? 'aria-current="page"' : ''} href="#/agent/review">会话复盘</a></nav><div class="identity"><span class="badge">本地演示 · 无实时连接</span><button data-action="logout">演示坐席 / 退出</button></div></header>${content}`;
}
function customer() {
  const modes = { normal: ['智能助手为您服务', '正常聊天', '您可以咨询订单、配送与售后问题。'], waiting: ['已转交人工客服', '等待人工', '您的问题已记录，请等待人工回复；演示不提供真实排队时间。'], human: ['人工客服已回复', '人工回复', '以下回复来自演示坐席。后续咨询将由智能助手继续接待。'] };
  const [title, label, hint] = modes[state.chatState];
  app.innerHTML = `<main class="customer-layout"><aside class="customer-intro"><div class="eyebrow">Z H I X U · SERVICE</div><h1>每一个问题，<br>都值得认真回应。</h1><p>从智能解答到人工跟进，<br>服务始终围绕您的问题展开。</p><div class="intro-card"><strong>您的专属咨询窗口</strong><p>这里只展示当前咨询。内部质检、AI 草稿与坐席工作信息不会向客户开放。</p></div><small>设计示例品牌 · 非真实客服服务</small></aside><section class="customer-chat" aria-label="客户咨询"><header class="chat-heading"><span class="brand-mark">知</span><div><h2>知序在线客服</h2><span class="muted">${title}</span></div><span class="badge ${state.chatState === 'waiting' ? 'warning' : 'success'}">${label}</span></header><div class="state-banner">${hint}</div><div class="conversation" role="log" aria-label="咨询消息">${messages(state.customerMessages)}${state.chatState === 'waiting' ? '<p class="system-note">人工正在等待处理您的咨询，请勿重复提交。</p>' : ''}${state.chatState === 'human' && !state.customerMessages.some(m => m.role === 'human') ? messages([{ role: 'human', text: '虚构回复：您好，我会先为您核实退款处理状态，再说明后续安排。' }]) : ''}</div><form id="customer-form" class="composer"><label for="customer-input">${state.chatState === 'waiting' ? '等待期间暂不接受新消息' : '继续咨询'}</label><textarea id="customer-input" maxlength="1000" rows="3" ${state.chatState === 'waiting' ? 'disabled' : ''} placeholder="请输入问题（请勿填写真实个人信息）">${esc(state.customerInput)}</textarea><div class="composer-footer"><small>Enter 发送 · Shift+Enter 换行</small><button class="primary" ${state.chatState === 'waiting' ? 'disabled' : ''}>发送消息</button></div></form><div class="demo-controls"><label for="chat-mode">原型状态演示</label><select id="chat-mode">${Object.entries(modes).map(([k, v]) => `<option value="${k}" ${state.chatState === k ? 'selected' : ''}>${v[1]}</option>`).join('')}</select><small>仅切换展示状态，不发起真实转人工</small></div></section></main>`;
}
function login() {
  app.innerHTML = `<main class="login-layout"><section class="login-story"><span class="brand-mark">知</span><div class="eyebrow">AGENT WORKSPACE</div><h1>让判断有依据，<br>让服务有温度。</h1><p>会话、建议与质检集中呈现。<br>最终回复由坐席确认，而不是由草稿自动发送。</p><div class="login-points"><span>01 理解客户上下文</span><span>02 审核 AI 建议</span><span>03 确认回复并复盘</span></div></section><section class="login-card"><span class="badge warning">模拟登录 · 不验证身份</span><h2>进入坐席工作空间</h2><p class="muted">本原型只演示角色分区，不代表已具备权限隔离。</p><form id="login-form"><label for="demo-account">演示账号</label><input id="demo-account" value="demo.agent（虚构）" readonly><label for="demo-role">演示角色</label><input id="demo-role" value="客户服务坐席" readonly><label class="check"><input id="demo-agree" type="checkbox" required>我了解所有数据为虚构且不会连接真实服务</label><button class="primary full">以演示身份进入</button></form><p class="small">无需输入真实账号或密码。刷新页面将退出演示身份并重置数据。</p></section></main>`;
}
function ticketList() {
  const rows = P.filter(state, search, statusFilter);
  return rows.length ? rows.map(t => `<button class="ticket ${state.selected === t.id ? 'selected' : ''}" data-ticket="${t.id}" aria-pressed="${state.selected === t.id}"><div class="row"><strong>${esc(t.name)}</strong><span class="badge ${t.status === 'open' ? 'warning' : 'success'}">${statusLabel(t)}</span></div><h3>${esc(t.topic)}</h3><p>${esc(t.query)}</p><div class="row small"><span>${t.id}</span><span>${esc(t.category)}</span></div></button>`).join('') : '<div class="empty"><h3>没有匹配的工单</h3><p>尝试其他关键词或切换状态。</p><button data-action="clear-filter">清除筛选</button></div>';
}
function timeline(t) {
  return `<ol class="timeline">${t.events.map(e => `<li><time>${esc(e.time)}</time><strong>${esc(e.text)}</strong><small>${esc(e.type)} · 虚构事件</small></li>`).join('')}</ol>`;
}
function inbox() {
  const t = P.current(state);
  app.innerHTML = shell(`<main class="workspace"><aside class="queue"><div class="panel-heading"><div class="eyebrow">INBOX</div><h1>待办与会话 <span class="count">${state.tickets.filter(x => x.status === 'open').length}</span></h1><p class="muted">虚构队列 · 仅内存演示</p><label for="ticket-search">搜索工单</label><input id="ticket-search" type="search" placeholder="客户、问题或工单编号" value="${esc(search)}"><label for="ticket-filter">处理状态</label><select id="ticket-filter"><option value="all" ${statusFilter === 'all' ? 'selected' : ''}>全部工单</option><option value="open" ${statusFilter === 'open' ? 'selected' : ''}>待处理</option><option value="resolved" ${statusFilter === 'resolved' ? 'selected' : ''}>已处理</option></select></div><div id="ticket-list" class="ticket-list">${ticketList()}</div><p class="queue-foot">筛选不切换当前会话，避免丢失编辑内容。</p></aside><section class="work-detail"><header class="detail-heading"><div><span class="eyebrow">${t.id} · 虚构会话</span><h2>${esc(t.topic)}</h2><span class="muted">${esc(t.name)} / ${esc(t.category)}</span></div><span class="badge ${t.status === 'open' ? 'warning' : 'success'}">${statusLabel(t)}</span></header><div class="conversation" role="log" aria-label="当前工单对话">${messages(t.messages)}</div>${t.status === 'open' ? `<section class="draft"><div class="row"><strong>AI 建议草稿</strong><span class="badge">内部可见 · 未发送</span></div><p>${esc(t.draft)}</p><button data-action="adopt">采纳到编辑器</button></section><form id="reply-form" class="composer"><div class="row"><label for="reply-input">人工回复</label><small id="dirty-label">${t.editor ? '有未提交内容' : '尚未采纳草稿'}</small></div><textarea id="reply-input" maxlength="2000" rows="4" placeholder="核实信息后编辑回复，确认后才会提交">${esc(t.editor)}</textarea><div class="composer-footer"><small>提交后关闭该虚构工单</small><button id="submit-reply" class="primary" ${!t.editor.trim() ? 'disabled' : ''}>预览并确认提交</button></div></form>` : `<section class="resolved"><h3>人工处理已完成</h3><p>${esc(t.humanReply)}</p><span class="badge success">演示记录成功 · 禁止重复提交</span><p><a href="#/agent/review">查看本次处理复盘 →</a></p></section>`}</section><aside class="insights"><details><summary>质检与决策依据 <span class="muted">展开 / 收起</span></summary><div class="insight-body"><div class="eyebrow">QUALITY CHECK · INTERNAL</div><div class="score">${t.score}<small>/ 100 · 虚构评分</small></div><h3>人工介入原因</h3><p>${esc(t.reason)}</p><div class="notice">评分仅辅助判断，不能替代事实核实；本页不展示真实客户资料。</div><h3>本次决策轨迹</h3>${timeline(t)}<a href="#/agent/review">打开完整复盘 →</a></div></details></aside></main>`, 'inbox');
  if (window.matchMedia('(min-width: 1180px)').matches) app.querySelector('.insights details').open = true;
}
function review() {
  const t = P.current(state);
  app.innerHTML = shell(`<main class="review"><header class="review-heading"><div><div class="eyebrow">CONVERSATION REVIEW</div><h1>从问题到回复，回看每次判断</h1><p class="muted">只读复盘 · 所有事件为本地虚构数据，不是生产审计日志</p></div><a class="button" href="#/agent/inbox">返回处理台</a></header><label for="review-ticket">选择复盘工单</label><select id="review-ticket">${state.tickets.map(x => `<option value="${x.id}" ${x.id === t.id ? 'selected' : ''}>${x.id} · ${esc(x.topic)} · ${statusLabel(x)}</option>`).join('')}</select><div class="review-grid"><section class="review-card"><h2>客户对话与最终回复</h2>${messages(t.messages)}${t.status === 'resolved' && !t.messages.some(m => m.role === 'human') ? messages([{ role: 'human', text: t.humanReply }]) : ''}<p class="notice">内部草稿不属于已发送消息。采纳记录只表示填入编辑器。</p></section><section class="review-card"><h2>决策与人工操作事件</h2>${timeline(t)}</section></div></main>`, 'review');
}
function render() {
  document.title = `${({ '/chat': '客户咨询', '/agent/login': '坐席登录', '/agent/inbox': '坐席处理台', '/agent/review': '会话复盘' })[route]} · 知序离线原型`;
  ({ '/chat': customer, '/agent/login': login, '/agent/inbox': inbox, '/agent/review': review })[route]();
}
function targetRoute(hash) {
  const value = hash.replace(/^#/, '') || '/chat';
  if (!['/chat', '/agent/login', '/agent/inbox', '/agent/review'].includes(value)) return '/chat';
  if (['/agent/inbox', '/agent/review'].includes(value) && !state.loggedIn) return '/agent/login';
  return value;
}
async function navigate(hash) {
  const next = targetRoute(hash);
  if (route && route !== next && !await allowLeave()) {
    history.replaceState(null, '', `#${route}`);
    return;
  }
  route = next;
  history.replaceState(null, '', `#${route}`);
  render();
}
document.addEventListener('click', async e => {
  const link = e.target.closest('a[href^="#/"]');
  if (link) { e.preventDefault(); await navigate(link.getAttribute('href')); return; }
  const ticket = e.target.closest('[data-ticket]');
  if (ticket) {
    if (ticket.dataset.ticket !== state.selected && await allowLeave()) { P.select(state, ticket.dataset.ticket, true); render(); }
    return;
  }
  const action = e.target.closest('[data-action]')?.dataset.action;
  if (action === 'clear-filter') { search = ''; statusFilter = 'all'; render(); }
  if (action === 'logout' && await allowLeave()) { state.loggedIn = false; await navigate('#/agent/login'); }
  if (action === 'adopt') {
    const t = P.current(state);
    if (t.editor && !await confirmAction('替换当前编辑内容？', '采纳草稿会覆盖编辑器，但不会提交。')) return;
    P.adopt(state, t.id); render(); document.getElementById('reply-input').focus(); toast('草稿已填入编辑器，尚未发送');
  }
});
document.addEventListener('input', e => {
  if (e.target.id === 'ticket-search') { search = e.target.value; document.getElementById('ticket-list').innerHTML = ticketList(); }
  if (e.target.id === 'customer-input') state.customerInput = e.target.value;
  if (e.target.id === 'reply-input') {
    P.current(state).editor = e.target.value;
    document.getElementById('dirty-label').textContent = e.target.value ? '有未提交内容' : '尚未采纳草稿';
    document.getElementById('submit-reply').disabled = !e.target.value.trim() || submitting;
  }
});
document.addEventListener('change', async e => {
  if (e.target.id === 'ticket-filter') { statusFilter = e.target.value; document.getElementById('ticket-list').innerHTML = ticketList(); }
  if (e.target.id === 'review-ticket') { P.select(state, e.target.value, false); render(); }
  if (e.target.id === 'chat-mode') {
    const mode = e.target.value;
    if (!await allowLeave()) { e.target.value = state.chatState; return; }
    P.setMode(state, mode); render();
  }
});
document.addEventListener('submit', async e => {
  if (!['login-form', 'customer-form', 'reply-form'].includes(e.target.id)) return;
  e.preventDefault();
  if (e.target.id === 'login-form') { state.loggedIn = true; await navigate('#/agent/inbox'); }
  if (e.target.id === 'customer-form') {
    const text = state.customerInput.trim();
    if (!text || state.chatState === 'waiting') return;
    state.customerMessages.push({ role: 'customer', text }, { role: 'ai', text: '模拟回答：已收到您的咨询。此原型不查询订单、不调用模型，您可用下方控件演示人工服务状态。' });
    state.customerInput = ''; P.setMode(state, 'normal'); render();
    const log = app.querySelector('.conversation'); log.scrollTop = log.scrollHeight;
    document.getElementById('customer-input').focus();
  }
  if (e.target.id === 'reply-form') {
    if (submitting) return;
    const t = P.current(state);
    if (t.status !== 'open' || !t.editor.trim()) return;
    submitting = true;
    const button = document.getElementById('submit-reply'); button.disabled = true;
    const accepted = await confirmAction('确认提交人工回复', `将向 ${t.name}（${t.id}）记录以下虚构回复并关闭工单。不是直接发送 AI 草稿。`, t.editor.trim());
    if (accepted && P.submit(state, t.id)) { toast('虚构工单已处理，可在复盘查看操作事件'); }
    submitting = false; render();
  }
});
document.addEventListener('keydown', e => {
  if (e.target.id === 'customer-input' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById('customer-form').requestSubmit(); }
});
window.addEventListener('hashchange', () => navigate(location.hash));
window.addEventListener('beforeunload', e => { if (P.dirty(state)) { e.preventDefault(); e.returnValue = ''; } });
navigate(location.hash);
