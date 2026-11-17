import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportDialog } from './ReportDialog';

const sendReport = vi.hoisted(() => vi.fn());

vi.mock('../lib/reports', async importOriginal => {
  const actual = await importOriginal<typeof import('../lib/reports')>();
  return { ...actual, sendReport };
});

const onClose = vi.fn();

function renderDialog(lang: 'zh' | 'en' = 'zh') {
  render(
    <ReportDialog
      open
      target={{ kind: 'trip', id: 7 }}
      onClose={onClose}
      lang={lang}
    />,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe('ReportDialog 举报弹层', () => {
  it('提交时带上问题类型与补充说明，成功后显示核查提示', async () => {
    const user = userEvent.setup();
    sendReport.mockResolvedValue({ ok: true, duplicate: false, id: 3, message: '已收到举报' });
    renderDialog();

    await user.selectOptions(screen.getByLabelText('问题类型'), '垃圾广告');
    await user.type(screen.getByLabelText('补充说明（可选）'), '  这是广告。 ');
    await user.click(screen.getByRole('button', { name: '提交举报' }));

    await waitFor(() =>
      expect(sendReport).toHaveBeenCalledWith({ kind: 'trip', id: 7 }, '垃圾广告', '  这是广告。 '),
    );
    expect(await screen.findByRole('status')).toHaveTextContent('已收到举报，我们会在 24 小时内核查。');
    expect(screen.queryByRole('button', { name: '提交举报' })).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('同一份行程重复举报时给出已举报提示', async () => {
    const user = userEvent.setup();
    sendReport.mockResolvedValue({ ok: true, duplicate: true, id: 3, message: '已收到举报' });
    renderDialog();

    await user.click(screen.getByRole('button', { name: '提交举报' }));

    expect(await screen.findByRole('status')).toHaveTextContent('你已经举报过这份行程');
  });

  it('提交失败时保留内容并显示可读错误', async () => {
    const user = userEvent.setup();
    sendReport.mockRejectedValue(new Error('网络不太稳定，请稍后重试。'));
    renderDialog();

    await user.type(screen.getByLabelText('补充说明（可选）'), '地点信息有误');
    await user.click(screen.getByRole('button', { name: '提交举报' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('网络不太稳定，请稍后重试。');
    expect(screen.getByLabelText('补充说明（可选）')).toHaveValue('地点信息有误');
    expect(screen.getByRole('button', { name: '提交举报' })).toBeEnabled();
  });

  it('父组件重渲染导致 target 对象变化时，不清空已输入的补充说明', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ReportDialog open target={{ kind: 'trip', id: 7 }} onClose={onClose} />,
    );

    await user.type(screen.getByLabelText('补充说明（可选）'), '已经写好的描述');
    rerender(<ReportDialog open target={{ kind: 'trip', id: 7 }} onClose={onClose} />);

    expect(screen.getByLabelText('补充说明（可选）')).toHaveValue('已经写好的描述');
  });

  it('英文界面把中文理由值翻译成英文显示，但提交仍是后端约定的中文值', async () => {
    const user = userEvent.setup();
    sendReport.mockResolvedValue({ ok: true, duplicate: false, id: 4, message: 'ok' });
    renderDialog('en');

    expect(screen.getByRole('heading', { name: 'Report this trip' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Privacy violation' })).toHaveValue('侵犯隐私');
    await user.selectOptions(screen.getByLabelText('Issue type'), '侵犯隐私');
    await user.click(screen.getByRole('button', { name: 'Submit report' }));

    await waitFor(() =>
      expect(sendReport).toHaveBeenCalledWith({ kind: 'trip', id: 7 }, '侵犯隐私', ''),
    );
    expect(await screen.findByRole('status')).toHaveTextContent('Report received.');
  });
});
