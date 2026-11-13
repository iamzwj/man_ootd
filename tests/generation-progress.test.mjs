import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../personal.js',import.meta.url),'utf8').replace('export function initPersonal','function initPersonal');
const create=vm.runInNewContext(source+'\ncreateWorkProgress');
const job=(id,status,slots)=>({id,kind:'same',status,slots});
const waiting=()=>[{key:'1',status:'queued'},{key:'2',status:'queued'}];

test('historical results are quiet; active jobs restore after refresh',()=>{
 const tracker=create();tracker.observe([job('old','succeeded',[{asset:'/old'}])]);assert.equal(tracker.snapshot(),null);
 tracker.observe([job('new','running',waiting())]);assert.equal(tracker.snapshot().total,2);assert.equal(tracker.snapshot().done,0);
});
test('concurrent jobs retain a stable four-image denominator through partial failure filtering',()=>{
 const tracker=create();tracker.track(job('a','queued',waiting()));tracker.track(job('b','queued',waiting()));
 tracker.observe([job('a','succeeded',[{asset:'/1'},{asset:'/2'}]),job('b','running',waiting())]);
 assert.equal(tracker.snapshot().done,2);assert.equal(tracker.snapshot().total,4);assert.equal(tracker.snapshot().status,'running');
 tracker.observe([job('a','succeeded',[{asset:'/1'},{asset:'/2'}]),job('b','partial',[{asset:'/3'}])]);
 assert.equal(tracker.snapshot().total,4);assert.equal(tracker.snapshot().success,3);assert.equal(tracker.snapshot().failed,1);assert.equal(tracker.snapshot().status,'partial');
});
test('failed tasks removed by the server complete the notice instead of leaving it stuck',()=>{
 const tracker=create();tracker.track(job('failed','queued',waiting()));tracker.observe([]);
 assert.equal(tracker.snapshot().failed,2);assert.equal(tracker.snapshot().status,'failed');
 tracker.dismiss();tracker.observe([]);assert.equal(tracker.snapshot(),null);
 tracker.track(job('next','queued',waiting()));assert.equal(tracker.snapshot().total,2);
});
test('unknown submissions stay explicit and normal refresh does not repeat dismissed completion',()=>{
 const tracker=create();tracker.track(job('unknown','queued',waiting()));
 tracker.observe([job('unknown','uncertain',[{status:'uncertain'},{status:'uncertain'}])]);assert.equal(tracker.snapshot().status,'uncertain');assert.equal(tracker.snapshot().done,0);
 tracker.dismiss();tracker.observe([job('unknown','uncertain',[{status:'uncertain'},{status:'uncertain'}])]);assert.equal(tracker.snapshot(),null);
 tracker.track(job('next','queued',waiting()));assert.equal(tracker.snapshot().status,'running');assert.equal(tracker.snapshot().total,2);
 tracker.reset();assert.equal(tracker.snapshot(),null);
});

test('failed and uncertain slots disappear while successful and active slots remain',()=>{
 const visible=vm.runInNewContext(source+'\nvisibleSlot');
 const slots=[{status:'failed'},{status:'uncertain'},{status:'running'},{asset:'/image'}];
 assert.deepEqual(slots.map(s=>visible(job('a','running',slots),s)),[false,false,true,true]);
 assert.deepEqual(slots.map(s=>visible(job('a','partial',slots),s)),[false,false,false,true]);
 const tracker=create();
 tracker.observe([job('old','uncertain',[slots[1]])]);
 assert.equal(tracker.snapshot(),null);
});
