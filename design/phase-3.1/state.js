/* Fictional in-memory demonstration only. No network or persistence. */
globalThis.Prototype = (() => {
  const event = (type, text) => ({ type, text, time: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
  function create() {
    return {
      selected: 'DEMO-101', chatState: 'normal', loggedIn: false,
      customerInput: '', customerMessages: [{ role: 'ai', text: '您好，我是智能服务助手。请问有什么可以帮您？' }],
      tickets: [
        { id: 'DEMO-101', name: '林女士（虚构）', topic: '退款进度需要核实', query: '退款申请三天了，为什么还没到账？', score: 62, reason: '缺少退款实际状态，不能承诺到账时间。', draft: '您好，我会先核实退款申请与支付渠道的处理状态，再向您说明后续安排。', status: 'open', category: '售后退款' },
        { id: 'DEMO-102', name: '周先生（虚构）', topic: '配送地址修改', query: '订单发出后还能修改地址吗？', score: 68, reason: '需核实物流节点与改址权限。', draft: '您好，需要先确认包裹是否已交付承运商，我会为您核实可调整范围。', status: 'open', category: '订单配送' },
        { id: 'DEMO-103', name: '陈女士（虚构）', topic: '电子发票说明', query: '在哪里申请电子发票？', score: 88, reason: '已由演示坐席核实。', draft: '可在订单详情中选择申请发票。', status: 'resolved', category: '发票服务' }
      ].map(t => ({ ...t, editor: '', humanReply: t.status === 'resolved' ? '演示回复：请在订单详情中申请电子发票。' : '', messages: [{ role: 'customer', text: t.query }, { role: 'system', text: '咨询已转交人工，内部草稿未发送给客户。' }], events: [event('classify', `意图分类 · ${t.category}`), event('quality_check', `质检 ${t.score} 分 · ${t.reason}`), event('handoff', `创建虚构工单 ${t.id}`), event(t.status === 'open' ? 'suspended' : 'human_submitted', t.status === 'open' ? '等待人工处理' : '历史人工回复已记录（虚构）')] }))
    };
  }
  const current = s => s.tickets.find(t => t.id === s.selected);
  const dirty = s => Boolean(current(s)?.editor.trim() || s.customerInput.trim());
  function select(s, id, discard) {
    if (id === s.selected) return true;
    if (!s.tickets.some(t => t.id === id)) return false;
    if (dirty(s) && !discard) return false;
    if (discard) { current(s).editor = ''; s.customerInput = ''; }
    s.selected = id;
    return true;
  }
  function adopt(s, id) {
    const t = s.tickets.find(t => t.id === id);
    if (!t || t.status !== 'open') return false;
    t.editor = t.draft;
    t.events.push(event('draft_adopted', '采纳草稿到编辑器 · 尚未发送'));
    return true;
  }
  function submit(s, id) {
    const t = s.tickets.find(t => t.id === id);
    if (!t || t.status !== 'open' || !t.editor.trim()) return false;
    t.humanReply = t.editor.trim();
    t.status = 'resolved';
    t.editor = '';
    t.messages.push({ role: 'human', text: t.humanReply });
    t.events.push(event('human_submitted', '坐席确认提交 · 虚构回复已记录'));
    if (id === 'DEMO-101') {
      s.chatState = 'human';
      s.customerMessages.push({ role: 'human', text: t.humanReply });
    }
    return true;
  }
  function filter(s, q, status) {
    q = q.trim().toLowerCase();
    return s.tickets.filter(t => (status === 'all' || t.status === status) && `${t.id} ${t.name} ${t.topic} ${t.query}`.toLowerCase().includes(q));
  }
  function setMode(s, mode) {
    if (!['normal', 'waiting', 'human'].includes(mode)) return false;
    s.chatState = mode;
    return true;
  }
  return { create, current, dirty, select, adopt, submit, filter, setMode };
})();
