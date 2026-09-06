const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = path.join(__dirname, 'state.js');
function setup() {
  assert.ok(fs.existsSync(source), 'prototype state implementation must exist');
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(source, 'utf8'), context);
  return context.Prototype;
}
test('adopt only fills editor; blank and duplicate submission blocked', () => {
  const p = setup(), s = p.create();
  const t = s.tickets[0], before = t.messages.length;
  p.adopt(s, t.id);
  assert.equal(t.editor, t.draft);
  assert.equal(t.messages.length, before);
  assert.equal(t.status, 'open');
  t.editor = '  ';
  assert.equal(p.submit(s, t.id), false);
  t.editor = '虚构人工回复';
  assert.equal(p.submit(s, t.id), true);
  assert.equal(p.submit(s, t.id), false);
  assert.equal(t.messages.length, before + 1);
  assert.equal(s.chatState, 'human');
});
test('switch protection and search/status filters', () => {
  const p = setup(), s = p.create();
  s.tickets[0].editor = '未保存';
  assert.equal(p.dirty(s), true);
  assert.equal(p.select(s, 'DEMO-102', false), false);
  assert.equal(s.selected, 'DEMO-101');
  assert.equal(p.select(s, 'DEMO-102', true), true);
  assert.equal(s.tickets[0].editor, '');
  assert.equal(p.filter(s, '不存在', 'all').length, 0);
  assert.equal(p.filter(s, 'DEMO-102', 'open').length, 1);
  assert.equal(p.filter(s, '', 'resolved').length, 1);
});
test('customer modes and review events remain local', () => {
  const p = setup(), s = p.create();
  for (const mode of ['normal', 'waiting', 'human']) {
    p.setMode(s, mode);
    assert.equal(s.chatState, mode);
  }
  assert.equal(p.setMode(s, 'invalid'), false);
  p.adopt(s, s.selected);
  p.submit(s, s.selected);
  assert.ok(s.tickets[0].events.some(e => e.type === 'draft_adopted'));
  assert.ok(s.tickets[0].events.some(e => e.type === 'human_submitted'));
});
