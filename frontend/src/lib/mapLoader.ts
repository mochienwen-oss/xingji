import { loadAppConfig } from './config';

/** 高德 JS API 命名空间。第三方脚本没有类型包，这里保留 any 边界。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AmapNamespace = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AmapMap = any;

const SCRIPT_ID = 'amap-js-api';
const SCRIPT_TIMEOUT = 8000;
const POLL_INTERVAL = 120;

let amapPromise: Promise<AmapNamespace> | null = null;

/**
 * 全应用只插一次 script#amap-js-api；两个探索地图同时挂载时共用同一个 Promise。
 * 失败会移除坏脚本并清空缓存，重试时重新加载。
 */
function loadScript(key: string, security: string): Promise<AmapNamespace> {
  return new Promise((resolve, reject) => {
    window._AMapSecurityConfig = { securityJsCode: security };
    let script = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (!script) {
      script = document.createElement('script');
      script.id = SCRIPT_ID;
      script.async = true;
      script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
      document.head.appendChild(script);
    }

    const node = script;
    const started = Date.now();
    let timer = 0;

    const stop = () => {
      window.clearInterval(timer);
      node.onerror = null;
    };
    const fail = (text: string) => {
      stop();
      node.parentNode?.removeChild(node);
      reject(new Error(text));
    };

    node.onerror = () => fail('地图加载失败，请检查网络后重试');
    timer = window.setInterval(() => {
      if (window.AMap) {
        stop();
        resolve(window.AMap);
        return;
      }
      if (Date.now() - started > SCRIPT_TIMEOUT) fail('地图加载超时，请重试');
    }, POLL_INTERVAL);
  });
}

/** 返回 window.AMap 构造函数；配置、脚本与并发请求都走模块级单例。 */
export function loadAmap(): Promise<AmapNamespace> {
  if (typeof window !== 'undefined' && window.AMap) return Promise.resolve(window.AMap);
  if (amapPromise) return amapPromise;

  amapPromise = loadAppConfig().then((config) => {
    // loadAppConfig 的成功响应会永久缓存，缺密钥时重试也不会真的再取一次 /config。
    if (!config?.amap_js_key) throw new Error('配置高德地图密钥后显示地图');
    return loadScript(config.amap_js_key, config.amap_js_security_code || '');
  });
  amapPromise.catch(() => {
    amapPromise = null;
  });
  return amapPromise;
}
