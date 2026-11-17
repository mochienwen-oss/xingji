import { describe, expect, it } from 'vitest';
import { amapNavigationUrl, navigationMode } from './amapNavigation';

describe('navigationMode', () => {
  it('maps trip transport modes to Amap modes', () => {
    expect(navigationMode('walking')).toBe('walk');
    expect(navigationMode('transit')).toBe('bus');
    expect(navigationMode('driving')).toBe('car');
    expect(navigationMode('other')).toBe('car');
  });
});

describe('amapNavigationUrl', () => {
  it('builds a navigation deep link with encoded name', () => {
    const url = amapNavigationUrl({ name: '西湖 断桥', location: '120.15,30.25' }, 'walk');
    expect(url).toBe('https://uri.amap.com/navigation?to=120.15,30.25,%E8%A5%BF%E6%B9%96%20%E6%96%AD%E6%A1%A5&mode=walk&policy=1&src=xingji-trip&coordinate=gaode&callnative=1');
  });

  it('rejects invalid coordinates instead of linking to nowhere', () => {
    expect(amapNavigationUrl({ name: 'X', location: '' })).toBeNull();
    expect(amapNavigationUrl({ name: 'X', location: '120.1' })).toBeNull();
    expect(amapNavigationUrl({ name: 'X', location: '200,30' })).toBeNull();
    expect(amapNavigationUrl(null)).toBeNull();
  });
});
