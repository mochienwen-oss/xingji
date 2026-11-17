/** 只清理行迹写在浏览器里的键，不动同域其它应用的数据。 */
export function clearXingjiStorage(): void {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    try {
      const keys: string[] = [];
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key?.startsWith('xingji')) keys.push(key);
      }
      for (const key of keys) storage.removeItem(key);
    } catch {
      // 隐私模式或站点数据被禁用时访问 storage 会抛错，清理失败不应阻断登出/注销。
    }
  }
}
