import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { coverGlyph, coverMotif, coverTone } from '../../lib/cover';
import { CompassIcon } from '../icons';
import { TripCover } from '../trip/TripCover';
import { Button } from './Button';
import { Checkbox } from './Checkbox';
import { Chip } from './Chip';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { IconButton } from './IconButton';
import { PasswordField } from './PasswordField';
import { SegmentedControl } from './SegmentedControl';
import { TextField } from './TextField';

const viewOptions: Array<{ value: 'overview' | 'day'; label: string }> = [
  { value: 'overview', label: '总览' },
  { value: 'day', label: '每日' },
];

describe('Button', () => {
  it('renders primary button and blocks clicks while loading', () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>保存</Button>);
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('calls onClick when it is not loading', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>保存</Button>);
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('keeps an external className on the button', () => {
    render(<Button className="from-caller">出发</Button>);
    expect(screen.getByRole('button', { name: '出发' })).toHaveClass('from-caller');
  });
});

describe('TextField', () => {
  it('links label, hint and error to the input', () => {
    render(<TextField label="邮箱" hint="用于找回密码" error="邮箱格式不对" />);
    const input = screen.getByLabelText('邮箱');
    expect(input).toHaveAccessibleDescription('用于找回密码 邮箱格式不对');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });

  it('only links the hint when there is no error', () => {
    render(<TextField label="昵称" hint="最多 12 个字" />);
    expect(screen.getByLabelText('昵称')).toHaveAccessibleDescription('最多 12 个字');
    expect(screen.getByLabelText('昵称')).not.toHaveAttribute('aria-invalid');
  });
});

describe('PasswordField', () => {
  it('toggles visibility and reports state with aria-pressed', () => {
    render(<PasswordField label="密码" />);
    const input = screen.getByLabelText('密码') as HTMLInputElement;
    expect(input.type).toBe('password');

    const show = screen.getByRole('button', { name: '显示密码' });
    expect(show).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(show);
    expect(input.type).toBe('text');

    const hide = screen.getByRole('button', { name: '隐藏密码' });
    expect(hide).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(hide);
    expect(input.type).toBe('password');
  });
});

describe('SegmentedControl', () => {
  it('moves segmented selection with arrow keys', () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl label="行程视图" value="day" options={viewOptions} onChange={onChange} />,
    );
    fireEvent.keyDown(screen.getByRole('tab', { name: '总览' }), { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith('day');
  });

  it('wraps with ArrowLeft and uses roving tabindex', () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl label="行程视图" value="overview" options={viewOptions} onChange={onChange} />,
    );
    fireEvent.keyDown(screen.getByRole('tab', { name: '总览' }), { key: 'ArrowLeft' });
    expect(onChange).toHaveBeenCalledWith('day');
    expect(screen.getByRole('tab', { name: '总览' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tab', { name: '每日' })).toHaveAttribute('tabindex', '-1');
  });

  it('selects on click', () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl label="行程视图" value="overview" options={viewOptions} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole('tab', { name: '每日' }));
    expect(onChange).toHaveBeenCalledWith('day');
  });
});

describe('IconButton', () => {
  it('exposes an icon-only control by label', () => {
    render(
      <IconButton label="返回">
        <CompassIcon />
      </IconButton>,
    );
    expect(screen.getByRole('button', { name: '返回' })).toBeInTheDocument();
  });
});

describe('Checkbox', () => {
  it('toggles from the label and describes the hint', () => {
    render(<Checkbox label="记住我" hint="仅在本设备" />);
    const box = screen.getByRole('checkbox', { name: /记住我/ });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(box).toBeChecked();
    expect(box).toHaveAccessibleDescription('仅在本设备');
  });
});

describe('Chip', () => {
  it('exposes selection with aria-pressed', () => {
    render(<Chip selected>杭州</Chip>);
    expect(screen.getByRole('button', { name: '杭州' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('EmptyState / ErrorState', () => {
  it('renders one primary action for an empty state', () => {
    render(
      <EmptyState
        kicker="还没有行程"
        title="从一条路线开始"
        body="选一个城市，说说想怎么玩。"
        action={<Button>从地图开始</Button>}
      />,
    );
    expect(screen.getByRole('heading', { level: 2, name: '从一条路线开始' })).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('offers a single retry action for an error', () => {
    const onRetry = vi.fn();
    render(<ErrorState body="地图暂时没加载出来" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent('地图暂时没加载出来');
  });
});

describe('TripCover', () => {
  it('renders a deterministic typographic cover for a city', () => {
    const { container } = render(<TripCover city="杭州" days={2} />);
    expect(container.textContent).toContain('杭州');
    expect(coverTone('杭州')).toBe(coverTone('杭州'));
  });

  it('derives a deterministic glyph and a regional motif from the city', () => {
    expect(coverGlyph('杭州市')).toBe('杭');
    expect(coverGlyph('new york')).toBe('N');
    expect(coverMotif('杭州')).toBe('garden');
    expect(coverMotif('三亚')).toBe('coast');
    expect(coverMotif('敦煌')).toBe('dunes');
    expect(coverMotif('哈尔滨')).toBe('snow');
  });

  it('derives the tone from the city and never uses network images', () => {
    const { container } = render(<TripCover city="杭州" dateRange="11月5日–11月7日" />);
    const tone = coverTone('杭州');
    expect(tone).toBeGreaterThanOrEqual(0);
    expect(tone).toBeLessThanOrEqual(4);
    expect(container.firstElementChild).toHaveAttribute('data-tone', String(tone));
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('11月5日–11月7日');
  });
});
