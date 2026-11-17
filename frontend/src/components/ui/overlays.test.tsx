import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { PageActiveProvider } from '../../app/providers/PageActiveProvider';
import { TOAST_DURATION, ToastProvider, useConfirm, useToast } from '../../app/providers/ToastProvider';
import { useBodyScrollLock } from '../../lib/useBodyScrollLock';
import {
  detentAfterDrag,
  nextDetent,
  releaseVelocity,
  shouldDismiss,
  type SheetDetent,
} from '../../lib/useSheetDrag';
import { useVisualViewport } from '../../lib/useVisualViewport';
import { ConfirmDialog } from './ConfirmDialog';
import { Dialog } from './Dialog';
import { Sheet } from './Sheet';

// jsdom 不做布局，任何元素尺寸都是 0；useFocusTrap 的可见性过滤会因此漏掉按钮。
// 只在本文件把 offsetWidth 打桩成 1，让焦点陷阱与浏览器里的判断一致。
const originalOffsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get: () => 1,
  });
});

afterAll(() => {
  if (originalOffsetWidth) {
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', originalOffsetWidth);
    return;
  }
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).offsetWidth;
});

beforeEach(() => {
  document.body.removeAttribute('style');
});

describe('useSheetDrag 吸附', () => {
  it('速度够快时按方向跨一档', () => {
    expect(nextDetent('half', -900)).toBe('full');
    expect(nextDetent('half', 900)).toBe('peek');
    expect(nextDetent('half', -120)).toBe('half');
    expect(nextDetent('peek', 900)).toBe('peek');
    expect(nextDetent('full', -900)).toBe('full');
  });

  it('速度不够时按位移与方向决定', () => {
    expect(detentAfterDrag('half', 240, 480)).toBe('peek');
    expect(detentAfterDrag('half', -60, 480)).toBe('full');
    expect(detentAfterDrag('half', 20, 480)).toBe('half');
  });

  it('只有 peek 下拉够远才直接关闭', () => {
    expect(shouldDismiss('peek', 80, 0, 112)).toBe(true);
    expect(shouldDismiss('peek', 80, 900, 112)).toBe(true);
    expect(shouldDismiss('peek', 10, 0, 112)).toBe(false);
    expect(shouldDismiss('half', 900, 900, 480)).toBe(false);
  });

  it('松手速度只回看最近 100ms', () => {
    const samples = [
      { y: 0, at: 900 },
      { y: 60, at: 1000 },
    ];
    expect(releaseVelocity(samples, 1000)).toBeCloseTo(600, 6);
    // 手指停住超过 100ms 再松手，不该沿用旧速度。
    expect(releaseVelocity([
      { y: 0, at: 700 },
      { y: 60, at: 800 },
    ], 1000)).toBe(0);
  });
});

type SheetHarnessProps = {
  open?: boolean;
  detent?: SheetDetent;
  onDetentChange?: (detent: SheetDetent) => void;
  onClose?: () => void;
};

function SheetHarness({ open = true, detent = 'half', onDetentChange, onClose }: SheetHarnessProps) {
  return (
    <Sheet
      open={open}
      detent={detent}
      onDetentChange={onDetentChange ?? (() => {})}
      onClose={onClose}
      labelledBy="sheet-title"
    >
      <h2 id="sheet-title">夜行地图</h2>
      <p>抽屉内容</p>
    </Sheet>
  );
}

describe('Sheet', () => {
  it('按 detent 渲染、带可访问名称，打开时锁滚动', () => {
    const onClose = vi.fn();
    render(<SheetHarness detent="half" onClose={onClose} />);

    const sheet = screen.getByRole('dialog', { name: '夜行地图' });
    expect(sheet).toHaveAttribute('data-detent', 'half');
    expect(sheet).toHaveAttribute('aria-modal', 'true');
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('关闭时移出可访问树并释放滚动锁', () => {
    render(<SheetHarness open={false} />);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
  });

  it('把手用方向键换档，最低档再按下才关闭', () => {
    const onDetentChange = vi.fn();
    const onClose = vi.fn();
    render(<SheetHarness detent="peek" onDetentChange={onDetentChange} onClose={onClose} />);

    const grabber = screen.getByRole('button', { name: '调整面板高度' });
    fireEvent.keyDown(grabber, { key: 'ArrowUp' });
    expect(onDetentChange).toHaveBeenCalledWith('half');

    fireEvent.keyDown(grabber, { key: 'ArrowDown' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('页面被路由收起时释放滚动锁，回来再锁上', () => {
    const { rerender } = render(
      <PageActiveProvider active>
        <SheetHarness />
      </PageActiveProvider>,
    );
    expect(document.body.style.overflow).toBe('hidden');

    rerender(
      <PageActiveProvider active={false}>
        <SheetHarness />
      </PageActiveProvider>,
    );
    expect(document.body.style.overflow).toBe('');

    rerender(
      <PageActiveProvider active>
        <SheetHarness />
      </PageActiveProvider>,
    );
    expect(document.body.style.overflow).toBe('hidden');
  });

  it('页面被路由收起时不响应 Escape', () => {
    const onClose = vi.fn();
    render(
      <PageActiveProvider active={false}>
        <SheetHarness onClose={onClose} />
      </PageActiveProvider>,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});

function DialogHarness({ busy = false, onClose }: { busy?: boolean; onClose: () => void }) {
  return (
    <Dialog open onClose={onClose} title="重命名" busy={busy}>
      <button type="button">取消</button>
      <button type="button">保存</button>
    </Dialog>
  );
}

describe('Dialog', () => {
  it('焦点进第一个可操作元素，Escape 关闭', () => {
    const onClose = vi.fn();
    render(<DialogHarness onClose={onClose} />);

    expect(screen.getByRole('dialog', { name: '重命名' })).toHaveAttribute('aria-modal', 'true');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '取消' }));

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Tab 在面板内正向/反向循环', () => {
    render(<DialogHarness onClose={() => {}} />);
    const cancel = screen.getByRole('button', { name: '取消' });
    const close = screen.getByRole('button', { name: '关闭' });

    close.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(cancel);

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(close);
  });

  it('busy 时 Escape 与关闭按钮都不生效', () => {
    const onClose = vi.fn();
    render(<DialogHarness busy onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();

    const close = screen.getByRole('button', { name: '关闭' });
    expect(close).toBeDisabled();
    fireEvent.click(close);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('页面被路由收起时不渲染 portal，也不锁滚动', () => {
    render(
      <PageActiveProvider active={false}>
        <DialogHarness onClose={() => {}} />
      </PageActiveProvider>,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
  });

  it('卸载后焦点回到触发元素', () => {
    const trigger = document.createElement('button');
    trigger.textContent = '打开弹层';
    document.body.appendChild(trigger);
    trigger.focus();

    const { unmount } = render(<DialogHarness onClose={() => {}} />);
    expect(document.activeElement).not.toBe(trigger);

    unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});

describe('ConfirmDialog', () => {
  it('取消在左、主行动在右，各自回调', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="删除旅行"
        body="删除后无法恢复。"
        confirmLabel="删除"
        danger
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const buttons = screen.getAllByRole('button');
    // 关闭图标按钮按 aria-label 取名，没有文本。
    expect(buttons.map(button => button.textContent)).toEqual(['取消', '删除', '']);

    fireEvent.click(buttons[1]);
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.click(buttons[0]);
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it('busy 时按钮禁用且 Escape 不关闭', () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        busy
        title="处理中"
        body="请稍候"
        confirmLabel="确定"
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled();
  });
});

function ToastDemo() {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toast('已保存', 'success')}>
      提示
    </button>
  );
}

function ToastRepeat() {
  const { toast } = useToast();
  return (
    <button
      type="button"
      onClick={() => {
        toast('已加入这一天');
        toast('已加入这一天');
      }}
    >
      重复
    </button>
  );
}

function ToastBurst() {
  const { toast } = useToast();
  return (
    <button
      type="button"
      onClick={() => {
        toast('一');
        toast('二');
        toast('三');
        toast('四');
      }}
    >
      连发
    </button>
  );
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('出现在 polite 区域并在 3 秒后消失', () => {
    render(
      <ToastProvider>
        <ToastDemo />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '提示' }));
    expect(screen.getByRole('region', { name: '通知' })).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByText('已保存')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(TOAST_DURATION - 1);
    });
    expect(screen.getByText('已保存')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText('已保存')).not.toBeInTheDocument();
  });

  it('队列最多 3 条，超出挤掉最早的', () => {
    render(
      <ToastProvider>
        <ToastBurst />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '连发' }));
    expect(screen.queryByText('一')).not.toBeInTheDocument();
    expect(screen.getByText('二')).toBeInTheDocument();
    expect(screen.getByText('四')).toBeInTheDocument();
  });

  it('相同内容的提示连发时只保留一条', () => {
    render(
      <ToastProvider>
        <ToastRepeat />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '重复' }));
    expect(screen.getAllByText('已加入这一天')).toHaveLength(1);
  });

  it('可手动关闭', () => {
    render(
      <ToastProvider>
        <ToastDemo />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '提示' }));
    fireEvent.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(screen.queryByText('已保存')).not.toBeInTheDocument();
  });
});

describe('useConfirm', () => {
  const captured: { promise?: Promise<boolean> } = {};

  function ConfirmDemo() {
    const confirm = useConfirm();
    return (
      <button
        type="button"
        onClick={() => {
          captured.promise = confirm({ title: '删除旅行', body: '删除后无法恢复。', confirmLabel: '删除' });
        }}
      >
        发起确认
      </button>
    );
  }

  it('确认返回 true，取消返回 false', async () => {
    render(
      <ToastProvider>
        <ConfirmDemo />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '发起确认' }));
    expect(screen.getByRole('dialog', { name: '删除旅行' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    await expect(captured.promise).resolves.toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '发起确认' }));
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    await expect(captured.promise).resolves.toBe(false);
  });
});

function LockProbe({ locked }: { locked: boolean }) {
  useBodyScrollLock(locked);
  return null;
}

describe('useBodyScrollLock', () => {
  it('锁定并恢复原来的 overflow 与 padding-right', () => {
    document.body.style.overflow = 'scroll';
    document.body.style.paddingRight = '4px';

    const { rerender, unmount } = render(<LockProbe locked />);
    expect(document.body.style.overflow).toBe('hidden');

    rerender(<LockProbe locked={false} />);
    expect(document.body.style.overflow).toBe('scroll');
    expect(document.body.style.paddingRight).toBe('4px');

    unmount();
  });

  it('引用计数：最后一个释放才恢复', () => {
    const { rerender } = render(<LockProbe locked />);
    rerender(
      <>
        <LockProbe locked />
        <LockProbe locked />
      </>,
    );
    expect(document.body.style.overflow).toBe('hidden');

    rerender(
      <>
        <LockProbe locked />
        <LockProbe locked={false} />
      </>,
    );
    expect(document.body.style.overflow).toBe('hidden');

    rerender(
      <>
        <LockProbe locked={false} />
        <LockProbe locked={false} />
      </>,
    );
    expect(document.body.style.overflow).toBe('');
  });
});

function ViewportProbe() {
  useVisualViewport();
  return null;
}

describe('useVisualViewport', () => {
  it('把键盘遮挡高度写进 --kb-inset 并在卸载时清理', () => {
    const innerHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight');
    const visualViewport = Object.getOwnPropertyDescriptor(window, 'visualViewport');
    const viewport = {
      height: 500,
      offsetTop: 42,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 });
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });

    const { unmount } = render(<ViewportProbe />);
    expect(document.documentElement.style.getPropertyValue('--kb-inset')).toBe('258px');

    unmount();
    expect(document.documentElement.style.getPropertyValue('--kb-inset')).toBe('');

    if (innerHeight) Object.defineProperty(window, 'innerHeight', innerHeight);
    if (visualViewport) Object.defineProperty(window, 'visualViewport', visualViewport);
    else delete (window as unknown as Record<string, unknown>).visualViewport;
  });
});
