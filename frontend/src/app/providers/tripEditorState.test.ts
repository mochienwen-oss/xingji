import { describe, expect, it } from 'vitest';
import type { Day, Trip } from '../../types/trip';
import { initialTripEditorState, reduce } from './tripEditorState';

const day = (name: string): Day => ({
  stops: [
    {
      place: {
        id: name,
        name,
        address: '京都府',
        location: '135.0,35.0',
        opentime: '09:00-17:00',
        cost: '免费',
        source_time: '2026-11-01',
      },
      duration: 60,
      reason: '测试数据',
    },
  ],
  routes: [],
});

const baseTrip: Trip = {
  id: 7,
  version: 3,
  title: '京都一日',
  request: {
    city: '京都',
    days: 1,
    start_date: null,
    travelers: 2,
    interests: '',
    pace: '适中',
    budget: '',
    must_visit: '',
    transport: 'walking',
  },
  days: [day('清水寺')],
  backlog: [],
  created_at: '2026-11-01T00:00:00Z',
};

const loaded = reduce(initialTripEditorState, { type: 'load', trip: baseTrip });
const editedDays = [day('金阁寺')];
const edited = reduce(loaded, { type: 'edit', days: editedDays });
const remote: Trip = { ...baseTrip, version: 4, days: [day('岚山')] };

describe('trip editor state machine', () => {
  it('keeps local edits on 409 and offers three exits', () => {
    const s = reduce(edited, { type: 'saveConflict' });
    expect(s.saveConflict).toBe(true);
    expect(s.dirty).toBe(true);
    expect(s.trip).toBe(edited.trip);
    // 三个出口互不覆盖：载入最新只放候选、保留我的保留本地、放弃修改才换服务器版本。
    const candidate = reduce(s, { type: 'reloadLatest', trip: remote });
    expect(candidate.saveConflict).toBe(true);
    expect(candidate.trip).toBe(edited.trip);
    expect(candidate.latest).toBe(remote);
  });

  it('stops polling and disables editing on accessLost', () => {
    const s = reduce(edited, { type: 'accessLost' });
    expect(s.accessLost).toBe(true);
    expect(s.syncState).toBe('offline');
    expect(s.busy).toBe(false);
    const ignored = reduce(s, { type: 'edit', days: [day('伏见稻荷大社')] });
    expect(ignored.trip).toBe(s.trip);
    expect(ignored.dirty).toBe(true);
    expect(reduce(s, { type: 'saveStart' }).syncState).toBe('offline');
  });

  it('does not overwrite dirty with reloadLatest until keepMine or discardMine', () => {
    const candidate = reduce(edited, { type: 'reloadLatest', trip: remote });
    expect(candidate.trip).toBe(edited.trip);
    expect(candidate.trip?.days).toBe(editedDays);
    expect(candidate.dirty).toBe(true);
    expect(candidate.latest).toBe(remote);
  });

  it('keepMine keeps local days and adopts the latest version', () => {
    const candidate = reduce(edited, { type: 'reloadLatest', trip: remote });
    const kept = reduce(candidate, { type: 'keepMine' });
    expect(kept.dirty).toBe(true);
    expect(kept.saveConflict).toBe(false);
    expect(kept.latest).toBeNull();
    expect(kept.trip?.days).toBe(editedDays);
    expect(kept.trip?.version).toBe(4);
  });

  it('discardMine replaces the local trip with the server version and clears dirty', () => {
    const dirtyConflict = reduce(reduce(edited, { type: 'saveConflict' }), {
      type: 'reloadLatest',
      trip: remote,
    });
    const discarded = reduce(dirtyConflict, { type: 'discardMine' });
    expect(discarded.trip).toBe(remote);
    expect(discarded.dirty).toBe(false);
    expect(discarded.saveConflict).toBe(false);
    expect(discarded.latest).toBeNull();
    expect(discarded.syncState).toBe('synced');
  });

  it('clears dirty and keeps the saved trip on saveSuccess', () => {
    const saving = reduce(edited, { type: 'saveStart' });
    expect(saving.syncState).toBe('saving');
    const saved = reduce(saving, { type: 'saveSuccess', trip: remote });
    expect(saved.trip).toBe(remote);
    expect(saved.dirty).toBe(false);
    expect(saved.busy).toBe(false);
    expect(saved.syncState).toBe('synced');
  });

  it('goes offline on a network failure but keeps the edits for a retry', () => {
    const failed = reduce(reduce(edited, { type: 'saveStart' }), {
      type: 'saveError',
      message: '网络不可用，请检查连接',
    });
    expect(failed.syncState).toBe('offline');
    expect(failed.dirty).toBe(true);
    expect(failed.busy).toBe(false);
    expect(failed.trip).toBe(edited.trip);
    expect(failed.error).toBe('网络不可用，请检查连接');
    const retried = reduce(failed, { type: 'saveStart' });
    expect(retried.syncState).toBe('saving');
    expect(retried.busy).toBe(true);
  });

  it('restores the snapshot on undo', () => {
    const withUndo = reduce(loaded, { type: 'edit', days: [day('金阁寺')], undo: true });
    expect(withUndo.undo).not.toBeNull();
    const restored = reduce(withUndo, { type: 'undo' });
    expect(restored.trip?.days).toBe(baseTrip.days);
    expect(restored.dirty).toBe(true);
    expect(restored.undo).toBeNull();
  });

  it('does not let polling downgrade a save in flight', () => {
    const saving = reduce(edited, { type: 'saveStart' });
    expect(reduce(saving, { type: 'syncStatus', status: 'synced' }).syncState).toBe('saving');
    expect(reduce(saving, { type: 'syncStatus', status: 'offline' }).syncState).toBe('saving');
    expect(reduce(saving, { type: 'syncStatus', status: 'synced' }).busy).toBe(true);
  });

  it('clears edits, undo and access loss when another trip is loaded', () => {
    const lost = reduce(edited, { type: 'accessLost' });
    const next = reduce(lost, { type: 'load', trip: remote });
    expect(next.trip).toBe(remote);
    expect(next.dirty).toBe(false);
    expect(next.accessLost).toBe(false);
    expect(next.undo).toBeNull();
    expect(next.syncState).toBe('synced');
  });

  it('ackVersion adopts the AI-saved version without touching local edits', () => {
    const acked = reduce(edited, { type: 'ackVersion', version: 5 });
    expect(acked.trip?.version).toBe(5);
    // 本地 days/backlog 原样保留（引用不变），dirty 也不被清掉。
    expect(acked.trip?.days).toBe(editedDays);
    expect(acked.trip?.backlog).toBe(edited.trip?.backlog);
    expect(acked.dirty).toBe(true);
    expect(acked.latest).toBeNull();
  });

  it('ackVersion aligns the polling candidate version and ignores stale receipts', () => {
    const candidate = reduce(edited, { type: 'reloadLatest', trip: remote });
    const acked = reduce(candidate, { type: 'ackVersion', version: 5 });
    expect(acked.trip?.version).toBe(5);
    expect(acked.trip?.days).toBe(editedDays);
    // latest 候选只同步版本号，days 仍是轮询拿到的服务器快照。
    expect(acked.latest?.version).toBe(5);
    expect(acked.latest?.days).toBe(remote.days);
    const advanced = reduce(acked, { type: 'ackVersion', version: 6 });
    expect(advanced.trip?.version).toBe(6);
    expect(advanced.latest?.version).toBe(6);
    // 迟到的旧回执不回退已推进的版本，也不触发无谓的重渲染。
    expect(reduce(advanced, { type: 'ackVersion', version: 5 })).toBe(advanced);
  });

  it('drops the previous account trip on sessionReset', () => {
    expect(reduce(edited, { type: 'sessionReset' })).toBe(initialTripEditorState);
  });

  it('ackVersion on a clean trip only bumps the version', () => {
    // 没有行程时是空操作。
    expect(reduce(initialTripEditorState, { type: 'ackVersion', version: 4 })).toBe(initialTripEditorState);
    const acked = reduce(loaded, { type: 'ackVersion', version: 4 });
    expect(acked.trip?.version).toBe(4);
    expect(acked.trip?.days).toBe(baseTrip.days);
    expect(acked.dirty).toBe(false);
    expect(acked.latest).toBeNull();
  });
});
