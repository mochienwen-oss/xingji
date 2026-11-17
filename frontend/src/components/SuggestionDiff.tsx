import { formatTime, scheduleDay } from "../lib/schedule";
import type { Day } from "../types/trip";

function travelMinutes(day:Day|undefined, mode:string):number|null {
  if(!day)return null;
  let seconds=0;
  for(let i=0;i<day.stops.length-1;i++){
    const route=day.routes[i];
    if(!route||route.origin!==day.stops[i].place.id||route.destination!==day.stops[i+1].place.id||route.mode!==mode||route.duration==null)return null;
    seconds+=route.duration;
  }
  return Math.ceil(seconds/60);
}
function describe(day:Day|undefined):string {
  return day?day.stops.map(s=>`${s.activity||s.place.name}（${s.duration} 分钟）`).join(' → ')||'未安排地点':'未安排';
}
export function SuggestionDiff({before,after,mode}:{before:Day[];after:Day[];mode:string}) {
  return <>{after.map((day,i)=>{
    const original=before[i];
    const oldText=describe(original),newText=describe(day);
    if(oldText===newText)return null;
    // AI 建议可能比原行程多出几天：此时 original 为 undefined，不能读 original.stops（审计 P0-1）。
    const added=!original;
    const oldTravel=travelMinutes(original,mode),newTravel=travelMinutes(day,mode);
    const oldFinish=original?scheduleDay(original,mode).finish:null,newFinish=scheduleDay(day,mode).finish;
    return <div key={day.start_time||day.stops[0]?.place.id||i}>
      <b>{added?`第 ${i+1} 天 · 新增`:`第 ${i+1} 天`}</b>
      {!added&&<p>原来：{oldText}</p>}
      <p>建议：{newText}</p>
      {!added&&<p>{oldTravel!==null&&newTravel!==null?`预计交通 ${oldTravel} → ${newTravel} 分钟`:'部分交通时间未知，暂无法比较'}</p>}
      {oldFinish!==null&&newFinish!==null&&<p>预计结束 {formatTime(oldFinish)} → {formatTime(newFinish)}</p>}
    </div>;
  })}</>;
}
