import { readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// jsdom 环境会替换全局 URL，这里用 node:url 从测试文件位置解析样式目录。
const stylesDir = dirname(fileURLToPath(import.meta.url));
const read = (name: string) => readFileSync(resolve(stylesDir, name), 'utf8');
// 字体真正对外提供的是 public/fonts（fonts.css 用根路径引用）；styles/fonts 旧副本已清理。
const statPublicFont = (name: string) => statSync(resolve(stylesDir, '../../public/fonts', name)).size;
const css = read('tokens.css');
const fontCss = read('fonts.css');

describe('D3 tokens', () => {
  it('uses the approved palette', () => {
    expect(css).toContain('--color-paper: #F6F2EA');
    expect(css).toContain('--color-ink: #17120E');
    expect(css).toContain('--color-accent: #A8342A');
    expect(css).toContain('--color-indigo: #1D3557');
  });

  it('uses the D3 shape, motion and keyboard tokens', () => {
    expect(css).toContain('--radius-card: 4px');
    expect(css).toContain('--shadow-card: none');
    expect(css).toContain('--radius-sheet: 16px');
    expect(css).toContain('--dur-sheet: 320ms');
    expect(css).toContain('--ease-out: cubic-bezier(.2,.8,.2,1)');
    expect(css).toContain('--kb-inset: 0px');
  });
});

describe('self-hosted serif', () => {
  it('declares 400 and 700 with font-display swap', () => {
    expect(fontCss.match(/@font-face/g) ?? []).toHaveLength(2);
    expect(fontCss).toContain('font-weight: 400');
    expect(fontCss).toContain('font-weight: 700');
    expect(fontCss.match(/font-display: swap/g) ?? []).toHaveLength(2);
    expect(fontCss).toContain('url("/fonts/NotoSerifSC-Regular.woff2")');
    expect(fontCss).toContain('url("/fonts/NotoSerifSC-Bold.woff2")');
  });

  it('keeps the woff2 payload under 3MB', () => {
    expect(statPublicFont('NotoSerifSC-Regular.woff2') + statPublicFont('NotoSerifSC-Bold.woff2')).toBeLessThan(3 * 1024 * 1024);
  });
});
