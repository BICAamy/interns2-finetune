export type JointMarker={joint:number;name:string;x:number;y:number};
export type ImageBox={left:number;top:number;width:number;height:number};
export const JOINT_COLORS=["#2563eb","#0891b2","#7c3aed","#d97706","#db2777","#0f766e"];

export function containedImageBox(width:number,height:number,naturalWidth:number,naturalHeight:number):ImageBox|null{
  if(Math.min(width,height,naturalWidth,naturalHeight)<=0)return null;
  const scale=Math.min(width/naturalWidth,height/naturalHeight);
  const w=naturalWidth*scale,h=naturalHeight*scale;
  return {left:(width-w)/2,top:(height-h)/2,width:w,height:h};
}

export function layoutJointLabels(markers:JointMarker[],box:ImageBox,width:number,height:number){
  const placed:{left:number;top:number}[]=[];
  const preferred=[[-48,26],[-48,-30],[-48,-30],[48,26],[48,-30],[48,26]];
  const candidates=[[-48,-30],[48,-30],[-48,26],[48,26],[0,-48],[0,48],[-66,0],[66,0]];
  return markers.filter(m=>Number.isInteger(m.joint)&&m.joint>=1&&m.joint<=6&&Number.isFinite(m.x)&&Number.isFinite(m.y)&&m.x>=0&&m.x<=1&&m.y>=0&&m.y<=1).map(marker=>{
    const x=box.left+marker.x*box.width,y=box.top+marker.y*box.height;
    const wanted=preferred[marker.joint-1];
    const options=[wanted,...candidates].map(([dx,dy])=>{
      const left=Math.max(4,Math.min(width-38,x+dx-17));
      const top=Math.max(4,Math.min(height-26,y+dy-11));
      const overlaps=placed.filter(p=>left<p.left+38&&left+38>p.left&&top<p.top+26&&top+26>p.top).length;
      return {left,top,score:overlaps*100000+Math.hypot(left+17-x-wanted[0],top+11-y-wanted[1])};
    }).sort((a,b)=>a.score-b.score);
    const position=options[0];placed.push(position);
    return {...marker,x,y,left:position.left,top:position.top,color:JOINT_COLORS[marker.joint-1]};
  });
}
