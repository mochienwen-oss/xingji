import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useRetryOnActivate } from './useRetryOnActivate';

function setup(props: { active: boolean; shouldRetry: boolean; retry: () => void }) {
  return renderHook(
    (next: { active: boolean; shouldRetry: boolean; retry: () => void }) => useRetryOnActivate(next.active, next.shouldRetry, next.retry),
    { initialProps: props },
  );
}

describe('useRetryOnActivate', () => {
  it('retries immediately when the page is active and already failed', () => {
    const retry = vi.fn();
    setup({ active: true, shouldRetry: true, retry });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('waits for the page to become active again before retrying', () => {
    const retry = vi.fn();
    const { rerender } = setup({ active: false, shouldRetry: true, retry });
    expect(retry).not.toHaveBeenCalled();

    rerender({ active: true, shouldRetry: true, retry });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('does nothing while the load is healthy, then retries when it fails', () => {
    const retry = vi.fn();
    const { rerender } = setup({ active: true, shouldRetry: false, retry });
    expect(retry).not.toHaveBeenCalled();

    rerender({ active: true, shouldRetry: true, retry });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('does not loop when the retry fails and the flags stay the same', () => {
    const retry = vi.fn();
    const { rerender } = setup({ active: true, shouldRetry: true, retry });
    expect(retry).toHaveBeenCalledTimes(1);

    rerender({ active: true, shouldRetry: true, retry });
    rerender({ active: true, shouldRetry: true, retry });
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('calls the latest retry callback when it becomes active again', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = setup({ active: false, shouldRetry: true, retry: first });

    rerender({ active: true, shouldRetry: true, retry: second });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
