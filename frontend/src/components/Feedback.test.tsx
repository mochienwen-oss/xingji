import { describe, expect, it } from 'vitest';
import { buildFeedbackMailto, FEEDBACK_MESSAGE_LIMIT } from './Feedback';

function parse(mailto: string) {
  const [head, query = ''] = mailto.split('?');
  const params = new URLSearchParams(query);
  return { to: head.replace('mailto:', ''), subject: params.get('subject') || '', body: params.get('body') || '' };
}

describe('buildFeedbackMailto', () => {
  it('带上反馈内容、版本、页面和浏览器信息', () => {
    const { to, subject, body } = parse(buildFeedbackMailto({
      email: 'help@xingji.app',
      kind: '行程内容有误',
      message: '  西湖的开放时间不对。  ',
      contact: 'traveler@example.com',
      version: '9.9.9',
      page: 'http://127.0.0.1:8000/#/trips/1',
      userAgent: 'TestBrowser/1.0',
      username: 'alice',
    }));

    expect(to).toBe('help@xingji.app');
    expect(subject).toContain('行程内容有误');
    expect(subject).toContain('alice');
    expect(body).toContain('西湖的开放时间不对。');
    expect(body).toContain('版本：行迹 Trip 9.9.9');
    expect(body).toContain('页面：http://127.0.0.1:8000/#/trips/1');
    expect(body).toContain('浏览器：TestBrowser/1.0');
    expect(body).toContain('联系方式：traveler@example.com');
    expect(body).not.toContain(' 西湖');
  });

  it('没有选填信息时也给出明确占位', () => {
    const { body } = parse(buildFeedbackMailto({
      email: 'help@xingji.app',
      kind: '功能建议',
      message: '希望支持导出 PDF。',
    }));
    expect(body).toContain('联系方式：未填写');
    expect(body).toContain('账号：未登录');
  });

  it('内容上限保持有限长度，避免邮件客户端截断', () => {
    expect(FEEDBACK_MESSAGE_LIMIT).toBeLessThanOrEqual(2000);
  });
});
