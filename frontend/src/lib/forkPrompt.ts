/**
 * 从分享页复制行程后，引导用户设置自己的出发日期。
 * 用 sessionStorage 传一次性意图：只在当前标签页生效，读完即删，
 * 不污染新建行程（用户可能在拿到 id 前就关掉页面）。
 */
const DATE_PROMPT_KEY = 'xingji:date-prompt';

export function markForkDatePrompt(tripId: number): void {
  try {
    window.sessionStorage.setItem(DATE_PROMPT_KEY, String(tripId));
  } catch {
    // 隐私模式或存储被禁用时静默跳过，不阻塞复制主流程。
  }
}

export function consumeForkDatePrompt(tripId: number): boolean {
  try {
    const pending = window.sessionStorage.getItem(DATE_PROMPT_KEY);
    if (pending !== String(tripId)) return false;
    window.sessionStorage.removeItem(DATE_PROMPT_KEY);
    return true;
  } catch {
    return false;
  }
}
