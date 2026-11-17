/** 规划会话 SSE 客户端：POST /api/planning/session/stream。
 *
 * 与 backend/services/harness/events.py 对齐：
 *  phase/status/delta/assistant_reset/form_patch/places/question/plan/
 *  summary_patch/done/error
 *
 * 这里只负责读流和把事件交给上层；状态归 usePlanningSession 管。
 * 传输层（fetch/解码/分帧/取消）统一走 lib/sse.ts，不设超时看门狗。
 */
import type { PlanRequest, Place, Trip } from '../../types/trip';
import { streamSse } from '../sse';

export type HarnessSummary = {
  core_request?: string;
  key_concepts?: string;
  data_and_interfaces?: string;
  errors_and_fixes?: string;
  resolution_process?: string;
  all_user_messages?: string[];
  pending_tasks?: string;
  current_work?: string;
  next_action?: string;
} & Record<string, unknown>;

export type HarnessEvent =
  | { kind: 'phase'; name: string; text: string }
  | { kind: 'status'; text: string }
  | { kind: 'delta'; text: string }
  | { kind: 'assistant_delta'; text: string }
  | { kind: 'assistant_reset' }
  | { kind: 'form_patch'; patch: Partial<PlanRequest> }
  | { kind: 'places'; places: Place[]; keyword?: string }
  | { kind: 'question'; text: string }
  | { kind: 'plan'; plan: Trip }
  | { kind: 'summary_patch'; summary: HarnessSummary; turn_count?: number }
  | {
      kind: 'done';
      reply?: string;
      question?: string;
      plan?: Trip;
      changed?: boolean;
      failed?: boolean;
      turn_count?: number;
      summary?: HarnessSummary;
    }
  | { kind: 'saved'; version: number }
  | { kind: 'error'; message: string; retryable?: boolean };

export type HarnessTurnInput = {
  mode: 'explore' | 'preview' | 'trip';
  message: string;
  messages: { role: 'user' | 'assistant'; content: string }[];
  form: PlanRequest;
  places: Place[];
  summary?: HarnessSummary | null;
  turnCount: number;
  preview?: Trip | null;
  tripId?: number | null;
  version?: number | null;
};

export type HarnessHandlers = {
  onEvent?: (event: HarnessEvent) => void;
  onDone?: (result: { done: boolean; failed: boolean; error?: string }) => void;
};

function normalizeTrip(raw: unknown): Trip | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Partial<Trip> & { days?: Trip['days'] };
  if (!value.request || !Array.isArray(value.days)) return null;
  return {
    id: Number(value.id ?? 0),
    title: value.title ?? null,
    version: Number(value.version ?? 0),
    request: value.request,
    days: value.days,
    backlog: Array.isArray(value.backlog) ? value.backlog : [],
    conversation: Array.isArray(value.conversation) ? value.conversation : [],
    created_at: typeof value.created_at === 'string' ? value.created_at : '',
    place_notice: typeof value.place_notice === 'string' ? value.place_notice : '',
    is_public: Boolean(value.is_public),
    is_owner: value.is_owner !== false,
  };
}

/** 发一轮会话；返回取消函数。 */
export function streamSession(input: HarnessTurnInput, handlers: HarnessHandlers = {}): () => void {
  let doneEvent = false;
  let failure = '';
  return streamSse<HarnessEvent>({
    url: '/api/planning/session/stream',
    body: {
      mode: input.mode,
      message: input.message,
      messages: input.messages,
      form: input.form,
      places: input.places,
      summary: input.summary ?? null,
      turn_count: input.turnCount,
      preview: input.preview ?? null,
      trip_id: input.tripId ?? null,
      version: input.version ?? null,
    },
    onEvent: event => {
      const rawEvent = event as HarnessEvent & Record<string, unknown>;
      if (event.kind === 'plan') {
        const trip = normalizeTrip(rawEvent.plan ?? rawEvent);
        if (trip) handlers.onEvent?.({ kind: 'plan', plan: trip });
        return;
      }
      if (event.kind === 'done') {
        doneEvent = true;
        const trip = rawEvent.plan ? normalizeTrip(rawEvent.plan) : null;
        handlers.onEvent?.(trip ? { ...event, plan: trip } : event);
        return;
      }
      if (event.kind === 'error') {
        failure = event.message || '这次没有排成功，请重试。';
      }
      handlers.onEvent?.(event);
    },
    onError: error => {
      if (error.kind === 'http') {
        handlers.onDone?.({ done: false, failed: true, error: error.detail ?? '规划服务暂时不可用，请稍后再试。' });
      } else {
        handlers.onDone?.({ done: false, failed: true, error: '连接中断，请重试。' });
      }
    },
    onEnd: () => {
      if (!doneEvent) {
        handlers.onDone?.({ done: false, failed: true, error: failure || '回复未完整返回，请重试。' });
        return;
      }
      handlers.onDone?.({ done: true, failed: Boolean(failure), error: failure || undefined });
    },
  });
}
