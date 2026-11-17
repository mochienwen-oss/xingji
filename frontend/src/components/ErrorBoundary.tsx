import React from "react";

type State = {error:Error|null};

/** 顶层错误边界：任何渲染异常都不该让整段未保存的旅程与聊天凭空消失（审计 P0-1）。 */
export class ErrorBoundary extends React.Component<{children:React.ReactNode},State> {
  state:State={error:null};
  static getDerivedStateFromError(error:Error):State{return {error}}
  componentDidCatch(error:Error,info:React.ErrorInfo){console.error('[行迹] 渲染异常',error,info.componentStack)}
  render(){
    if(!this.state.error)return this.props.children;
    return <div className="crash-screen" role="alert">
      <div className="crash-card">
        <span className="crash-kicker">行迹 · 遇到一点意外</span>
        <h1>这一段旅程走丢了</h1>
        <p>页面没有正确渲染，但草稿仍保存在这台设备上。可以重新载入，或回到探索页继续。</p>
        <details className="crash-detail"><summary>查看错误信息</summary><code>{this.state.error.message||'未知渲染错误'}</code></details>
        <div className="crash-actions">
          <button type="button" className="primary" onClick={()=>window.location.reload()}>重新载入</button>
          <button type="button" className="secondary" onClick={()=>{window.history.replaceState(null,'',window.location.pathname+window.location.search);window.location.reload()}}>回到探索</button>
        </div>
      </div>
    </div>;
  }
}
