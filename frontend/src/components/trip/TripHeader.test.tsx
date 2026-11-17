import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TripHeader } from './TripHeader';

const baseProps = {
  title: '杭州半日慢走',
  collaborators: [
    { user_id: 1, username: 'qa-nav', role: 'owner' },
    { user_id: 2, username: 'qa-mate', role: 'editor' },
  ],
  syncState: 'synced' as const,
  optimizeVisible: true,
  optimizeAvailable: true,
  optimizeBusy: false,
  onBack: vi.fn(),
  onRename: vi.fn(),
  onMembers: vi.fn(),
  onMenuAction: vi.fn(),
};

describe('TripHeader', () => {
  it('exposes the trip title as the page heading', () => {
    render(<TripHeader {...baseProps} />);
    expect(screen.getByRole('heading', { level: 1, name: '杭州半日慢走' })).toBeInTheDocument();
  });

  it('keeps the title button as the rename affordance and the share slot accessible', () => {
    const onRename = vi.fn();
    render(
      <TripHeader
        {...baseProps}
        onRename={onRename}
        shareSlot={<button type="button" aria-label="分享行程">分享</button>}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '重命名行程：杭州半日慢走' }));
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '分享行程' })).toBeInTheDocument();
  });

  it('hides owner-only rename and delete from collaborators', () => {
    render(<TripHeader {...baseProps} canManage={false} />);
    expect(screen.queryByRole('button', { name: '重命名行程：杭州半日慢走' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    expect(screen.getByRole('menuitem', { name: '预算' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: '删除行程' })).not.toBeInTheDocument();
  });

  it('opens the menu and closes it with Escape', () => {
    const onMenuAction = vi.fn();
    render(<TripHeader {...baseProps} onMenuAction={onMenuAction} />);
    const more = screen.getByRole('button', { name: '更多操作' });
    fireEvent.click(more);
    expect(more).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(more).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(more);
    fireEvent.click(screen.getByRole('menuitem', { name: '预算' }));
    expect(onMenuAction).toHaveBeenCalledWith('budget');
  });
});
