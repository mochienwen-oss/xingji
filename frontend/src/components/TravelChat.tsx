import React, { useEffect, useMemo, useRef, useState } from "react";
import { streamAssistant, streamPlanningChat, type AgentEvent } from "../lib/agent";
import type { ChatMessage, Day, Place, PlanRequest, Stop, Trip } from "../types/trip";
import { SuggestionDiff } from "./SuggestionDiff";
import { PlaceSuggestions, type PlaceMatch } from "./PlaceSuggestions";

type Props = {
  form: PlanRequest;
  setForm?: React.Dispatch<React.SetStateAction<PlanRequest>>;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  trip?: Trip;
  dirty?: boolean;
  onSuggestion?: (days: Day[], backlog: Stop[]) => void;
  onVersion?: (version: number) => void;
  onGenerate?: (form?:PlanRequest,messages?:ChatMessage[]) => void;
  generating?: boolean;
  collectedIds?: string[];
  onCollect?: (place:Place) => string;
  compact?: boolean;
  /** agent 生命感事件出口：pin/day_done/route_seg 供地图与总览实时呈现（B/C 类在上层消费）。 */
  onAgentEvent?: (event: AgentEvent) => void;
  onAgentPreviewClear?: () => void;
  onRefreshTrip?: () => Promise<boolean>;
  onUndo?: () => void;
  /** 完成类滑入通知（B 类在场痕迹）：建议就绪/应用/撤销由组件内部触发。 */
  onNotify?: (text: string) => void;
};

const StarIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path className="star-main" d="M9.5 3.5c.7 4.6 2.4 6.3 7 7-4.6.7-6.3 2.4-7 7-.7-4.6-2.4-6.3-7-7 4.6-.7 6.3-2.4 7-7Z"/><path className="star-small" d="M18.5 2c.3 2.1 1.1 2.9 3.2 3.2-2.1.3-2.9 1.1-3.2 3.2-.3-2.1-1.1-2.9-3.2-3.2 2.1-.3 2.9-1.1 3.2-3.2Z"/></svg>;
const SendIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4.2 21 12 3 19.8l1.7-6.1L14 12l-9.3-1.7L3 4.2Z"/></svg>;

/** 共享类型没有 id，用「角色 + 内容 + 同内容序号」派生稳定 key，避免索引复用错节点。 */
function messageKeys(list: ChatMessage[]) {
  const seen = new Map<string, number>();
  return list.map(item => {
    const base = `${item.role}:${item.content}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return `${count}:${base}`;
  });
}

export function TravelChat({form, setForm, messages, setMessages, trip, dirty, onSuggestion, onVersion, onGenerate, generating, collectedIds=[], onCollect, compact=false, onAgentEvent, onAgentPreviewClear, onRefreshTrip, onUndo, onNotify}: Props) {
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded,setExpanded] = useState(false);
  const [error, setError] = useState('');
  const [needsRefresh,setNeedsRefresh] = useState(false);
  const [suggestion, setSuggestion] = useState<{days:Day[];backlog:Stop[]} | null>(null);
  const [places,setPlaces] = useState<PlaceMatch[]>([]), [placesCity,setPlacesCity] = useState(''), [placeNotice,setPlaceNotice] = useState('');
  const [statusText, setStatusText] = useState('');
  const [streamingText,setStreamingText]=useState('');
  const [streaming,setStreaming]=useState(false);
  const [stopped,setStopped]=useState(false);
  const [liveStatus,setLiveStatus]=useState('');
  const end = useRef<HTMLDivElement>(null);
  const pending = useRef<{content:string;next:ChatMessage[]}|null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const request = useRef<AbortController | null>(null);
  const cancelStream = useRef<(() => void) | null>(null);
  /** 流式正文先写 ref，每帧最多 setState 一次，避免逐 token 重渲染。 */
  const streamText = useRef('');
  const streamFrame = useRef(0);
  const lastPrompt = useRef('');
  const generateAnimation = useRef<Animation | null>(null);
  const generateAction = useRef(onGenerate), generationBlocked = useRef(false);
  generateAction.current=onGenerate;generationBlocked.current=!!generating||busy||!form.city.trim();
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  /** finish 闭包持提交时刻的回调；tripRef 保证读取最新行程（多智能体审查 P1 修复）。 */
  const tripRef = useRef(trip);
  tripRef.current = trip;
  useEffect(() => {
    if (!compact) { end.current?.scrollIntoView({block:'nearest'}); return; }
    if (!expanded) return;
    const box = messagesRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [messages, busy, compact, expanded, statusText, streamingText]);
  useEffect(() => {
    if (!compact || !expanded) return;
    const close = (event: KeyboardEvent) => { if (event.isComposing || event.key !== 'Escape') return; setExpanded(false); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [compact, expanded]);
  useEffect(() => () => {request.current?.abort();cancelStream.current?.();generateAnimation.current?.cancel();if(streamFrame.current)window.cancelAnimationFrame(streamFrame.current)}, []);
  useEffect(() => { if (dirty) {setSuggestion(null);onAgentPreviewClear?.()} }, [dirty]);

  function flushStream(){streamFrame.current=0;setStreamingText(streamText.current)}
  function pushStream(text:string){streamText.current+=text;if(!streamFrame.current)streamFrame.current=window.requestAnimationFrame(flushStream)}
  function resetStream(text:string){streamText.current=text;if(streamFrame.current){window.cancelAnimationFrame(streamFrame.current);streamFrame.current=0}setStreamingText(text)}
  function clearStream(){streamText.current='';if(streamFrame.current){window.cancelAnimationFrame(streamFrame.current);streamFrame.current=0}setStreamingText('')}
  function stopStreaming(){
    if(!streaming)return;
    request.current?.abort();cancelStream.current?.();
    request.current=null;cancelStream.current=null;
    if(streamFrame.current){window.cancelAnimationFrame(streamFrame.current);streamFrame.current=0}
    setStreamingText(streamText.current);setStreaming(false);setBusy(false);setStatusText('');setStopped(true);setLiveStatus('已停止');
    pending.current=null;
  }
  async function submit(retry=false, preset?:string) {
    const content = preset ?? (retry&&pending.current?pending.current.content:input.trim());
    if (!content || busy || dirty || suggestion || generating || needsRefresh) return;
    const last = messages[messages.length-1];
    // 重新生成时不重复插入同一条用户消息。
    const prior = preset!==undefined && last?.role==='user' && last.content===content
      ? messages.slice(0,-1)
      : pending.current && messages===pending.current.next ? pending.current.next.slice(0,-1) : messages;
    const next: ChatMessage[] = [...prior, {role:'user', content}];
    setError('');setNeedsRefresh(false);setBusy(true);setStatusText('正在理解需求…');clearStream();setStopped(false);setStreaming(true);setLiveStatus('正在规划…');lastPrompt.current=content;setInput(current=>retry&&current!==content?current:'');
    setMessages(next);onAgentPreviewClear?.();
    const controller = new AbortController();
    request.current = controller;
    let streamError = '';
    let pendingFinish: {days?:unknown;backlog?:unknown;reply?:string;changed?:boolean;version?:number} | null = null;
    const finish = () => {
      if (controller.signal.aborted) return;
      if (streamError) { onAgentPreviewClear?.();setError(streamError); setInput(current=>current||content); pending.current={content,next}; }
      else if (pendingFinish) {
        pending.current=null;
        const {days,backlog,reply,changed,version} = pendingFinish;
        if (typeof version === 'number') onVersion?.(version);
        const text = `${reply||''}${changed && dirtyRef.current ? '\n等待期间行程已修改，本次建议未应用；保存后可以重新提出。' : ''}`;
        setMessages([...next, {role:'assistant', content:text}]);
        if (changed && days && backlog && !dirtyRef.current) {
          if(tripRef.current?.id===0){onSuggestion?.(days as Day[],backlog as Stop[]);onAgentPreviewClear?.()}
          else{setSuggestion({days:days as Day[],backlog:backlog as Stop[]});onNotify?.('AI 修改建议已就绪，可应用或忽略')}
        }
        else onAgentPreviewClear?.();
      }
      setBusy(false); setStatusText('');setStreaming(false);clearStream();setLiveStatus(streamError?'生成中断':'已完成');
    };
    if (trip) {
      cancelStream.current = streamAssistant(trip.id, {message:content, history:prior.slice(-10), version:trip.version||0, ...(trip.id===0?{preview:trip}:{})}, {
        onEvent: event => {
          if (controller.signal.aborted) return;
          if (event.kind==='delta'){if(event.reset===true)resetStream(event.text);else pushStream(event.text)}
          if (event.kind==='status'||event.kind==='tool_start'||event.kind==='tool_result') { if (event.text) setStatusText(event.text); }
          if (!dirtyRef.current) onAgentEvent?.(event);
        },
        onDone: payload => { pendingFinish=payload; streamError=payload.error||'';setNeedsRefresh(!!payload.needsRefresh);finish(); },
      });
    } else {
      cancelStream.current=streamPlanningChat({messages:next.slice(-20),current:form},{
        onDelta:text=>{if(!controller.signal.aborted)pushStream(text)},
        onDone:(result,failure)=>{
          if(controller.signal.aborted)return;
          if(failure||!result){setError(failure||'回复失败，请重试。');setInput(current=>current||content);pending.current={content,next}}
          else{pending.current=null;const nextForm={...form,...result.updates};const nextMessages:ChatMessage[]=[...next,{role:'assistant',content:result.reply}];setForm?.(nextForm);setMessages(nextMessages);setPlaces(result.place_matches||[]);setPlacesCity(nextForm.city.trim());setPlaceNotice(result.place_notice||'');if(result.intent==='plan'&&result.updates.city?.trim())onGenerate?.(nextForm,nextMessages)}
          setBusy(false);setStatusText('');setStreaming(false);clearStream();setLiveStatus(failure||!result?'生成中断':'已完成');
        }
      });
    }
  }
  function send(e: React.FormEvent) { e.preventDefault(); void submit(); }
  async function refreshTrip(){
    if(!onRefreshTrip||busy)return;
    setBusy(true);
    try{if(await onRefreshTrip()){pending.current=null;setError('');setNeedsRefresh(false);onAgentPreviewClear?.()}}finally{setBusy(false)}
  }
  function animateGenerate(event:React.MouseEvent<HTMLButtonElement>) {
    if(generateAnimation.current||generationBlocked.current||!generateAction.current)return;
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches||typeof event.currentTarget.animate!=='function'){generateAction.current();return}
    const animation=event.currentTarget.animate([
      {transform:'scale(.96)',boxShadow:'inset 0 4px 9px #20382a55, inset 0 1px 3px #20382a35'},
      {transform:'scale(1.018)',boxShadow:'inset 0 0 0 transparent',offset:.68},
      {transform:'scale(1)',boxShadow:'none'}
    ],{duration:300,easing:'cubic-bezier(.2,.8,.2,1)'});
    generateAnimation.current=animation;
    animation.onfinish=()=>{generateAnimation.current=null;if(!generationBlocked.current)generateAction.current?.()};
  }
  const messageKeyList=useMemo(()=>messageKeys(messages),[messages]);
  const hasContent=!!(messages.length||busy||streamingText||places.length||placeNotice||(compact&&(error||dirty)));
  return <section className={`travel-chat${compact?' home-chat':''}${compact&&!expanded?' is-collapsed':''}${compact&&expanded?' is-open':''}`} aria-label="旅行对话">
    {!compact&&<div className="travel-chat-heading"><div><span className="section-kicker">行迹 AI</span><h2>{trip ? '一起完善旅程' : '从旅行的想法开始'}</h2></div>{trip && <span className="chat-context">{trip.request.city} · {trip.request.days} 天</span>}</div>}
    <p className="visually-hidden" role="status" aria-live="polite">{liveStatus}</p>
    <div ref={messagesRef} className={`travel-messages${messages.length||busy||places.length||placeNotice||(compact&&expanded)?' has-content':''}`}>
      {compact&&<div className="chat-panel-head"><span className="chat-panel-title"><i className="chat-avatar" aria-hidden="true"><StarIcon/></i>行迹 AI</span><span className="chat-panel-actions">{onUndo&&<button type="button" className="text-btn" onClick={onUndo}>撤销调整</button>}</span></div>}
      {compact&&!hasContent&&<p className="chat-wait">想去哪儿？</p>}
      {compact&&error&&<div className="error" role="alert"><span>{error}</span>{needsRefresh&&onRefreshTrip?<button type="button" className="text-btn" disabled={busy||generating} onClick={()=>void refreshTrip()}>重新打开行程</button>:<button type="button" className="text-btn" disabled={busy||dirty||!!suggestion||generating||!pending.current} onClick={()=>void submit(true)}>重试</button>}</div>}
      {compact&&dirty&&<p className="chat-hint">请先保存或放弃行程修改，再继续对话。</p>}
      {messages.length === 0 && !compact && <div className="chat-welcome"><div className="route-mark" aria-hidden="true"><span></span><span></span><span></span></div><p>{trip ? '想调整路线，或了解某个地点？告诉我你的想法。' : '想去哪里、玩几天，或者期待怎样的旅程？从你已经知道的开始说起。'}</p></div>}
      {messages.map((m,i)=>m.role==='assistant'
        ? <div key={messageKeyList[i]} className="chat-message assistant"><span className="chat-bubble-label"><i className="chat-avatar" aria-hidden="true"><StarIcon/></i>行迹 AI</span><p>{m.content}</p></div>
        : <div key={messageKeyList[i]} className="chat-message user"><span>我</span><p>{m.content}</p></div>)}
      {!trip && onCollect && placesCity===form.city.trim() && <fieldset className="planning-options" disabled={generating}><PlaceSuggestions groups={places} collectedIds={collectedIds} onCollect={onCollect}/></fieldset>}
      {!trip && placeNotice && <p className="chat-hint">{placeNotice}</p>}
      {streamingText&&<div className="chat-message assistant" aria-live="off"><span className="chat-bubble-label"><i className="chat-avatar chat-avatar-spin" aria-hidden="true"><StarIcon/></i>行迹 AI</span><p>{streamingText}{streaming&&<span className="chat-cursor" aria-hidden="true"/>}</p></div>}
      {busy&&!streamingText && <p className="chat-wait"><i className="chat-avatar chat-avatar-spin" aria-hidden="true"><StarIcon/></i><span>{statusText||'正在理解需求…'}</span></p>}
      {generating&&!busy&&<p className="chat-wait"><i className="chat-avatar chat-avatar-spin" aria-hidden="true"><StarIcon/></i><span>正在查询地点并规划路线…</span></p>}
      <div ref={end}/>
    </div>
    {streaming&&<div className="chat-stop-row"><button type="button" className="chat-stop" onClick={stopStreaming}>停止生成</button></div>}
    {stopped&&!streaming&&<div className="chat-stopped"><span>已停止</span><span aria-hidden="true">·</span><button type="button" onClick={()=>void submit(false,lastPrompt.current)}>重新生成</button></div>}
    {suggestion && trip && <div className="suggestion-card"><strong>行程修改建议</strong><SuggestionDiff before={trip.days} after={suggestion.days} mode={trip.request.transport}/>{JSON.stringify((trip.backlog||[]).map(s=>s.place.id))!==JSON.stringify(suggestion.backlog.map(s=>s.place.id))&&<div><b>待规划</b><p>原来：{(trip.backlog||[]).map(s=>s.activity||s.place.name).join('、')||'无'}</p><p>建议：{suggestion.backlog.map(s=>s.activity||s.place.name).join('、')||'无'}</p></div>}<p>应用后可继续编辑，保存后生效。</p><div className="suggestion-actions"><button type="button" className="primary" disabled={dirty} onClick={()=>{onSuggestion?.(suggestion.days,suggestion.backlog);onAgentPreviewClear?.();setSuggestion(null)}}>应用建议</button><button type="button" className="text-btn" onClick={()=>{onAgentPreviewClear?.();setSuggestion(null);onNotify?.('已忽略本次 AI 建议')}}>不采用</button></div></div>}
    {!compact && error && <div className="error" role="alert">{error}</div>}
    {!compact && dirty && <p className="chat-hint">请先保存或放弃行程修改，再继续对话。</p>}
    {compact&&<button type="button" className="chat-collapse" aria-label={expanded?'收起对话':'展开对话'} aria-expanded={expanded} onClick={()=>setExpanded(value=>!value)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>}<form className="travel-input" onSubmit={send}><textarea aria-label="描述旅行想法" value={input} onFocus={()=>setExpanded(true)} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit()}}} placeholder={compact?'说说你的旅行想法':'告诉我你的旅行想法'} maxLength={2000} rows={compact?1:2} readOnly={dirty || !!suggestion || generating}/><div><span>Enter 发送 · Shift + Enter 换行</span><button className={`primary send-round${busy||generating?' is-flying':''}`} aria-label={busy||generating?'正在规划':'发送'} disabled={busy || dirty || !!suggestion || generating || needsRefresh || !input.trim()}><SendIcon/></button></div></form>
    {!trip && <div className="planning-actions"><span>{generating?'正在核对地图地点并规划路线，请稍候':form.city ? `${form.city} · ${form.days} 天 · ${form.travelers} 人 · ${form.pace}` : '说说想去哪里、玩几天'}</span><button type="button" className="secondary generate-button" onClick={animateGenerate} disabled={!form.city.trim() || generating || busy}>{generating?'正在生成…':'生成行程'}</button></div>}
  </section>;
}
