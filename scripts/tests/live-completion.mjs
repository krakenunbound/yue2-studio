import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';
const source=fs.readFileSync('src/LivePage.tsx','utf8').replace(/\r\n/g,'\n');
const start=source.indexOf('  useEffect(() => {\n    if (!on || !job');
const end=source.indexOf('  async function writeSong',start);
assert.ok(start>0&&end>start);
const effect=ts.transpile(source.slice(start,end),{target:ts.ScriptTarget.ES2022});
function fixture(code=effect){let deps,cleanup,timer;let next;const added=new Set();const errors=[];const song={id:'done',folder_name:'done',title:'Finished song'};
 const scope={on:true,job:{id:'job',kind:'yue2',status:'running',progress:.97925},liveEpochRef:{current:0},submitting:{current:true},
 window:{setInterval(fn){timer=fn;return 1},clearInterval(){timer=null}},
 useEffect(fn,newDeps){if(!deps||newDeps.some((x,i)=>x!==deps[i])){cleanup?.();deps=newDeps;cleanup=fn()}},
 getJob:async()=>({job:next}),getLibrary:async()=>({items:[song]}),
 setGeneratedIds(fn){for(const id of fn(added))added.add(id)},setQueue(fn){scope.queue=fn(scope.queue)},queue:[],
 setActivePick(value){scope.active=value},active:{id:'pick'},setError(error){errors.push(error)},
 setJob(value){scope.job=value;render()},onRefresh:null,refreshRef:{current:null}};
 vm.createContext(scope);const render=()=>vm.runInContext(code,scope);
 const refreshed=async()=>{scope.onRefresh=async()=>{};scope.refreshRef.current=scope.onRefresh;render();await Promise.resolve()};
 scope.onRefresh=refreshed;scope.refreshRef.current=refreshed;render();
 return {scope,added,errors,render,setNext:value=>next=value,tick:()=>timer()};
}
const test=fixture();test.setNext({id:'job',kind:'yue2',status:'succeeded',progress:1,result:{folder_name:'done'}});await test.tick();
assert.equal(test.scope.job.status,'succeeded','parent refresh must not cancel terminal publication');
assert.equal(test.scope.job.progress,1);assert.ok(test.added.has('done'));assert.deepEqual([...test.scope.queue],['done']);assert.equal(test.scope.submitting.current,false);
const stopped=fixture();stopped.scope.refreshRef.current=async()=>{stopped.scope.liveEpochRef.current++};stopped.setNext({id:'job',kind:'yue2',status:'succeeded',result:{folder_name:'done'}});await stopped.tick();assert.equal(stopped.added.size,0,'Stop invalidates late completion');
console.log('PASS: parent refresh rerender publishes completion, adds song once, releases next generation; Stop rejects late completion');


const before=effect.replace('await refreshRef.current()', 'await onRefresh()').replace('[on, job?.id, job?.status]', '[on, job?.id, job?.status, onRefresh]');
assert.notEqual(before,effect);
const broken=fixture(before);broken.setNext({id:'job',kind:'yue2',status:'succeeded',progress:1,result:{folder_name:'done'}});await broken.tick();
assert.equal(broken.scope.job.progress,.97925,'negative control reproduces original 98% freeze');
assert.equal(broken.added.size,0);
console.log('PASS: same test reproduces old 98% freeze without the fix');
