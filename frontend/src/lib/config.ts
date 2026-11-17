import { api } from './api';

/** /api/config 下发的公开部署配置；全应用共用一次请求，失败后允许下一次重试。 */
export type AppConfig = {
  amap_js_key?: string;
  amap_js_security_code?: string;
  support_email?: string;
  operator?: unknown;
};

let configPromise: Promise<AppConfig> | null = null;

export function loadAppConfig(): Promise<AppConfig> {
  if (!configPromise) {
    configPromise = api<AppConfig>('/config', { timeoutMs: 8000 }).catch((error: unknown) => {
      configPromise = null;
      throw error;
    });
  }
  return configPromise;
}
