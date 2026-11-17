import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Conversation } from './Conversation';

describe('Conversation', () => {
  it('助手已经流式输出后仍显示检索进度', () => {
    render(
      <Conversation
        messages={[{ role: 'user', content: '杭州两天' }]}
        streaming="好，我按两天轻松节奏排一版。"
        busy
        status="正在检索杭州的真实地点"
      />,
    );
    expect(screen.getByText('正在检索杭州的真实地点')).toBeInTheDocument();
  });

  it('生成中可以停止', async () => {
    const onCancel = vi.fn();
    render(
      <Conversation messages={[]} streaming="" busy status="正在规划" onCancel={onCancel} />,
    );
    await userEvent.click(screen.getByRole('button', { name: '停止生成' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('消息区域声明为 role="log"，读屏器不会逐 token 打断', () => {
    render(<Conversation messages={[{role: 'user', content: '杭州两天'}]} streaming="好" busy status="" />);
    const log = screen.getByRole('log', {name: '规划对话'});
    expect(log).toHaveTextContent('杭州两天');
  });

  it('还没有输出时用打字气泡显示状态', () => {
    render(
      <Conversation
        messages={[{ role: 'user', content: '杭州两天' }]}
        streaming=""
        busy
        status="正在理解你的需求…"
      />,
    );
    expect(screen.getAllByText('正在理解你的需求…').length).toBeGreaterThan(0);
  });
});
