export type MotionPref = 'system' | 'reduce';
const KEY = 'xingji:motion';

export function readMotionPref(): MotionPref {
  try { return localStorage.getItem(KEY) === 'reduce' ? 'reduce' : 'system'; } catch { return 'system'; }
}

/** 用户在「我的」里选择的动效偏好，优先于系统设置；启动时先于首帧应用。 */
export function applyMotionPref(pref: MotionPref = readMotionPref()): void {
  document.documentElement.dataset.motion = pref === 'reduce' ? 'reduce' : 'system';
}

export function saveMotionPref(pref: MotionPref): void {
  try { localStorage.setItem(KEY, pref); } catch { /* 隐私模式下仅本页生效 */ }
  applyMotionPref(pref);
}
