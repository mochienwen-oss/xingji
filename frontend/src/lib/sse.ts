/** 行迹 SSE 传输层：所有流式 POST 接口共用的唯一实现。
 *
 * 只负责传输：fetch POST JSON → 校验响应 → 增量解码 → 按空行分帧 →
 * 解析 data: 行（忽略注释心跳与坏 JSON）。业务事件协议、done/saved/error
 * 聚合仍留在 agent.ts 与 harness/session.ts。
 *
 * 不设任何 idle watchdog 或超时定时器：流式会话可能长时间没有输出，
 * 是否中断由调用方主动 abort（使用返回的取消函数）决定。
 */

export type SseHttpError = {kind: 'http'; status: number; detail?: string};
export type SseNetworkError = {kind: 'network'; cause: unknown};
export type SseError = SseHttpError | SseNetworkError;

export type SseOptions<T> = {
  url: string;
  body: unknown;
  /** 一条解析成功的 data: 事件。 */
  onEvent?: (event: T) => void;
  /** 流正常读完且未被 abort 时调用；是否「完整」由调用方按事件判断。 */
  onEnd?: () => void;
  /** fetch 失败、非 2xx / 无 body、读流中断时调用；abort 后不再回调。 */
  onError?: (error: SseError) => void;
};

/** 空行分帧；同时接受 CRLF，避免代理改写换行后整段事件被丢弃。 */
const FRAME_BREAK = /\r?\n\r?\n/;

export function streamSse<T = unknown>({url, body, onEvent, onEnd, onError}: SseOptions<T>): () => void {
  const controller = new AbortController();

  void (async () => {
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (cause) {
      if (!controller.signal.aborted) onError?.({kind: 'network', cause});
      return;
    }

    if (!response.ok || !response.body) {
      const parsed = await response.json().catch(() => null) as {detail?: unknown} | null;
      const detail = typeof parsed?.detail === 'string' ? parsed.detail : undefined;
      if (!controller.signal.aborted) onError?.({kind: 'http', status: response.status, detail});
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        let match: RegExpExecArray | null;
        while ((match = FRAME_BREAK.exec(buffer)) !== null) {
          const raw = buffer.slice(0, match.index).trim();
          buffer = buffer.slice(match.index + match[0].length);
          if (!raw.startsWith('data:')) continue;
          let event: T;
          try {
            event = JSON.parse(raw.slice(5).trim()) as T;
          } catch {
            continue;
          }
          onEvent?.(event);
        }
      }
    } catch (cause) {
      if (!controller.signal.aborted) onError?.({kind: 'network', cause});
      return;
    }

    // 服务端正常帧都以空行结尾；连接被截断时最后一条 data: 可能没有空行，补解析一次。
    const tail = buffer.trim();
    if (tail.startsWith('data:')) {
      try {
        onEvent?.(JSON.parse(tail.slice(5).trim()) as T);
      } catch {
        /* 半帧解析不了，忽略 */
      }
    }

    if (!controller.signal.aborted) onEnd?.();
  })();

  return () => controller.abort();
}
