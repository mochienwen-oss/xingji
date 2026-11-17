import { useState } from 'react';
import type { Place } from '../types/trip';

export function PlaceThumbnail({place, eager}: {place: Place; eager?: boolean}) {
  const urls = Array.isArray(place.photos) ? place.photos.map(photo => photo.url).filter(Boolean) : [];
  const key = JSON.stringify([place.id, urls]);
  const [failure, setFailure] = useState({key:'', index:0});
  const index = failure.key === key ? failure.index : 0;
  return <div className="stop-thumbnail">{urls[index]
    ? <img src={urls[index]} alt={`${place.name}的高德图片`} loading={eager ? 'eager' : 'lazy'} draggable={false} referrerPolicy="no-referrer" onError={() => setFailure({key, index:index+1})}/>
    : <span aria-label="地点暂无图片">无图</span>}</div>;
}
