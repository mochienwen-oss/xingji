import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamSession, type HarnessEvent, type HarnessTurnInput } from './session';

type DoneResult = { done: boolean; failed: boolean; error?: string };

function frame(value: unknown): string {
  return `data: ${JSON.stringify(value)}\n\n`;
}

function stubStream(text: string) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  }), {status: 200})));
}

const input: HarnessTurnInput = {
  mode: 'explore',
  message: '去杭州',
  messages: [],
  form: {} as never,
  places: [],
  turnCount: 0,
};

function run(text: string): Promise<{ events: HarnessEvent[]; result: DoneResult }> {
  stubStream(text);
  const events: HarnessEvent[] = [];
  return new Promise(resolve => {
    streamSession(input, {
      onEvent: event => events.push(event),
      onDone: result => resolve({events, result}),
    });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamSession', () => {
  it('normalizes plan events and aggregates a clean done', async () => {
    const plan = {request: {city: '杭州'}, days: [], backlog: [], is_owner: false};
    const {events, result} = await run(
      frame({kind: 'status', text: '规划中'}) + frame({kind: 'plan', plan}) + frame({kind: 'done', reply: '好的'}),
    );
    const planEvent = events.find(event => event.kind === 'plan') as Extract<HarnessEvent, {kind: 'plan'}>;
    expect(planEvent.plan.id).toBe(0);
    expect(planEvent.plan.version).toBe(0);
    expect(planEvent.plan.is_owner).toBe(false);
    expect(result).toMatchObject({done: true, failed: false});
    expect(result.error).toBeUndefined();
  });

  it('normalizes the plan attached to a done event as a fallback', async () => {
    const {events} = await run(frame({kind: 'done', reply: '好的', plan: {request: {city: '苏州'}, days: []}}));
    const doneEvent = events.find(event => event.kind === 'done') as Extract<HarnessEvent, {kind: 'done'}>;
    expect(doneEvent.plan?.request).toEqual({city: '苏州'});
  });

  it('marks a done followed by an error as failed', async () => {
    const {result} = await run(frame({kind: 'done', reply: '好的'}) + frame({kind: 'error', message: '保存失败'}));
    expect(result).toEqual({done: true, failed: true, error: '保存失败'});
  });

  it('reports a stream that ends without done as incomplete', async () => {
    const {result} = await run(frame({kind: 'status', text: '规划中'}));
    expect(result.done).toBe(false);
    expect(result.failed).toBe(true);
    expect(result.error).toMatch(/未完整返回/);
  });

  it('passes the HTTP detail through on rejection', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({detail: '会话已过期'}), {
      status: 409,
      headers: {'Content-Type': 'application/json'},
    })));
    const result = await new Promise<DoneResult>(resolve => {
      streamSession(input, {onDone: resolve});
    });
    expect(result).toEqual({done: false, failed: true, error: '会话已过期'});
  });
});
