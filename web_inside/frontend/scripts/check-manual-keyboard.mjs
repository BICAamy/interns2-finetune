import fs from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';
import vm from 'node:vm';
const code=ts.transpileModule(fs.readFileSync('src/manualKeyboard.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(code,context);
const {keyDirection,isMotionKey,sameDirection}=context.exports;
const expected=[['KeyW','translation',0,1],['KeyS','translation',0,-1],['KeyA','translation',1,1],['KeyD','translation',1,-1],['KeyR','translation',2,1],['KeyF','translation',2,-1],['KeyI','rotation',0,1],['KeyK','rotation',0,-1],['KeyJ','rotation',1,1],['KeyL','rotation',1,-1],['KeyU','rotation',2,1],['KeyO','rotation',2,-1]];
for(const [key,kind,axis,direction] of expected){assert.ok(isMotionKey(key));assert.equal(JSON.stringify(keyDirection(key,false)),JSON.stringify({kind,axis,direction}));}
for(let i=1;i<=6;i++)for(const shift of [false,true]){assert.equal(JSON.stringify(keyDirection(`Digit${i}`,shift)),JSON.stringify({kind:'joint',axis:i-1,direction:shift?-1:1}));}
for(const key of ['Space','Enter','Digit0','Digit7','KeyZ']){assert.equal(keyDirection(key,false),null);assert.equal(isMotionKey(key),false);}
assert.equal(sameDirection({kind:'joint',axis:0,direction:1},{kind:'joint',axis:0,direction:-1}),false);
console.log('PASS: 24 motion directions, Shift reverse and unmapped-key rejection.');
