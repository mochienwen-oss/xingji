import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamAssistant, type AgentEvent } from './agent';

type StreamResult = {
  days?: unknown;
  backlog?: unknown;
  reply?: string;
  changed?: boolean;
  version?: number;
  error?: string;
  needsRefresh?: boolean;
};

/** 把后端 SSE 事件序列编码成按字节切碎的响应流，模拟真实网络分片。 */
function sseChunks(events: unknown[], cut = 11): Uint8Array[] {
  const bytes = new TextEncoder().encode(events.map(value => `data: ${JSON.stringify(value)}\n\n`).join(''));
  const chunks: Uint8Array[] = [];
  for (let offset = 0; offset < bytes.length; offset += cut) chunks.push(bytes.slice(offset, offset + cut));
  return chunks;
}

function stubFetch(response: () => Response) {
  vi.stubGlobal('fetch', vi.fn(async () => response()));
}

function streamOf(events: unknown[], cut = 11): Response {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of sseChunks(events, cut)) controller.enqueue(chunk);
      controller.close();
    },
  }), { status: 200 });
}

function run(events: unknown[], cut = 11) {
  stubFetch(() => streamOf(events, cut));
  const received: AgentEvent['kind'][] = [];
  return new Promise<{ received: AgentEvent['kind'][]; result: StreamResult }>(resolve => {
    streamAssistant(1, { message: '调整', history: [], version: 0 }, {
      onEvent: event => received.push(event.kind),
      onDone: result => resolve({ received, result }),
    });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamAssistant', () => {
  it('delivers fragmented events and the final suggestion with the saved version', async () => {
    const { received, result } = await run([
      { kind: 'status', phase: 'plan', text: '正在规划' },
      { kind: 'done', days: [{ stops: [] }], backlog: [], reply: '建议调整', changed: true },
      { kind: 'saved', version: 3 },
    ]);
    expect(received).toEqual(['status', 'done', 'saved']);
    expect(result.reply).toBe('建议调整');
    expect(result.changed).toBe(true);
    expect(result.version).toBe(3);
    expect(result.days).toHaveLength(1);
  });

  it('reports errors and incomplete results instead of treating them as success', async () => {
    const failed = await run([{ kind: 'error', message: '路线失败' }]);
    expect(failed.result.error).toBe('路线失败');
    const incomplete = await run([{ kind: 'done', days: [], backlog: [], reply: '完成', changed: false }]);
    expect(incomplete.result.error).toMatch(/未完整返回/);
    expect(incomplete.result.needsRefresh).toBe(true);
  });

  it('requests an explicit refresh on version conflicts instead of treating retry as safe', async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: '行程已在其他操作中更新' }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }));
    const result = await new Promise<StreamResult>(resolve => {
      streamAssistant(1, { message: '调整', history: [], version: 0 }, { onDone: resolve });
    });
    expect(result.needsRefresh).toBe(true);
    expect(result.error).toMatch(/行程已在其他操作中更新/);
  });

  it('lets an unsaved preview finish without a saved event', async () => {
    stubFetch(() => streamOf([{ kind: 'done', days: [], backlog: [], reply: '完成', changed: false }]));
    const result = await new Promise<StreamResult>(resolve => {
      streamAssistant(0, { message: '调整', history: [], version: 0, preview: { request: {}, days: [], backlog: [] } as never }, { onDone: resolve });
    });
    expect(result.error).toBeUndefined();
    expect(result.reply).toBe('完成');
  });
});
