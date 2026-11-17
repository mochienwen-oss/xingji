import { useEffect, useState } from 'react';
import { loadAppConfig } from './config';

/** 部署时通过 /api/config 下发的公开运营主体信息；未配置时保持演示版文案。 */
export type OperatorInfo = {
  name: string;
  contact_email: string;
  jurisdiction: string;
  icp_number: string;
};

export const EMPTY_OPERATOR: OperatorInfo = Object.freeze({
  name: '',
  contact_email: '',
  jurisdiction: '',
  icp_number: '',
});

let pending: Promise<OperatorInfo> | null = null;

export function normalizeOperator(value: unknown): OperatorInfo {
  if (!value || typeof value !== 'object') return EMPTY_OPERATOR;
  const raw = value as Partial<Record<keyof OperatorInfo, unknown>>;
  const text = (key: keyof OperatorInfo) =>
    typeof raw[key] === 'string' ? (raw[key] as string).trim() : '';
  return {
    name: text('name'),
    contact_email: text('contact_email'),
    jurisdiction: text('jurisdiction'),
    icp_number: text('icp_number'),
  };
}

/** 同一个页面生命周期内只请求一次 /api/config，失败时安静回退到演示版。 */
export function loadOperatorInfo(): Promise<OperatorInfo> {
  if (!pending) {
    pending = loadAppConfig()
      .then((config) => normalizeOperator(config.operator))
      .catch(() => EMPTY_OPERATOR);
  }
  return pending;
}

export function useOperatorInfo(): OperatorInfo {
  const [info, setInfo] = useState<OperatorInfo>(EMPTY_OPERATOR);
  useEffect(() => {
    let alive = true;
    loadOperatorInfo().then((value) => {
      if (alive) setInfo(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  return info;
}
