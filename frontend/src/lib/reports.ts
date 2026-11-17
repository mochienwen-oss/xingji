import { api } from './api';

/** 与后端 REPORT_REASONS 一一对应；展示文案由 ReportDialog 按语言映射。 */
export const REPORT_REASONS = ['虚假信息', '违法违规', '侵犯隐私', '垃圾广告', '其他'] as const;

export type ReportReason = (typeof REPORT_REASONS)[number];

export type ReportResult = {
  ok: boolean;
  duplicate: boolean;
  id: number;
  message: string;
};

function submit(path: string, reason: ReportReason, detail: string) {
  return api<ReportResult>(path, {
    method: 'POST',
    body: JSON.stringify({ reason, detail: detail.trim() }),
    timeoutMs: 12000,
  });
}

/** 举报公开广场里的行程；仅已公开的行程可举报。 */
export function reportTrip(tripId: number, reason: ReportReason, detail = '') {
  return submit('/trips/' + tripId + '/report', reason, detail);
}

/** 举报分享链接打开的行程；私密分享也能举报。 */
export function reportShare(token: string, reason: ReportReason, detail = '') {
  return submit('/shares/' + encodeURIComponent(token) + '/report', reason, detail);
}

export type ReportTarget = { kind: 'trip'; id: number } | { kind: 'share'; token: string };

export function sendReport(target: ReportTarget, reason: ReportReason, detail = '') {
  return target.kind === 'trip'
    ? reportTrip(target.id, reason, detail)
    : reportShare(target.token, reason, detail);
}
