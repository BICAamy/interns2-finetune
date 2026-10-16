import fs from 'node:fs';import assert from 'node:assert/strict';import vm from 'node:vm';import ts from 'typescript';
const code=ts.transpileModule(fs.readFileSync('src/jointLabelLayout.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(code,context);
const {containedImageBox,layoutJointLabels}=context.exports;
const box=containedImageBox(800,400,600,600);
assert.equal(JSON.stringify(box),JSON.stringify({left:200,top:0,width:400,height:400}));
assert.equal(containedImageBox(800,400,0,0),null);
const labels=layoutJointLabels(Array.from({length:6},(_,i)=>({joint:i+1,name:`J${i+1}`,x:.5,y:.5})),box,800,400);
assert.equal(labels.length,6);
for(const label of labels){assert.equal(label.x,400);assert.equal(label.y,200);assert.ok(label.left>=0&&label.left+34<=800);assert.ok(label.top>=0&&label.top+22<=400);}
for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){
  const a=labels[i],b=labels[j];assert.ok(!(a.left<b.left+34&&a.left+34>b.left&&a.top<b.top+22&&a.top+22>b.top),'Joint labels overlap');
}
assert.equal(layoutJointLabels([{joint:9,x:.5,y:.5}],box,800,400).length,0);
console.log('PASS: image letterboxing, six coincident joint anchors, bounds and invalid marker rejection.');
