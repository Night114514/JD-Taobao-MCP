// Execute the actual production evaluate function against a synthetic DOM.
// No Playwright, browser, website, network, child processes or user state.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../jd_taobao_mcp/extractors/detail.py'), 'utf8');
const start = source.indexOf('r"""');
const end = source.indexOf('"""', start + 4);
const evaluate = source.slice(start + 4, end);
const LIMIT = 80000;
function run(chunks) {
  const nodes = chunks.map(([tag, text]) => ({
    textContent: text, nodeValue: text,
    parentElement: {closest: () => /^(script|style|noscript|template)$/.test(tag) ? {} : null}
  }));
  const body = {innerText: 'Visible product', textContent: chunks.map(x=>x[1]).join('')};
  const document = {
    body, querySelector: () => null, querySelectorAll: () => [],
    createTreeWalker(root, what, filter) {
      let i = 0;
      return {nextNode() {
        while (i < nodes.length) {
          const n = nodes[i++];
          if (!filter || filter.acceptNode(n) === 1) return n;
        }
        return null;
      }};
    }
  };
  const context = vm.createContext({document, NodeFilter:{SHOW_TEXT:4,FILTER_ACCEPT:1,FILTER_REJECT:2}});
  const fn = vm.runInContext('(' + evaluate + ')', context, {timeout:1000});
  return fn({title:[],price:[],shop:[],reviews:[],sales:[],specs:[],review_items:[]});
}
const cases = [
  ['large hidden text bounded before serialization', () => {
    const r=run([['div','x'.repeat(3*1024*1024)]]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.equal(r.body_text_all_truncated,true);
    assert.ok(Buffer.byteLength(JSON.stringify(r.body_text_all),'utf8') <= 480002);
  }],
  ['script style and hydration excluded, hidden product retained', () => {
    const text='参数信息 品牌 Example 型号 K1 额定功率 100W 额定电压 220V 图文详情';
    const r=run([['script','HYDRATION'.repeat(400000)],['style','STYLE'.repeat(400000)],['template','TEMPLATE'],['noscript','NOSCRIPT'],['div',text]]);
    assert.equal(r.body_text_all,text);
    assert.equal(r.body_text_all_truncated,false);
  }],
  ['network parameters and dated review preserved', () => {
    const text='参数信息 千兆 适用网络类型 M.2 网卡插口 是 是否无线 3000Mbps 传输速度 品牌 WTXUP 型号 MT7925 售后服务 店铺三包 适用场景 台式机 无线协议 802.11be 频段类型 6GHz 成色 全新 图文详情 用户评价·1 t***3 2026-09-01 很好用非常满意 查看全部评价';
    assert.equal(run([['div',text]]).body_text_all,text);
  }],
  ['split nodes retain textContent order and whitespace', () => {
    assert.equal(run([['div','品牌 '],['span','Example '],['div','型号 K1']]).body_text_all,'品牌 Example 型号 K1');
  }],
  ['exact limit is not truncated', () => {
    const r=run([['div','x'.repeat(LIMIT)]]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.equal(r.body_text_all_truncated,false);
  }],
  ['tail is truncated and JSON escape bound holds', () => {
    const r=run([['div','\u0001'.repeat(LIMIT)],['div','UNSEEN PARAMETER']]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.equal(r.body_text_all_truncated,true);
    assert.ok(!r.body_text_all.includes('UNSEEN'));
    assert.ok(Buffer.byteLength(JSON.stringify(r.body_text_all),'utf8') <= 480002);
  }],
];
cases.push(
  ['separate reviewer date and content nodes retain boundaries', () => {
    const r=run([['div','t***3'],['div','2026-09-01'],['div','很好用']]);
    assert.match(r.body_text_all, /^t\*\*\*3\s+2026-09-01\s+很好用$/);
    assert.equal(r.body_text_all_truncated,false);
  }],
  ['separate specification labels and values retain boundaries', () => {
    const r=run([['div','品牌'],['span','Example'],['div','型号'],['span','K1']]);
    assert.match(r.body_text_all, /^品牌\s+Example\s+型号\s+K1$/);
  }],
  ['separator counts toward exact transfer limit', () => {
    const r=run([['div','x'.repeat(LIMIT-2)],['span','Y']]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.match(r.body_text_all, /x\sY$/);
    assert.equal(r.body_text_all_truncated,false);
  }],
  ['separator cannot push transfer over limit', () => {
    const r=run([['div','x'.repeat(LIMIT-1)],['span','YZ']]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.equal(r.body_text_all_truncated,true);
  }],
  ['empty and excluded tail do not falsely mark truncation', () => {
    const r=run([['div','x'.repeat(LIMIT)],['span',''],['script','ignored'],['template','ignored']]);
    assert.equal(r.body_text_all.length,LIMIT);
    assert.equal(r.body_text_all_truncated,false);
  }],
);
// Exercise the production JD context probe without a browser or website.
const serviceSource = fs.readFileSync(path.join(__dirname, '../jd_taobao_mcp/service.py'), 'utf8');
const helperStart = serviceSource.indexOf('async def _requires_extraction_verification');
const jsStart = serviceSource.indexOf('r"""', helperStart);
const jsEnd = serviceSource.indexOf('"""', jsStart + 4);
function jdContext({title=true, price=true, challenge=false, outside='Product', copy='安全验证', body=true}={}) {
  const visibleNode = {getClientRects:()=>[{}]};
  const removed = new Set();
  const clone = {
    querySelectorAll(selector) {
      for (const needed of ['#detail','#comment','script','style']) assert.ok(selector.includes(needed));
      return [{remove:()=>removed.add('copy')}];
    },
    get innerText() {return outside+(removed.has('copy')?'':copy);}
  };
  const document = {
    querySelector: selector => (selector.includes('#name') ? title : price) ? visibleNode : null,
    querySelectorAll: () => challenge ? [visibleNode] : [],
    body: body ? {cloneNode:()=>clone} : null,
  };
  const fn=vm.runInNewContext('('+serviceSource.slice(jsStart+4,jsEnd)+')',{document},{timeout:1000});
  return fn();
}
cases.push(
  ['JD product review text excluded from page-level context',()=>{
    const r=jdContext(); assert.equal(r.has_product_identity,true);
    assert.equal(r.has_challenge_ui,false); assert.equal(r.outside_product_text,'Product');
  }],
  ['JD product words alone do not establish product identity',()=>{
    assert.equal(jdContext({title:false,price:false,outside:'商品详情 安全验证'}).has_product_identity,false);
  }],
  ['JD visible challenge remains detected over product',()=>{
    assert.equal(jdContext({challenge:true}).has_challenge_ui,true);
  }],
  ['JD verification outside product copy remains available',()=>{
    assert.equal(jdContext({outside:'安全验证'}).outside_product_text,'安全验证');
  }],
  ['JD context transport is bounded',()=>{
    assert.equal(jdContext({outside:'x'.repeat(100000)}).outside_product_text.length,5000);
  }],
  ['JD missing body cannot fabricate context',()=>{
    assert.equal(jdContext({body:false,title:false,price:false}).has_product_identity,false);
  }],
);
let failures=0;
for(const [name,test] of cases) {
  try {test(); console.log('PASS '+name);}
  catch(e){failures++; console.log('FAIL '+name+': '+e.message.slice(0,300));}
}
console.log(JSON.stringify({tests:cases.length,failures,browser_started:false}));
process.exitCode=failures?1:0;
