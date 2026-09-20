import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';
const moduleSource=fs.readFileSync('src/orbitAudio.ts','utf8');
const mod={exports:{}};
vm.runInNewContext(ts.transpile(moduleSource,{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}),{exports:mod.exports,Float32Array,Math,Number});
const {measureOrbitAudio,followAudio}=mod.exports;
const spectrum=new Float32Array(512).fill(-Infinity);spectrum[2]=-12;
const loud=measureOrbitAudio(spectrum,new Float32Array(1024).fill(.5),48000);
const quiet=measureOrbitAudio(spectrum,new Float32Array(1024).fill(.05),48000);
assert.ok(Math.abs(loud.low/quiet.low-10)<1e-6,'10x audio amplitude must give 10x bass drive');
assert.equal(measureOrbitAudio(spectrum,new Float32Array(1024),48000).low,0,'silence wins over stale FFT');
for(const [bin,band] of [[2,'low'],[21,'mid'],[128,'high']]){spectrum.fill(-Infinity);spectrum[bin]=-12;const result=measureOrbitAudio(spectrum,new Float32Array(1024).fill(.1),48000);assert.equal(result[band],result.rms);}
const follow=(fps)=>{let n=0;for(let i=0;i<fps;i++)n=followAudio(n,.5,1/fps);for(let i=0;i<fps/2;i++)n=followAudio(n,0,1/fps);return n;};
assert.ok(Math.abs(follow(30)-follow(120))<1e-10,'envelope is refresh-rate independent');
const source=fs.readFileSync('src/OrbitGalaxy.tsx','utf8');
const start=source.indexOf('    let freqData');
const end=source.indexOf('    const updateCore',start);
const record=source.slice(source.indexOf('    const recordWave'),source.indexOf('    const frame'));
const audio={frequencyBinCount:512,fftSize:1024,context:{sampleRate:48000,state:'running',currentTime:0},
 amplitude:0,getByteFrequencyData(d){d.fill(0)},getFloatFrequencyData(d){d.fill(-Infinity);d[2]=-12},getFloatTimeDomainData(d){d.fill(this.amplitude)}};
const scope={analyserRef:{current:audio},playingRef:{current:'song'},MUSIC_WAVE_HISTORY:360,MUSIC_WAVE_RATE:60,measureOrbitAudio,followAudio};vm.createContext(scope);
vm.runInContext(ts.transpile(source.slice(start,end)+record+'\nglobalThis.step=()=>{stepAudio();return {bassDrive,history:Array.from(bassHistory),waveWrite};};',{target:ts.ScriptTarget.ES2022}),scope);
for(let i=0;i<60;i++){audio.context.currentTime+=1/60;assert.equal(scope.step().bassDrive,0);}
audio.amplitude=.5; audio.context.currentTime+=1/60;assert.ok(scope.step().bassDrive>.3);
scope.playingRef.current=null;assert.ok(scope.step().history.every(x=>x===0));
scope.playingRef.current='new';audio.amplitude=0;assert.equal(scope.step().bassDrive,0);
audio.context.currentTime+=2;assert.ok(scope.step().history.every(x=>x===0),'throttled render must clear old history');
const ringLoop=source.slice(source.indexOf('      for (const ring of rings) {',source.indexOf('    const frame')),source.indexOf('      hub.scale',source.indexOf('    const frame')));
const ringScope={rings:[2.2,3.12,4.04,5].map(radius=>({radius,bandIndex:0,speed:.05,angle:0,lift:0,mesh:{rotation:{y:0},position:{y:0}}})),bandMid:0,bandHigh:0,wasPlaying:true,delta:1/60,MUSIC_WAVE_HISTORY:360,MUSIC_WAVE_RATE:60,MUSIC_WAVE_SPEED:3.15*(.92/.18),MUSIC_SCENE_SCALE:.92/.18,INNER_RING:2.2,RING_GAP:.92,waveWrite:1,bassHistory:new Float32Array(360),midHistory:new Float32Array(360),highHistory:new Float32Array(360),presenceHistory:new Float32Array(360),followAudio};
for(const key of ['hubRing','ringGroup','orbitalGroup','starfield']) ringScope[key]={rotation:{x:0,y:0,z:0}};
vm.createContext(ringScope);ringScope.bassHistory[0]=.5;vm.runInContext(ringLoop,ringScope);assert.ok(ringScope.rings[0].lift>0);assert.equal(ringScope.rings[1].lift,0);
ringScope.waveWrite=4;vm.runInContext(ringLoop,ringScope);assert.ok(ringScope.rings[1].lift>0);
ringScope.waveWrite=11;vm.runInContext(ringLoop,ringScope);assert.ok(ringScope.rings[3].lift>0,'outermost visible ring must respond');
assert.ok(!source.includes('Math.sin(time * 0.007)'));
assert.ok(source.includes('controls.autoRotate = true'));
assert.ok(source.includes('orbitalGroup.rotation.x +='));
ringScope.wasPlaying=false;ringScope.bassHistory.fill(0);
for(const ring of ringScope.rings) ring.lift=0;
const oldAngle=ringScope.rings[0].angle;vm.runInContext(ringLoop,ringScope);
assert.ok(ringScope.rings[0].angle>oldAngle,'ambient ring rotation continues without sound');
assert.ok(ringScope.rings.every(r=>r.lift===0),'ambient rotation never creates audio lift');
assert.ok(ringScope.orbitalGroup.rotation.x>0 && ringScope.ringGroup.rotation.y>0,'scene orbit is restored');
console.log('PASS: linear quiet/loud amplitude, frequency bands, silence, 30/120fps, pause, track change, throttling, outward propagation, outer rings, ambient orbit preserved without synthetic audio lift');


// Compare the three-dimensional orbit to the working source, not just a spin flag.
const original=fs.readFileSync('F:/Orbitwave/app.js','utf8');
for(const axis of ['x','y','z']) {
 const getRate=text=>Number(text.match(new RegExp('orbitalGroup\\.rotation\\.'+axis+' \\+= (?:delta|dt) \\* ([0-9.]+)'))[1]);
 assert.equal(getRate(source),getRate(original),axis+' turnover rate matches original');
}
assert.equal(source.match(/controls.autoRotateSpeed = ([0-9.]+)/)[1],original.match(/controls.autoRotateSpeed = ([0-9.]+)/)[1]);
const THREE=await import('three');
const originalNormal=new THREE.Vector3(0,1,0);
const facing=[];
for(let seconds=0;seconds<=360;seconds+=1){
 const normal=originalNormal.clone().applyEuler(new THREE.Euler(seconds*.018,seconds*.006,seconds*.009));
 const view=new THREE.Vector3(0,22.3,13.8).normalize().applyAxisAngle(new THREE.Vector3(0,1,0),-seconds*Math.PI*2/60*.25);
 facing.push(normal.dot(view));
}
assert.ok(Math.min(...facing)<-.5 && Math.max(...facing)>.5,'orbit must show front, edge and underside');
console.log('PASS: original 3-axis turnover and camera orbit rates; front/edge/underside views');
