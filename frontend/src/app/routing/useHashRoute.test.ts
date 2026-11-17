import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseHash } from './routes';
import { useHashRoute } from './useHashRoute';

// jsdom 的默认地址是 http://localhost:3000/，每个用例前把 hash 清空。
const resetUrl = () => window.history.replaceState(null, '', '/');

beforeEach(() => {
  resetUrl();
});

afterEach(() => {
  vi.restoreAllMocks();
  resetUrl();
});

describe('parseHash', () => {
  it('treats an empty hash as explore', () => {
    expect(parseHash('')).toEqual({ name: 'explore' });
    expect(parseHash('#/')).toEqual({ name: 'explore' });
    expect(parseHash('#/explore')).toEqual({ name: 'explore' });
  });

  it('parses trip ids and trips tabs', () => {
    expect(parseHash('#/trips/42')).toEqual({ name: 'trip', id: 42 });
    expect(parseHash('#/trips?tab=plaza')).toEqual({ name: 'trips', tab: 'plaza' });
    expect(parseHash('#/trips?tab=mine')).toEqual({ name: 'trips', tab: 'mine' });
    expect(parseHash('#/trips')).toEqual({ name: 'trips', tab: 'mine' });
  });

  it('parses the collab page and its legacy shared tab', () => {
    expect(parseHash('#/collab')).toEqual({ name: 'collab' });
    expect(parseHash('#/collab/extra')).toEqual({ name: 'notFound', hash: '#/collab/extra' });
    // 旧「行程 → 共享」入口已提升为一级「协同」页，旧链接要落到新页面。
    expect(parseHash('#/trips?tab=shared')).toEqual({ name: 'collab' });
    expect(parseHash('#/trips?tab=shared&from=old')).toEqual({ name: 'collab' });
  });

  it('keeps legacy share and invite links', () => {
    expect(parseHash('#share=abc')).toEqual({ name: 'share', token: 'abc' });
    expect(parseHash('#invite=xyz')).toEqual({ name: 'invite', token: 'xyz' });
  });

  it('parses email token links', () => {
    expect(parseHash('#reset=tok')).toEqual({ name: 'reset', token: 'tok' });
    expect(parseHash('#verify=tok')).toEqual({ name: 'verify', token: 'tok' });
  });

  it('maps settings and legal pages', () => {
    expect(parseHash('#/settings/account')).toEqual({ name: 'account' });
    expect(parseHash('#/settings/privacy')).toEqual({ name: 'privacy' });
    expect(parseHash('#/terms')).toEqual({ name: 'terms' });
    expect(parseHash('#/privacy')).toEqual({ name: 'privacy' });
    expect(parseHash('#/profile')).toEqual({ name: 'profile' });
    expect(parseHash('#/forgot')).toEqual({ name: 'forgot' });
  });

  it('falls back to notFound for unknown paths and invalid ids', () => {
    expect(parseHash('#/nope')).toEqual({ name: 'notFound', hash: '#/nope' });
    expect(parseHash('#/trips/abc')).toEqual({ name: 'notFound', hash: '#/trips/abc' });
    expect(parseHash('#/trips/0')).toEqual({ name: 'notFound', hash: '#/trips/0' });
    expect(parseHash('#/settings')).toEqual({ name: 'notFound', hash: '#/settings' });
  });

  it('decodes url-encoded legacy tokens', () => {
    expect(parseHash('#share=a%20b')).toEqual({ name: 'share', token: 'a b' });
  });
});

describe('useHashRoute', () => {
  it('starts from the current hash', () => {
    window.history.replaceState(null, '', '#/trips/42');
    const { result } = renderHook(() => useHashRoute());
    expect(result.current.route).toEqual({ name: 'trip', id: 42 });
  });

  it('navigates with pushState and updates the route', () => {
    const push = vi.spyOn(window.history, 'pushState');
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      result.current.navigate('#/trips/7');
    });

    expect(push).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe('#/trips/7');
    expect(result.current.route).toEqual({ name: 'trip', id: 7 });
  });

  it('navigates with replaceState when asked', () => {
    const replace = vi.spyOn(window.history, 'replaceState');
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      result.current.navigate('/trips?tab=plaza', { replace: true });
    });

    expect(replace).toHaveBeenCalledTimes(1);
    expect(result.current.route).toEqual({ name: 'trips', tab: 'plaza' });
  });

  it('follows external hashchange events', () => {
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      window.history.replaceState(null, '', '#/profile');
      window.dispatchEvent(new Event('hashchange'));
    });

    expect(result.current.route).toEqual({ name: 'profile' });
  });

  it('follows popstate events', () => {
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      window.history.replaceState(null, '', '#/terms');
      window.dispatchEvent(new Event('popstate'));
    });

    expect(result.current.route).toEqual({ name: 'terms' });
  });

  it('returns to explore even when the hash does not change, without rebroadcasting', () => {
    window.history.replaceState(null, '', '#/explore');
    const onChange = vi.fn();
    window.addEventListener('hashchange', onChange);
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      result.current.navigate('#/explore', { replace: true });
    });

    // 路由状态由 setRoute 自己维护：不再自派发 hashchange，否则每次导航会多跑一遍 parse+setRoute。
    expect(onChange).not.toHaveBeenCalled();
    expect(result.current.route).toEqual({ name: 'explore' });
    window.removeEventListener('hashchange', onChange);
  });

  it('goes back through history', () => {
    const back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    const { result } = renderHook(() => useHashRoute());

    act(() => {
      result.current.back();
    });

    expect(back).toHaveBeenCalledTimes(1);
  });
});
