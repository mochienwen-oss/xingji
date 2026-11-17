/** 规划会话状态机：把 SSE 事件折叠成 UI 需要的 running/streaming/status。
 *
 * 只负责流本身；表单、消息、预览路线由页面和 DraftProvider 持有，
 * 这样总结和轮次可以跟着草稿一起持久化。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Place, PlanRequest, Trip } from '../../types/trip';
import {
  streamSession,
  type HarnessEvent,
  type HarnessSummary,
  type HarnessTurnInput,
} from './session';

type Meta = { summary?: HarnessSummary | null; turnCount?: number };

export type PlanningSessionOptions = {
  onFormPatch?: (patch: Partial<PlanRequest>) => void;
  onPlan?: (trip: Trip) => void;
  onAssistant?: (text: string) => void;
  onQuestion?: (text: string) => void;
  onError?: (message: string) => void;
  onPlaces?: (places: Place[], keyword?: string) => void;
  onMeta?: (meta: Meta) => void;
};

export type PlanningSession = {
  running: boolean;
  streamText: string;
  status: string;
  send: (input: Omit<HarnessTurnInput, 'summary' | 'turnCount'> & Partial<Pick<HarnessTurnInput, 'summary' | 'turnCount'>>) => boolean;
  cancel: () => void;
};

export function usePlanningSession(options: PlanningSessionOptions): PlanningSession {
  const [running, setRunning] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [status, setStatus] = useState('');

  const optionsRef = useRef(options);
  optionsRef.current = options;
  const abortRef = useRef<(() => void) | null>(null);
  const runningRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => () => {
    mountedRef.current = false;
    abortRef.current?.();
  }, []);

  const finish = useCallback(() => {
    runningRef.current = false;
    abortRef.current = null;
    if (!mountedRef.current) return;
    setRunning(false);
    setStreamText('');
    setStatus('');
  }, []);

  const send = useCallback((input: PlanningSession['send'] extends (value: infer T) => boolean ? T : never): boolean => {
    if (runningRef.current) return false;
    runningRef.current = true;
    setRunning(true);
    setStreamText('');
    setStatus('正在理解你的需求…');

    let sawDone = false;
    let sawPlan = false;
    const handle = (event: HarnessEvent) => {
      if (!mountedRef.current) return;
      const current = optionsRef.current;
      switch (event.kind) {
        case 'phase':
        case 'status':
          setStatus(event.text || '正在处理…');
          break;
        case 'delta':
        case 'assistant_delta':
          setStreamText((text) => text + event.text);
          break;
        case 'assistant_reset':
          setStreamText('');
          break;
        case 'form_patch':
          current.onFormPatch?.(event.patch);
          break;
        case 'places':
          current.onPlaces?.(event.places, event.keyword);
          break;
        case 'question':
          current.onQuestion?.(event.text);
          break;
        case 'plan':
          sawPlan = true;
          current.onPlan?.(event.plan);
          break;
        case 'summary_patch':
          current.onMeta?.({ summary: event.summary, turnCount: event.turn_count });
          break;
        case 'error':
          current.onError?.(event.message);
          setStatus('');
          break;
        case 'done': {
          sawDone = true;
          const reply = (event.reply || '').trim();
          // plan 事件已经触发过 onPlan；done.plan 仅作兜底，避免重复 toast/重复画线。
          if (event.plan && !sawPlan) current.onPlan?.(event.plan);
          if (reply) current.onAssistant?.(reply);
          if (event.summary || typeof event.turn_count === 'number') {
            current.onMeta?.({ summary: event.summary, turnCount: event.turn_count });
          }
          finish();
          break;
        }
        default:
          break;
      }
    };

    abortRef.current = streamSession(input as HarnessTurnInput, {
      onEvent: handle,
      onDone: (result) => {
        if (sawDone) return;
        if (!result.done || result.failed) {
          optionsRef.current.onError?.(result.error || '回复未完整返回，请重试。');
          finish();
        }
      },
    });
    return true;
  }, [finish]);

  const cancel = useCallback(() => {
    abortRef.current?.();
    finish();
  }, [finish]);

  return { running, streamText, status, send, cancel };
}
