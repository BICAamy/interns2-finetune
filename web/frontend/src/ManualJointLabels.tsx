import {useEffect,useState} from "react";
import {createPortal} from "react-dom";
import {containedImageBox,layoutJointLabels} from "./jointLabelLayout";
import type {ImageBox,JointMarker} from "./jointLabelLayout";

export default function ManualJointLabels({sessionId,activeJoint}:{sessionId:string;activeJoint:number|null}){
  const [stage,setStage]=useState<HTMLElement|null>(null),[markers,setMarkers]=useState<JointMarker[]>([]);
  const [geometry,setGeometry]=useState<{width:number;height:number;box:ImageBox}|null>(null);
  useEffect(()=>{
    const node=document.querySelector<HTMLElement>(".video-stage");if(!node)return;
    setStage(node);let disposed=false;let timer:number|undefined;let pending=false;
    const resize=()=>{
      const image=node.querySelector("img");if(!image){setGeometry(null);return;}
      const stageRect=node.getBoundingClientRect(),imageRect=image.getBoundingClientRect();
      const box=containedImageBox(imageRect.width,imageRect.height,image.naturalWidth,image.naturalHeight);
      if(!box){setGeometry(null);return;}
      box.left+=imageRect.left-stageRect.left;box.top+=imageRect.top-stageRect.top;
      setGeometry({width:stageRect.width,height:stageRect.height,box});
    };
    const observer=new ResizeObserver(resize);observer.observe(node);
    const poll=async()=>{
      if(pending)return;pending=true;
      try{
        const response=await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/manual/joint-labels`,{cache:"no-store",signal:AbortSignal.timeout(1200)});
        const data=await response.json();if(!disposed){setMarkers(response.ok&&data.available&&Array.isArray(data.labels)?data.labels:[]);resize();}
      }catch{if(!disposed)setMarkers([]);}
      finally{pending=false;if(!disposed)timer=window.setTimeout(()=>void poll(),120);}
    };
    void poll();return()=>{disposed=true;if(timer)window.clearTimeout(timer);observer.disconnect();};
  },[sessionId]);
  if(!stage||!geometry||markers.length===0)return null;
  const labels=layoutJointLabels(markers,geometry.box,geometry.width,geometry.height);
  return createPortal(<svg className="manual-joint-overlay" width={geometry.width} height={geometry.height}
    viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" aria-label="J1 至 J6 关节转轴位置标注">
    {labels.map(label=><g key={label.joint} className={activeJoint===label.joint?"is-active":""}>
      <title>{label.name} 转轴中心</title>
      <line x1={label.x} y1={label.y} x2={label.left+17} y2={label.top+11} stroke="white" strokeWidth="4"/>
      <line x1={label.x} y1={label.y} x2={label.left+17} y2={label.top+11} stroke={label.color} strokeWidth={activeJoint===label.joint?3:1.5}/>
      <circle cx={label.x} cy={label.y} r={activeJoint===label.joint?4:2.5} fill={label.color} stroke="white" strokeWidth="1.5"/>
      <rect x={label.left} y={label.top} width="34" height="22" rx="6" fill={activeJoint===label.joint?label.color:"rgba(255,255,255,.9)"} stroke={label.color} strokeWidth={activeJoint===label.joint?2:1}/>
      <text x={label.left+17} y={label.top+15} textAnchor="middle" fill={activeJoint===label.joint?"white":label.color}>{label.name}</text>
    </g>)}
  </svg>,stage);
}
