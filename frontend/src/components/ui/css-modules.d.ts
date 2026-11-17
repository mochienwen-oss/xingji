/// <reference types="vite/client" />
// CSS Modules 的类型来自 vite/client（*.module.css -> Record<string, string>）。
// 放在本任务目录下，避免改动 F1 的 tsconfig；后续任务若新增 vite-env.d.ts 引用同一份类型即可，不会冲突。
