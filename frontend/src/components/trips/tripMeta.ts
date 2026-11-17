import type { TripSummary } from '../../types/trip';

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const ISO_DATE = /^(\d{4})-(\d{1,2})-(\d{1,2})/;

/** 列表里显示的行程名：作者起过名就用名字，否则用城市兜底。 */
export function tripName(trip: { city: string; title?: string | null }): string {
  return trip.title?.trim() || trip.city + '旅行计划';
}

/**
 * 后端 start_date 是 YYYY-MM-DD。
 * 直接 new Date('2026-11-05') 会按 UTC 解析、在东八区显示成前一天，
 * 所以这里拆成年月日再按本地日历构造。
 */
export function formatTripDate(value: string | null | undefined): string {
  if (!value) return '';
  const match = ISO_DATE.exec(value.trim());
  if (!match) return value;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  if (Number.isNaN(date.getTime())) return value;
  return Number(match[2]) + '月' + Number(match[3]) + '日 ' + WEEKDAYS[date.getDay()];
}

/** 卡片第二行：城市 · 天数 · 日期（没有日期就说待定）。 */
export function summaryMeta(trip: TripSummary): string {
  const days = trip.request?.days;
  const date = formatTripDate(trip.request?.start_date);
  return [trip.city, typeof days === 'number' && days > 0 ? days + ' 天' : '', date || '日期待定']
    .filter(Boolean)
    .join(' · ');
}
