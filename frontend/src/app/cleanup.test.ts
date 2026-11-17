import { describe, expect, it } from 'vitest';

const codeFiles = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.*'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const cssFiles = import.meta.glob('../**/*.css', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('工程护栏', () => {
  it('不在源码里使用浏览器原生 confirm / prompt / alert', () => {
    const offenders = Object.entries(codeFiles)
      .filter(([, source]) => /window\.(confirm|prompt|alert)\(/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it('CSS 里使用的自定义属性都有定义或兜底值', () => {
    const css = Object.values(cssFiles).join('\n');
    const defined = new Set([...css.matchAll(/(--[\w-]+)\s*:/g)].map(match => match[1]));
    const missing = [...css.matchAll(/var\(\s*(--[\w-]+)\s*(,)?/g)]
      .filter(match => !match[2] && !defined.has(match[1]))
      .map(match => match[1]);
    expect([...new Set(missing)]).toEqual([]);
  });

  it('路由页面包在错误边界里', () => {
    const shell = Object.entries(codeFiles).find(([path]) => path.includes('AppShell.tsx'))?.[1] ?? '';
    expect(Object.keys(codeFiles).length).toBeGreaterThan(0);
    expect(shell).toContain('<ErrorBoundary');
    expect(shell).toContain('renderRoute()');
  });
});
