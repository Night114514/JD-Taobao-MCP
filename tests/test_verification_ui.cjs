// Execute production challenge scan on synthetic DOM only; no browser/network.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../jd_taobao_mcp/browser.py'), 'utf8');
const begin = source.indexOf('r"""(body) =>');
assert.ok(begin >= 0);
const end = source.indexOf('"""', begin + 4);
const code = source.slice(begin + 4, end);
const selected = 'input[autocomplete="one-time-code"], input[name*="captcha" i], iframe[src*="captcha" i], iframe[src*="punish" i], #nc_1_wrapper, .nc-container, #baxia-dialog-content, #JDJRV-wrap, .JDJRV-wrap'.split(', ');
function scan(nodes, failure = false) {
  const body = {querySelectorAll(selector) {
    assert.deepEqual(selector.split(', '), selected);
    if (failure) throw new Error('synthetic DOM failure');
    return nodes.filter(n => selected.includes(n.selector));
  }};
  const context = vm.createContext({body, getComputedStyle: n => n.style});
  return vm.runInContext('(' + code + ')(body)', context, {timeout:1000});
}
function node(selector, rects = 1, visibility = 'visible', display = 'block') {
  return {selector, getClientRects: () => Array(rects).fill({}), style: {visibility, display}};
}
const cases = [
  ['empty ordinary DOM', () => assert.equal(scan([]), false)],
  ['ordinary product field', () => assert.equal(scan([node('input[name="product"]')]), false)],
  ['visible challenge controls', () => { for (const s of selected) assert.equal(scan([node(s)]), true); }],
  ['hidden challenge template', () => assert.equal(scan([node(selected[0], 1, 'hidden')]), false)],
  ['display none', () => assert.equal(scan([node(selected[0], 1, 'visible', 'none')]), false)],
  ['no rendered rectangles', () => assert.equal(scan([node(selected[0], 0)]), false)],
  ['later visible overlay', () => assert.equal(scan([node(selected[0], 0), node(selected[1])]), true)],
  ['DOM error remains error', () => assert.throws(() => scan([], true), /synthetic DOM failure/)],
];
let failures = 0;
for (const [name, test] of cases) {
  try { test(); console.log('PASS ' + name); }
  catch (error) { failures++; console.log('FAIL ' + name + ': ' + error.message); }
}
console.log(JSON.stringify({tests: cases.length, failures, browser_started:false}));
process.exitCode = failures ? 1 : 0;
