const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('local-resume-companion-extension/content.js', 'utf8');

function fixture(matches, nativeHook) {
  const sent = [];
  const input = { tagName: 'INPUT', type: 'file', disabled: false, isConnected: true, dispatchEvent(e) { sent.push(e.type); } };
  const target = {requestId:'one', url:'https://example.com/apply', selector:'#resume'};
  const context = vm.createContext({document:{querySelectorAll:()=>matches(input)},location:{href:target.url},
    chrome:{runtime:{async sendMessage(m) {
      sent.push(m);
      if(m.type==='resume-target') return {target};
      if(m.type==='resume-field-ready') { nativeHook?.(input); return {ok:true,fileName:'approved.docx',base64:'YQ=='}; }
    }}}, setInterval(){}, atob:s=>Buffer.from(s,'base64').toString('binary'), Uint8Array,
    File:class {constructor(parts,name){this.name=name;}},
    DataTransfer:class {constructor(){this.files=[];this.items={add:f=>this.files.push(f)};}}, Event:class {constructor(type){this.type=type;}}});
  vm.runInContext(source.replace(/check\(\);\nsetInterval\(check, 1500\);/, ''),context);
  return {context,input,target,sent};
}

test('explicit selector attaches without consulting surrounding text',async()=>{
  const f=fixture(i=>[i]);
  await vm.runInContext('check()',f.context);
  assert.equal(f.input.files[0].name,'approved.docx');
  assert.ok(f.sent.some(m=>m.status==='dispatched'));
  await vm.runInContext('check()',f.context);
  assert.equal(f.sent.filter(m=>m.type==='resume-field-ready').length,1);
});
test('ambiguous or missing explicit selector never falls back or claims bytes',async()=>{
  for(const matches of [()=>[],i=>[i,i]]) {
    const f=fixture(matches); await vm.runInContext('check()',f.context);
    assert.ok(f.sent.some(m=>m.status==='blocked'));
    assert.ok(!f.sent.some(m=>m.type==='resume-field-ready'));
  }
});
test('disabled input rejected',async()=>{
  const f=fixture(i=>[i]); f.input.disabled=true; await vm.runInContext('check()',f.context);
  assert.ok(!f.sent.some(m=>m.type==='resume-field-ready'));
});
test('detached input after native call is not used',async()=>{
  const f=fixture(i=>[i],i=>{i.isConnected=false}); await vm.runInContext('check()',f.context);
  assert.equal(f.input.files,undefined);
  assert.ok(f.sent.some(m=>m.status==='blocked'));
});
test('new request works on same page',async()=>{
  const f=fixture(i=>[i]); await vm.runInContext('check()',f.context);
  f.target.requestId='two'; await vm.runInContext('check()',f.context);
  assert.equal(f.sent.filter(m=>m.type==='resume-field-ready').length,2);
});
test('selector chain enters an unambiguous open shadow root',async()=>{
  const f=fixture(i=>[i]);
  f.target.shadowHosts=['resume-widget'];
  f.context.document.querySelectorAll=()=>[{shadowRoot:{querySelectorAll:()=>[f.input]}}];
  await vm.runInContext('check()',f.context);
  assert.equal(f.input.files[0].name,'approved.docx');
});
test('invalidated extension context stops polling without unhandled rejection',async()=>{
  const f=fixture(i=>[i]);
  let calls=0;
  f.context.chrome.runtime.sendMessage=()=>{ calls++; throw new Error('Extension context invalidated.'); };
  await vm.runInContext('check()',f.context);
  await vm.runInContext('check()',f.context);
  assert.equal(calls,1);
  assert.equal(f.input.files,undefined);
});
