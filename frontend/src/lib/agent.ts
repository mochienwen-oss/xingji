/** 行迹 agent 流式客户端：消费后端 /assistant/stream 的 SSE 事件。
 *
 * 事件协议（与 backend/services/agent/state.py 的 event(kind) 对齐）：
 *  status      {phase,text}     节点级播报（understand/plan/route）
 *  tool_start  {tool,keyword?,text}   工具开始（含拟人文案）
 *  tool_result {tool,keyword?,count?,changed?,text}  工具结果
 *  pin         {place}          新地点落针（地图逐个出现）
 *  day_done    {day,stops}      某天规划完成（总览逐日点亮）
 *  route_seg   {day,origin,destination,duration,distance}  路线逐段
 *  done        {days,backlog,reply,changed}  最终建议
 *  saved       {version}        持久化完成
 *  error       {message}
 */
import type {Place,PlanRequest,Trip} from '../types/trip';
import {streamSse} from './sse';

export type AgentEvent =
  | {kind: 'delta'; text: string; reset?: boolean}
  | {kind: 'status'; phase: string; text: string}
  | {kind: 'tool_start'; tool: string; keyword?: string; text: string}
  | {kind: 'tool_result'; tool: string; keyword?: string; count?: number; changed?: boolean; text: string}
  | {kind: 'pin'; place: Place}
  | {kind: 'day_done'; day: number; stops: {id: string; name: string}[]}
  | {kind: 'route_seg'; day: number; origin: string; destination: string; duration: number|null; distance: number|null; polyline: number[][][]}
  | {kind: 'done'; days: unknown; backlog: unknown; reply: string; changed: boolean}
  | {kind: 'saved'; version: number}
  | {kind: 'error'; message: string};

export type AgentHandlers = {
  onEvent?: (event: AgentEvent) => void;
  onDone?: (payload: {days?: unknown; backlog?: unknown; reply?: string; changed?: boolean; version?: number; error?: string; needsRefresh?: boolean}) => void;
};

type AgentResult = Parameters<NonNullable<AgentHandlers['onDone']>>[0];

function networkFailure(preview?: Trip): {error: string; needsRefresh?: boolean} {
  return preview
    ? {error: '连接中断，请重试。'}
    : {error: '连接中断，对话可能已保存。请重新打开行程核对后再决定是否重发。', needsRefresh: true};
}

/** 触发一次流式行程助手会话；返回取消函数。 */
export function streamAssistant(tripId: number, body: {message: string; history: {role: string; content: string}[]; version: number; preview?: Trip},
                               handlers: AgentHandlers = {}): () => void {
  const preview = body.preview;
  let result: AgentResult = {};
  let doneEvent = false;
  let savedEvent = false;
  return streamSse<AgentEvent>({
    url: preview ? '/api/planning/preview/assistant/stream' : `/api/trips/${tripId}/assistant/stream`,
    body: preview ? {message:body.message,history:body.history,request:preview.request,days:preview.days,backlog:preview.backlog||[],place_notice:preview.place_notice||''} : body,
    onEvent: event => {
      if (event.kind === 'done') {
        doneEvent = true;
        result = {...result, days:event.days, backlog:event.backlog, reply:event.reply, changed:event.changed};
      } else if (event.kind === 'saved') {
        savedEvent = true;
        result = {...result, version:event.version};
      } else if (event.kind === 'error') {
        result = {...result, error:event.message, needsRefresh:!preview && doneEvent};
      }
      handlers.onEvent?.(event);
    },
    onError: error => {
      if (error.kind === 'http') {
        handlers.onDone?.({error: error.detail || '行程助手暂时不可用，请稍后再试。', needsRefresh: error.status === 409});
      } else {
        handlers.onDone?.(networkFailure(preview));
      }
    },
    onEnd: () => {
      if (!result.error && (!doneEvent || (!preview && !savedEvent))) {
        result.error = preview ? '结果未完整返回，请重试。' : '结果未完整返回，对话可能已保存。请重新打开行程核对后再决定是否重发。';
        result.needsRefresh = !preview;
      }
      handlers.onDone?.(result);
    },
  });
}

export function streamPlanningChat(body:{messages:{role:string;content:string}[];current:unknown},
  handlers:{onDelta:(text:string)=>void;onDone:(result?:{reply:string;updates:Partial<PlanRequest>;place_matches:{keyword:string;matches:Place[]}[];place_notice:string;intent?:string},error?:string)=>void}):()=>void {
  type ChatResult = Parameters<typeof handlers.onDone>[0];
  let result: ChatResult;
  let failure = '';
  return streamSse<ChatResult & {kind?: string; text?: string; message?: string}>({
    url: '/api/planning/chat/stream',
    body,
    onEvent: event => {
      if (event.kind === 'delta' && typeof event.text === 'string') handlers.onDelta(event.text);
      else if (event.kind === 'done') result = event;
      else if (event.kind === 'error') failure = event.message || '对话失败，请重试。';
    },
    onError: error => {
      if (error.kind === 'http') {
        handlers.onDone(undefined, error.detail ?? '对话服务暂时不可用，请稍后重试。');
      } else {
        handlers.onDone(undefined, error.cause instanceof Error ? error.cause.message : '连接中断，请重试。');
      }
    },
    onEnd: () => {
      handlers.onDone(failure ? undefined : result, failure || (!result ? '回复未完整返回，请重试。' : undefined));
    },
  });
}
