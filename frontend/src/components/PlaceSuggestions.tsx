import type { Place } from "../types/trip";
import { useState } from 'react';
import { PlaceThumbnail } from './PlaceThumbnail';

export type PlaceMatch = {keyword:string;matches:Place[]};
export function PlaceSuggestions({groups,collectedIds,onCollect}:{groups:PlaceMatch[];collectedIds:string[];onCollect:(place:Place)=>string}) {
  const [error,setError]=useState('');
  if(!groups.length)return null;
  return <div className="place-suggestions"><strong>地图匹配结果</strong><p>请核对地址，确认是否为想去的地点。</p>{error&&<p role="alert">{error}</p>}{groups.map((group,i)=><div key={`${group.keyword}-${i}`}><small>{group.keyword}</small>{group.matches.length===0?<p>没有找到匹配地点</p>:group.matches.map(place=><div className="place-suggestion" key={place.id}><PlaceThumbnail place={place}/><div><b>{place.name}</b><p>{place.address||'地址暂无信息'}</p></div><button type="button" className="text-btn" disabled={collectedIds.includes(place.id)} onClick={()=>setError(onCollect(place))}>{collectedIds.includes(place.id)?'已收藏':'收藏地点'}</button></div>)}</div>)}</div>;
}
