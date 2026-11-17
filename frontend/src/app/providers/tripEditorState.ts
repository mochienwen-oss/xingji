import type { Day, Stop, Trip } from '../../types/trip';

/** 底部保存条/同步状态点使用的三态。 */
export type TripSyncState = 'synced' | 'saving' | 'offline';

/** 撤销快照只保留会被编辑的行程主体；标题等元数据不参与撤销。 */
export type TripUndo = {
  days: Day[];
  backlog: Stop[];
};

export type TripEditorState = {
  trip: Trip | null;
  dirty: boolean;
  busy: boolean;
  accessLost: boolean;
  saveConflict: boolean;
  undo: TripUndo | null;
  syncState: TripSyncState;
  /** 冲突时暂存的最新服务器版本：用户选择前绝不覆盖本地 trip。 */
  latest: Trip | null;
  /** 最近一次保存/载入失败的文案，成功后清空。 */
  error: string;
};

export const initialTripEditorState: TripEditorState = {
  trip: null,
  dirty: false,
  busy: false,
  accessLost: false,
  saveConflict: false,
  undo: null,
  syncState: 'synced',
  latest: null,
  error: '',
};

export type TripEditorAction =
  | { type: 'load'; trip: Trip }
  | { type: 'edit'; days: Day[]; backlog?: Stop[]; undo?: boolean }
  | { type: 'saveStart' }
  | { type: 'saveSuccess'; trip: Trip }
  | { type: 'saveConflict'; latest?: Trip | null }
  | { type: 'saveError'; message: string; offline?: boolean }
  | { type: 'ackVersion'; version: number }
  | { type: 'accessLost' }
  | { type: 'reloadLatest'; trip: Trip }
  | { type: 'keepMine' }
  | { type: 'discardMine' }
  | { type: 'syncStatus'; status: 'synced' | 'offline' }
  | { type: 'undo' }
  | { type: 'sessionReset' };

const EMPTY_UNDO_BACKLOG: Stop[] = [];

/**
 * 行程编辑状态机：所有网络副作用留在 Provider，这里只做可测试的状态转移。
 * CAS 契约：saveSuccess 才清 dirty；409 保留本地 trip；accessLost 后禁编辑。
 */
export function reduce(state: TripEditorState, action: TripEditorAction): TripEditorState {
  switch (action.type) {
    case 'sessionReset':
      // 退出登录或换账号：编辑器常驻不卸载，必须丢掉上一账号的行程，
      // 否则返回 #/trips/<id> 会渲染别人的内存数据，保存时才撞 401。
      return initialTripEditorState;

    case 'load':
      // 换行程/首次载入：清空上一段行程的修改、撤销与失效状态。
      return { ...initialTripEditorState, trip: action.trip };

    case 'edit': {
      if (!state.trip || state.busy || state.accessLost) return state;
      return {
        ...state,
        trip: {
          ...state.trip,
          days: action.days,
          backlog: action.backlog ?? state.trip.backlog,
        },
        dirty: true,
        saveConflict: false,
        error: '',
        undo: action.undo
          ? { days: state.trip.days, backlog: state.trip.backlog ?? EMPTY_UNDO_BACKLOG }
          : null,
      };
    }

    case 'saveStart': {
      if (!state.trip || state.accessLost) return state;
      return { ...state, busy: true, syncState: 'saving', error: '' };
    }

    case 'saveSuccess':
      return {
        ...state,
        trip: action.trip,
        dirty: false,
        busy: false,
        accessLost: false,
        saveConflict: false,
        undo: null,
        syncState: 'synced',
        latest: null,
        error: '',
      };

    case 'saveConflict':
      // 409 时本地行程与 dirty 原样保留，三选一由用户决定怎么走。
      return {
        ...state,
        dirty: true,
        busy: false,
        saveConflict: true,
        latest: action.latest ?? state.latest,
        syncState: 'synced',
        error: '',
      };

    case 'saveError':
      // 网络错误不丢编辑：保持 dirty，允许原地重试。
      return {
        ...state,
        busy: false,
        syncState: action.offline === false ? 'synced' : 'offline',
        error: action.message,
      };

    case 'ackVersion': {
      // AI 对话落库的版本回执：只把 CAS 用的 version 对齐到服务器最新，
      // 绝不覆盖本地 days/backlog/dirty；reloadLatest 放进 latest 的候选也只同步版本号。
      // 迟到的旧回执不回退（轮询/保存可能已把版本推进得更远）。
      if (!state.trip) return state;
      const version = action.version;
      const current = state.trip.version;
      const trip = current === undefined || version > current ? { ...state.trip, version } : state.trip;
      const latestCurrent = state.latest?.version;
      const latest = state.latest && (latestCurrent === undefined || version > latestCurrent)
        ? { ...state.latest, version }
        : state.latest;
      if (trip === state.trip && latest === state.latest) return state;
      return { ...state, trip, latest };
    }

    case 'accessLost':
      // 404/403：停止轮询与编辑，但本地修改仍留在内存里，以便重新检查后继续。
      return {
        ...state,
        busy: false,
        accessLost: true,
        saveConflict: false,
        latest: null,
        syncState: 'offline',
        error: '',
      };

    case 'reloadLatest':
      // 只放候选，不动 trip/dirty；keepMine 或 discardMine 才决定去向。
      return {
        ...state,
        latest: action.trip,
        busy: false,
        error: '',
      };

    case 'keepMine': {
      if (!state.trip) return state;
      const latest = state.latest;
      return {
        ...state,
        trip: latest ? { ...state.trip, version: latest.version } : state.trip,
        latest: null,
        dirty: true,
        busy: false,
        accessLost: false,
        saveConflict: false,
        syncState: 'synced',
        error: '',
      };
    }

    case 'discardMine': {
      if (!state.trip || !state.latest) return state;
      return {
        ...state,
        trip: state.latest,
        latest: null,
        dirty: false,
        busy: false,
        accessLost: false,
        saveConflict: false,
        undo: null,
        syncState: 'synced',
        error: '',
      };
    }

    case 'syncStatus': {
      if (state.accessLost) return state;
      // 保存中由 saveStart/saveSuccess 决定状态，轮询不能把“保存中”降级。
      if (state.busy) return state;
      return {
        ...state,
        syncState: action.status === 'offline' ? 'offline' : 'synced',
      };
    }

    case 'undo': {
      if (!state.trip || !state.undo || state.busy || state.accessLost) return state;
      return {
        ...state,
        trip: { ...state.trip, days: state.undo.days, backlog: state.undo.backlog },
        dirty: true,
        undo: null,
        saveConflict: false,
        error: '',
      };
    }

    default:
      return state;
  }
}
