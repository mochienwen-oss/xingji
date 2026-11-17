export type ClassValue = string | false | null | undefined;

/** 合并 className：过滤空值，保留外部 className 的最后优先级（由调用方传入，样式表不依赖顺序）。 */
export function cx(...values: ClassValue[]): string {
  return values.filter(Boolean).join(' ');
}
