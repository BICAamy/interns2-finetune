import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { SimulationTelemetry } from "./types";
import { isMotionKey, keyDirection, sameDirection } from "./manualKeyboard";
import type { ManualDirection, ManualKind } from "./manualKeyboard";
import "./ManualControl.css";
import {JOINT_COLORS} from "./jointLabelLayout";

type Status = {
  available:boolean; mode:string; reason:string; occupied:boolean; owned_by_session:boolean;
  moving:boolean; stopping:boolean; fault:string|null;
  limits:{translation_step:number;rotation_step:number;translation_speed:number;angular_speed:number};
};
async function request(session:string,path:string,body?:object):Promise<Status & {token?:string}> {
  const abort=new AbortController(); const timer=window.setTimeout(()=>abort.abort(),3000);
  try {
    const response=await fetch(`/api/sessions/${encodeURIComponent(session)}/manual${path}`,{
      method:body===undefined?"GET":"POST", cache:"no-store", signal:abort.signal,
      headers:{"Content-Type":"application/json"}, body:body===undefined?undefined:JSON.stringify(body),
    });
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:data.message??`请求失败 (${response.status})`);
    return data;
  } finally {window.clearTimeout(timer);}
}

export default function ManualControl({sessionId,runtimeMode,telemetry}:{
  sessionId:string|null;runtimeMode:"real"|"simulation";telemetry:SimulationTelemetry|null;
}) {
  const [open,setOpen]=useState(false),[status,setStatus]=useState<Status|null>(null);
  const [owner,setOwner]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [active,setActive]=useState<ManualDirection|null>(null);
  const [step,setStep]=useState(10),[angle,setAngle]=useState(10),[speed,setSpeed]=useState(1);
  const [keyboardReady,setKeyboardReady]=useState(false);
  const token=useRef<string|null>(null),sequence=useRef(0),held=useRef<ManualDirection|null>(null);
  const source=useRef<"keyboard"|"pointer"|null>(null),keys=useRef(new Set<string>()),blocked=useRef(false);
  const settings=useRef({step,angle,speed});settings.current={step,angle,speed};
  const fab=useRef<HTMLButtonElement|null>(null),drawer=useRef<HTMLElement|null>(null);
  const failed=useRef(false),alive=useRef(true);
  const usable=owner&&status?.available&&!status.fault&&!status.stopping&&!busy&&!failed.current;
  const closePanel=()=>{setOpen(false);window.requestAnimationFrame(()=>fab.current?.focus());};

  const send=async(direction:ManualDirection|null)=>{
    const current=token.current;if(!sessionId||!current)return;
    const id=++sequence.current;
    try {
      const config=settings.current;
      const data=await request(sessionId,"/input",{token:current,sequence:id,
        kind:direction?.kind??null,axis:direction?.axis??0,direction:direction?.direction??1,
        amount:direction?.kind==="translation"?config.step:config.angle,speed_scale:config.speed,continuous:true});
      if(alive.current&&token.current===current&&id===sequence.current)setStatus(data);
    } catch(err) {
      if(!alive.current||token.current!==current||id!==sequence.current)return;
      failed.current=true;held.current=null;source.current=null;keys.current.clear();
      setActive(null);setKeyboardReady(false);setError(err instanceof Error?err.message:String(err));
    }
  };
  const stop=()=>{
    held.current=null;source.current=null;keys.current.clear();blocked.current=false;
    setActive(null);setKeyboardReady(false);void send(null);
  };
  const release=async(close=false)=>{
    held.current=null;source.current=null;keys.current.clear();setActive(null);setKeyboardReady(false);
    if(!sessionId||!token.current){if(close)closePanel();return;}
    setBusy(true);const current=token.current;
    try {
      await send(null);
      const data=await request(sessionId,"/release",{token:current});
      token.current=null;setOwner(false);setStatus(data);failed.current=false;setError("");
      if(close)closePanel();
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  };
  const acquire=async()=>{
    if(!sessionId)return;setBusy(true);setError("");
    try{
      const data=await request(sessionId,"/acquire",{});
      if(!data.token)throw new Error("服务未返回控制令牌");
      token.current=data.token;sequence.current=0;failed.current=false;setOwner(true);setStatus(data);
      drawer.current?.focus();
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  };
  const start=(direction:ManualDirection,origin:"pointer"|"keyboard")=>{
    if(!usable)return;
    if(held.current&&!sameDirection(held.current,direction)){stop();setError("请先松开当前方向，再改变运动方向");return;}
    if(held.current&&source.current!==origin){stop();setError("请先松开鼠标或键盘，再切换操作方式");return;}
    held.current=direction;source.current=origin;setActive(direction);setError("");void send(direction);
  };

  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    if(status){setStep(value=>Math.min(value,status.limits.translation_step));setAngle(value=>Math.min(value,status.limits.rotation_step));}
  },[status?.limits.translation_step,status?.limits.rotation_step]);
  useEffect(()=>{
    setOwner(false);setStatus(null);setActive(null);setError("");setKeyboardReady(false);
    failed.current=false;keys.current.clear();held.current=null;source.current=null;
  },[sessionId,runtimeMode]);
  useEffect(()=>{
    if(!open||!sessionId)return;
    let disposed=false;
    const update=async()=>{const before=token.current;try{
      const data=await request(sessionId,"");if(!disposed){setStatus(data);
        if(before&&token.current===before&&!data.occupied){token.current=null;held.current=null;keys.current.clear();setOwner(false);setActive(null);setKeyboardReady(false);}}
    }catch(err){if(!disposed)setError(err instanceof Error?err.message:String(err));}};
    void update();const poll=window.setInterval(()=>void update(),600);
    return()=>{disposed=true;window.clearInterval(poll);};
  },[open,sessionId,runtimeMode]);

  useEffect(()=>{
    if(!owner||!sessionId)return;
    let disposed=false,heartBusy=false;
    const beat=async()=>{
      const current=token.current;if(!current||heartBusy)return;heartBusy=true;
      try{const data=await request(sessionId,"/heartbeat",{token:current});
        if(!disposed&&token.current===current)setStatus(data);
      }catch(err){if(!disposed){failed.current=true;stop();setError(err instanceof Error?err.message:String(err));}}
      finally{heartBusy=false;}
    };
    const heartbeat=window.setInterval(()=>void beat(),250);
    const movement=window.setInterval(()=>{if(held.current&&!failed.current)void send(held.current);},140);
    return()=>{disposed=true;window.clearInterval(heartbeat);window.clearInterval(movement);};
  },[owner,sessionId]);

  useEffect(()=>{
    if(!open)return;
    const typing=(target:EventTarget|null)=>target instanceof HTMLElement&&Boolean(target.closest("input,textarea,select,[contenteditable=true]"));
    const keyboard=(event:KeyboardEvent,down:boolean)=>{
      const code=event.code;
      if(event.ctrlKey||event.altKey||event.metaKey){if(held.current)stop();return;}
      if(code==="Escape"&&down){event.preventDefault();stop();return;}
      if(typing(event.target)){if(held.current)stop();return;}
      if(code!=="Space"&&!isMotionKey(code)&&!code.startsWith("Shift"))return;
      if(!owner||!usable)return;
      event.preventDefault();
      if(event.repeat)return;
      if(down)keys.current.add(code);else keys.current.delete(code);
      const motion=[...keys.current].filter(isMotionKey);
      if(motion.length===0)blocked.current=false;
      if(motion.length>1){blocked.current=true;held.current=null;source.current=null;setActive(null);void send(null);setError("一次只控制一个方向，请松开按键后重试");return;}
      const space=keys.current.has("Space");setKeyboardReady(space);
      if(!space||blocked.current||motion.length===0){if(source.current==="keyboard"){held.current=null;source.current=null;setActive(null);void send(null);}return;}
      const direction=keyDirection(motion[0],event.shiftKey);
      if(direction){if(held.current&&!sameDirection(held.current,direction)){blocked.current=true;held.current=null;source.current=null;setActive(null);void send(null);setError("改变正负方向前请松开按键");return;}
        if(!held.current)start(direction,"keyboard");}
    };
    const down=(e:KeyboardEvent)=>keyboard(e,true),up=(e:KeyboardEvent)=>keyboard(e,false);
    const blur=()=>stop(),hidden=()=>{if(document.hidden)stop();};
    const focus=(e:FocusEvent)=>{if(typing(e.target))stop();};
    window.addEventListener("keydown",down,true);window.addEventListener("keyup",up,true);
    window.addEventListener("blur",blur);document.addEventListener("visibilitychange",hidden);document.addEventListener("focusin",focus);
    return()=>{window.removeEventListener("keydown",down,true);window.removeEventListener("keyup",up,true);
      window.removeEventListener("blur",blur);document.removeEventListener("visibilitychange",hidden);document.removeEventListener("focusin",focus);};
  },[open,owner,usable,sessionId]);

  useEffect(()=>()=>{
    const current=token.current;token.current=null;held.current=null;
    if(current&&sessionId)void fetch(`/api/sessions/${sessionId}/manual/release`,{method:"POST",keepalive:true,
      headers:{"Content-Type":"application/json"},body:JSON.stringify({token:current})}).catch(()=>{});
  },[sessionId,runtimeMode]);

  const directionButton=(kind:ManualKind,axis:number,direction:-1|1,label:string,key:string)=>{
    const value:ManualDirection={kind,axis,direction};
    const down=(event:PointerEvent<HTMLButtonElement>)=>{
      if(event.button!==0||!usable)return;event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);start(value,"pointer");
    };
    return <button key={`${kind}-${axis}-${direction}`} type="button" className={`manual-direction ${sameDirection(active,value)?"is-active":""}`}
      disabled={!usable} data-manual-direction={`${kind}-${axis}-${direction}`}
      aria-label={`${kind==="joint"?`J${axis+1}`:kind==="rotation"?["Rx","Ry","Rz"][axis]:["X","Y","Z"][axis]} ${direction===1?"正向":"反向"}，按住移动，松开停止`} onPointerDown={down}
      onPointerUp={()=>{if(source.current==="pointer")stop();}} onPointerCancel={stop}
      onLostPointerCapture={()=>{if(source.current==="pointer")stop();}}>
      <strong>{label}</strong><kbd>{key}</kbd></button>;
  };
  const xy=(axis:number,direction:-1|1,label:string,key:string)=>directionButton("translation",axis,direction,label,key);
  const options=(max:number)=>[.1,.5,1,2,5,10,20].filter(v=>v<=max);
  const point=telemetry?.actual_tcp_robot_base?.translation_mm??(telemetry?.current_tcp?[telemetry.current_tcp.x,telemetry.current_tcp.y,telemetry.current_tcp.z]:null);
  return <>
    {!open&&<button ref={fab} type="button" className="manual-fab" aria-label="🎮 手动控制" aria-expanded={false} aria-controls="manual-control-drawer"
      onClick={()=>{setOpen(true);setError("");}}>
      <span aria-hidden="true">🎮</span><strong>手动控制</strong>
    </button>}
    {open&&<aside className="manual-drawer" id="manual-control-drawer" aria-label="手动控制面板" tabIndex={-1} ref={drawer}>
      <div className="manual-header"><div><span>DIRECT CONTROL</span><h2>手动控制</h2></div>
        <span className="manual-mode">{runtimeMode==="simulation"?"仿真":"真机"}</span>
        <button type="button" className="manual-close" aria-label="关闭手动控制" onClick={()=>void release(true)}>×</button></div>
      <div className="manual-ownership">
        <span role="status">{status?.stopping?"正在停止":status?.fault?"操作已暂停":owner?(status?.moving?"点动中":"已接管，等待操作"):status?.occupied?"其他页面正在控制":"未接管"}</span>
        {owner?<button type="button" disabled={busy} onClick={()=>void release(true)}>退出控制</button>:
          <button type="button" disabled={!sessionId||busy||!status?.available||status.occupied} onClick={()=>void acquire()}>{busy?"正在连接…":"接管手动控制"}</button>}
      </div>
      {status&&!status.available&&<div className="manual-notice">{status.reason}</div>}
      {(error||status?.fault)&&<div className="manual-error" role="alert">{error||status?.fault}</div>}
      <div className="manual-scroll">
        <section className="manual-section"><div className="manual-section-title"><h3>XYZ 平移</h3><span>Base · mm</span></div>
          <div className="manual-translation"><div className="manual-pad">
            <div className="manual-north">{xy(1,1,"Y＋","W")}</div>
            <div className="manual-west">{xy(0,-1,"X－","A")}</div><span className="manual-pad-center">XY</span>
            <div className="manual-east">{xy(0,1,"X＋","D")}</div><div className="manual-south">{xy(1,-1,"Y－","S")}</div>
          </div><div className="manual-z">{xy(2,1,"Z＋","R")}{xy(2,-1,"Z－","F")}</div></div>
        </section>
        <section className="manual-section"><div className="manual-section-title"><h3>姿态调整</h3><span>Base RPY · °</span></div>
          <div className="manual-pairs">{["Rx","Ry","Rz"].map((label,axis)=><div className="manual-pair" key={label}>
            <span>{label}</span>{directionButton("rotation",axis,-1,"－",["K","L","O"][axis])}{directionButton("rotation",axis,1,"＋",["I","J","U"][axis])}
          </div>)}</div>
        </section>
        <section className="manual-section"><div className="manual-section-title"><h3>六关节运动</h3><span>Shift ＋ 数字：反向</span></div>
          <div className="manual-joints">{Array.from({length:6},(_,axis)=><div className="manual-pair" key={axis}>
            <span><b className="manual-joint-name"><i style={{background:JOINT_COLORS[axis]}}/>J{axis+1}</b><small>{telemetry?.joint_positions_deg?.[axis]?.toFixed(1)??"—"}°</small></span>
            {directionButton("joint",axis,-1,"－",`⇧${axis+1}`)}{directionButton("joint",axis,1,"＋",`${axis+1}`)}
          </div>)}</div>
        </section>
        <section className="manual-settings">
          <label>平移步长 <select value={step} disabled={Boolean(active)} onChange={e=>setStep(Number(e.target.value))}>{options(status?.limits.translation_step??20).map(v=><option key={v} value={v}>{v} mm</option>)}</select></label>
          <label>角度步长 <select value={angle} disabled={Boolean(active)} onChange={e=>setAngle(Number(e.target.value))}>{options(status?.limits.rotation_step??20).map(v=><option key={v} value={v}>{v}°</option>)}</select></label>
          <label className="manual-speed">速度比例 <strong>{Math.round(speed*100)}%</strong><input aria-label="手动速度比例" type="range" min="0.1" max="1" step="0.05" value={speed} disabled={Boolean(active)} onChange={e=>setSpeed(Number(e.target.value))}/></label>
        </section>
        <div className="manual-position">{point?point.map((value,index)=><span key={index}>{["X","Y","Z"][index]} <b>{value.toFixed(2)}</b> mm</span>):"正在读取实际位置"}</div>
      </div>
      <div className="manual-footer"><p className={keyboardReady?"is-ready":""}>按住 <kbd>Space</kbd> ＋ 方向键；鼠标按住按钮移动，松开停止</p>
        <button type="button" className="manual-stop" disabled={!owner||busy} onClick={stop}>■ 停止手动运动</button>
        <small>手动与文本任务互斥 · 不经过模型解析</small></div>
    </aside>}
  </>;
}
