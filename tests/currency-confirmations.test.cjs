const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({confirmed = false, tickets = 2} = {}) {
  const calls = [], dialogs = [];
  const context = {
    console, document: {querySelector: () => null, getElementById: () => null},
    window: {
      clubDialog: {confirm: async options => {dialogs.push(options); return confirmed;}, notice: async options => dialogs.push(options)},
      clubApi: {
        requestId: () => 'test-request',
        request: async (url, options = {}) => {
          calls.push({url, options});
          let data = url.includes('inventory') ? {inventory:[{item_type:'makeup_ticket', quantity:tickets}]} :
            url.includes('makeup') ? {success:true, week_id:14} :
            url.includes('purchase') ? {balance:7, total_price:3} : {balance:10, can_purchase:true};
          return {ok:true, json:async () => data};
        }
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../currency.js'), 'utf8'), context);
  return {module:context.window.CurrencyModule, calls, dialogs};
}

test('canceling ticket use never spends a ticket or opens permission', async () => {
  const state = setup();
  assert.equal(await state.module.performMakeupCheckin('2026-10-28'), false);
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 0);
  assert.match(state.dialogs[0].text, /补签券 ×1/);
});
test('confirmed ticket use sends exactly one permission request', async () => {
  const state = setup({confirmed:true});
  await state.module.performMakeupCheckin('2026-10-28');
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 1);
});
test('previously unlocked date does not prompt for another ticket', async () => {
  const state = setup({tickets:0});
  await state.module.performMakeupCheckin('2026-10-28', {alreadyOpen:true});
  assert.equal(state.dialogs.length, 0);
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 1);
});
test('empty backpack does not send a ticket consumption request', async () => {
  const state = setup({tickets:0});
  await state.module.performMakeupCheckin('2026-10-28');
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 0);
  assert.equal(state.dialogs[0].title, '补签券不足');
});
test('canceling purchase never sends a purchase request', async () => {
  const state = setup();
  await state.module.purchaseItem(1, 1, {name:'补签券', price:3});
  assert.equal(state.calls.length, 0);
});
test('confirmed purchase keeps the idempotency token and reports success in site dialog', async () => {
  const state = setup({confirmed:true});
  assert.equal(await state.module.purchaseItem(1, 1, {name:'补签券', price:3}), true);
  assert.equal(state.calls.length, 1);
  assert.equal(JSON.parse(state.calls[0].options.body).request_id, 'test-request');
  assert.equal(state.dialogs.at(-1).title, '购买成功');
});
