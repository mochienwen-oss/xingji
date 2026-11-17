import React, { useState } from "react";
import { api, message } from "../lib/api";
import type { Day, GuideOutlineDay, Place, Stop } from "../types/trip";

type Extracted = { name:string; day_hint:string; matches:Place[] };
export type GuideAdoptResult = {days:Day[];backlog:Stop[];version:number};
type Props = {tripId:number;city:string;existingIds:string[];version?:number;dirty?:boolean;onAdd:(places:Place[])=>boolean;onAdopt:(result:GuideAdoptResult)=>void};
type Mode = 'outline'|'extract';

/** 把一条大纲站点解析为最终地点：精确命中优先，否则用核对下拉里选中的匹配。 */
function resolveStop(stop:GuideOutlineDay['stops'][number]|undefined, chosenId?:string):Place|null {
  if(!stop)return null;
  if(stop.place)return stop.place;
  return stop.matches.find(place=>place.id===chosenId)||null;
}

export function GuideImport({tripId,city,existingIds,version,dirty,onAdd,onAdopt}:Props) {
  const [mode,setMode]=useState<Mode|null>(null), [text,setText]=useState(''), [busy,setBusy]=useState(false);
  const [error,setError]=useState(''), [notice,setNotice]=useState('');
  /* 旧入口：从攻略提取地点 */
  const [results,setResults]=useState<Extracted[]>([]), [selected,setSelected]=useState<Record<number,string>>({});
  const [keywords,setKeywords]=useState<Record<number,string>>({}), [searching,setSearching]=useState<number|null>(null);
  /* 新入口：AI 按天成稿 */
  const [days,setDays]=useState<GuideOutlineDay[]>([]), [checked,setChecked]=useState<Record<string,boolean>>({});
  const [chosen,setChosen]=useState<Record<string,string>>({}), [adopting,setAdopting]=useState(false);

  function resetFeedback(){setError('');setNotice('')}
  function switchMode(next:Mode){resetFeedback();setMode(current=>current===next?null:next)}

  async function parse(e:React.FormEvent) {
    e.preventDefault(); if(!text.trim()) return;
    setBusy(true);setError('');setNotice('');setResults([]);setSelected({});setKeywords({});
    try {const data=await api<{results:Extracted[]}>(`/trips/${tripId}/guide`,{method:'POST',body:JSON.stringify({text})});setResults(data.results);if(!data.results.length)setError('没有识别到明确的地点，请补充地点名称后重试')}
    catch(e){setError(message(e))}finally{setBusy(false)}
  }
  async function search(index:number) {
    const keyword=(keywords[index]||results[index].name).trim();if(!keyword)return;
    setSearching(index);setError('');
    try{const matches=await api<Place[]>(`/places?city=${encodeURIComponent(city)}&q=${encodeURIComponent(keyword)}`);setResults(current=>current.map((r,i)=>i===index?{...r,matches:matches.slice(0,5)}:r));setSelected(current=>({...current,[index]:''}));if(!matches.length)setError(`没有找到“${keyword}”，请换个名称`)}
    catch(e){setError(message(e))}finally{setSearching(null)}
  }
  const selectedPlaces=results.flatMap((r,i)=>{const place=r.matches.find(p=>p.id===selected[i]);return place&&!existingIds.includes(place.id)?[place]:[]});
  function addSelected() {
    const unique=[...new Map(selectedPlaces.map(place=>[place.id,place])).values()];
    if(!unique.length)return;
    if(!onAdd(unique))return;
    setResults(current=>current.filter((_,i)=>!selected[i]||!unique.some(p=>p.id===selected[i])));
    setSelected({});setKeywords({});
  }

  async function outline(e:React.FormEvent) {
    e.preventDefault();
    const content=text.trim(); if(!content||busy)return;
    setBusy(true);resetFeedback();setDays([]);setChecked({});setChosen({});
    try{
      const data=await api<{days:GuideOutlineDay[]}>(`/trips/${tripId}/guide/outline`,{method:'POST',body:JSON.stringify({text:content})});
      if(!data.days.length){setError('AI 没有整理出可用的行程大纲，请补充攻略正文后重试');return}
      const next:Record<string,boolean>={};
      data.days.forEach((day,dayIndex)=>day.stops.forEach((stop,stopIndex)=>{
        const place=resolveStop(stop);
        if(place&&!existingIds.includes(place.id))next[`${dayIndex}-${stopIndex}`]=true;
      }));
      setDays(data.days);setChecked(next);
      if(data.days.length!==data.days.filter(day=>day.stops.length).length)setNotice('部分日期没有识别到地点，可补充分天后重新生成');
    }catch(e){setError(message(e))}finally{setBusy(false)}
  }

  const picked=days.flatMap((day,dayIndex)=>day.stops.flatMap((stop,stopIndex)=>{
    if(!checked[`${dayIndex}-${stopIndex}`])return [];
    const place=resolveStop(stop,chosen[`${dayIndex}-${stopIndex}`]);
    if(!place||existingIds.includes(place.id))return [];
    return [{day:dayIndex+1,place,duration:90}];
  }));
  const assignments=[...new Map(picked.map(item=>[item.place.id,item])).values()];

  async function adopt() {
    if(!assignments.length||adopting)return;
    // 采纳会在服务端整份替换 days/backlog；本地未保存修改必须先在保存/放弃之间做选择，
    // 否则请求成功后本地被覆盖，version CAS 也发现不了。
    if(dirty){setError('当前有未保存的修改，请先保存或放弃修改后再采纳攻略。');return}
    setAdopting(true);resetFeedback();
    try{
      const payload:Record<string,unknown>={assignments:assignments.map(item=>({day:item.day,place_id:item.place.id,duration:item.duration}))};
      if(version!==undefined)payload.version=version;
      const result=await api<GuideAdoptResult>(`/trips/${tripId}/guide/adopt`,{method:'POST',body:JSON.stringify(payload)});
      onAdopt(result);
      setDays([]);setChecked({});setChosen({});setText('');setMode(null);
      setNotice('已加入行程');
    }catch(e){setError(message(e))}finally{setAdopting(false)}
  }

  return <section className="guide-import">
    <div className="guide-entry">
      <button type="button" className="primary" aria-expanded={mode==='outline'} onClick={()=>switchMode('outline')}>{mode==='outline'?'收起 AI 排行程':'AI 按天排行程'}</button>
      <button type="button" className="secondary" aria-expanded={mode==='extract'} onClick={()=>switchMode('extract')}>{mode==='extract'?'收起提取':'从攻略提取地点'}</button>
    </div>
    {notice&&<div className="notice" role="status">{notice}</div>}
    {error&&<div className="error" role="alert">{error}</div>}

    {mode==='outline'&&<div className="guide-content guide-outline">
      <h3>AI 按天排行程</h3>
      <p>粘贴攻略正文，AI 会按天拆分、核对地图地点；确认后再一次采纳进行程。</p>
      <form onSubmit={outline}>
        <textarea aria-label="攻略文字（按天排行程）" value={text} onChange={e=>setText(e.target.value)} placeholder="粘贴攻略正文，例如：第一天先去碑林，傍晚逛回民街；第二天上城墙…" maxLength={12000}/>
        <button className="primary" disabled={busy||!text.trim()}>{busy?'AI 正在按天整理…':'生成按天大纲'}</button>
      </form>
      {days.length>0&&<div className="guide-days">
        {days.map((day,dayIndex)=><section className="guide-day" key={dayIndex}>
          <header className="guide-day-head"><span className="guide-day-label">第 {dayIndex+1} 天</span><p>{day.summary||'这一天还没有摘要'}</p></header>
          {day.stops.length===0?<p className="guide-day-empty">这一天没有整理出地点</p>
            :<ul className="guide-stops">{day.stops.map((stop,stopIndex)=>{
              const key=`${dayIndex}-${stopIndex}`;
              const place=resolveStop(stop,chosen[key]);
              const duplicated=place?existingIds.includes(place.id):false;
              const pickable=Boolean(place)&&!duplicated;
              return <li className={`guide-stop${checked[key]&&pickable?' is-picked':''}`} key={`${stop.name}-${stopIndex}`}>
                <label className="guide-check"><input type="checkbox" checked={Boolean(checked[key])&&pickable} disabled={!pickable} onChange={e=>setChecked(current=>({...current,[key]:e.target.checked}))} aria-label={`选择${stop.name}`}/></label>
                <div className="guide-stop-body">
                  <strong>{stop.name}</strong>
                  {stop.why&&<p>{stop.why}</p>}
                  {place
                    ? <small className="guide-place">{place.name} · {place.address||'地址暂无信息'}{duplicated?' · 已在行程中':''}</small>
                    : stop.matches.length
                      ? <label className="guide-match">核对地点<select value={chosen[key]||''} aria-label={`核对${stop.name}`} onChange={e=>{setChosen(current=>({...current,[key]:e.target.value}));if(e.target.value)setChecked(current=>({...current,[key]:true}))}}><option value="">选择匹配地点</option>{stop.matches.map(option=><option key={option.id} value={option.id} disabled={existingIds.includes(option.id)}>{option.name} · {option.address||'地址暂无信息'}{existingIds.includes(option.id)?'（已在行程中）':''}</option>)}</select></label>
                      : <small className="guide-place">未匹配到地图地点，可稍后在行程里手动添加</small>}
                </div>
              </li>;
            })}</ul>}
        </section>)}
      </div>}
      {days.length>0&&<div className="guide-batch"><span>{dirty?'请先保存或放弃当前修改，再采纳攻略':`已选 ${assignments.length} 站`}</span><button type="button" className="primary" disabled={!assignments.length||adopting||dirty} onClick={adopt}>{adopting?'正在加入…':`采纳所选（${assignments.length} 站）`}</button></div>}
    </div>}

    {mode==='extract'&&<div className="guide-content"><h3>从文字整理地点</h3><p>粘贴攻略正文，核对地点后可一次加入待规划</p>
      <form onSubmit={parse}><textarea aria-label="攻略文字" value={text} onChange={e=>setText(e.target.value)} placeholder="粘贴包含地点名称的攻略文字" maxLength={12000}/><button className="secondary" disabled={busy||searching!==null||!text.trim()}>{busy?'正在识别…':'提取地点'}</button></form>
      {results.length>0&&<ul className="guide-results">{results.map((result,i)=><li className="guide-result" key={`${result.name}-${i}`}><div><strong>{result.name}</strong>{result.day_hint&&<small>原文提示：{result.day_hint}</small>}</div>
        <div><label>核对地点<select aria-label={`核对${result.name}`} value={selected[i]||''} onChange={e=>setSelected({...selected,[i]:e.target.value})}><option value="">{result.matches.length?'选择匹配地点':'没有匹配结果'}</option>{result.matches.map(p=><option key={p.id} value={p.id} disabled={existingIds.includes(p.id)}>{p.name} · {p.address||'地址暂无信息'}{existingIds.includes(p.id)?'（已在行程中）':''}</option>)}</select></label>
          <div className="guide-research"><input aria-label={`重新搜索${result.name}`} value={keywords[i]??result.name} onChange={e=>setKeywords({...keywords,[i]:e.target.value})} maxLength={80}/><button type="button" className="text-btn" disabled={busy||searching!==null} onClick={()=>search(i)}>{searching===i?'搜索中…':'重新搜索'}</button></div></div></li>)}</ul>}
      {results.length>0&&<div className="guide-batch"><span>已确认 {new Set(selectedPlaces.map(p=>p.id)).size} 个地点</span><button type="button" className="secondary" disabled={!selectedPlaces.length} onClick={addSelected}>加入待规划</button></div>}
    </div>}
  </section>;
}
