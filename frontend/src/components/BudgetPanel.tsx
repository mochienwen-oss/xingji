import React, { useEffect, useRef, useState } from 'react';
import { api, message } from '../lib/api';

type Expense = {id:number;amount_cents:number;category:string;expense_date:string;place_id?:string|null;note?:string|null};
type Budget = {amount_cents:number|null;expenses:Expense[]};
type EstimateItem = {category:string;low:number;high:number;assumption:string};
type Draft = {amount:string;category:string;date:string;note:string};

const CATEGORIES=['餐饮','交通','住宿','门票','其他'];
const UNDO_MS=6000;
/** AI 估算 10 分钟后标为过期，提醒用户按最新行程重新估算。 */
const ESTIMATE_TTL=10*60*1000;

function today() {
  const date=new Date(),pad=(value:number)=>String(value).padStart(2,'0');
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`;
}
/** 分 → 「元」显示文本（整数不带小数）。 */
function yuan(cents:number|null|undefined) {
  if(cents==null)return '—';
  return (cents/100).toLocaleString('zh-CN',{minimumFractionDigits:0,maximumFractionDigits:2});
}
/**
 * 「元」输入 → 分，不做静默清洗：空串返回 {cents:null}（用于清空总预算），
 * 格式不合法（含字母、负号、超过两位小数、0）返回 invalid，由界面提示而不是悄悄改值。
 */
function parseMoney(text:string):{cents:number|null;invalid:boolean} {
  const trimmed=text.trim();
  if(!trimmed)return {cents:null,invalid:false};
  if(!/^\d+(?:\.\d{1,2})?$/.test(trimmed))return {cents:null,invalid:true};
  const value=Number(trimmed);
  if(!Number.isFinite(value)||value<=0)return {cents:null,invalid:true};
  return {cents:Math.round(value*100),invalid:false};
}
function emptyDraft():Draft {return {amount:'',category:'餐饮',date:today(),note:''}}
const MONEY_HINT='请输入大于 0 的金额，最多两位小数';

/** 行程预算：总预算 + 支出记录（增删改）+ AI 估算。金额全部以分存取。 */
export function BudgetPanel({tripId,canEditBudget=true}:{tripId:number;canEditBudget?:boolean}) {
  const [budget,setBudget]=useState<Budget|null>(null),[loading,setLoading]=useState(true);
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  const [amountInput,setAmountInput]=useState('');
  const [amountInvalid,setAmountInvalid]=useState(false);
  const [draft,setDraft]=useState<Draft>(emptyDraft);
  const [draftInvalid,setDraftInvalid]=useState(false);
  const [editing,setEditing]=useState<number|null>(null),[edit,setEdit]=useState<Draft>(emptyDraft);
  const [editInvalid,setEditInvalid]=useState(false);
  const [saving,setSaving]=useState(false);
  const [estimate,setEstimate]=useState<EstimateItem[]>([]),[estimating,setEstimating]=useState(false),[estimateNote,setEstimateNote]=useState(''),[estimateError,setEstimateError]=useState('');
  const [estimateAt,setEstimateAt]=useState(0);
  const [clock,setClock]=useState(0);
  const [pendingDelete,setPendingDelete]=useState<Expense|null>(null);
  const [reloadKey,setReloadKey]=useState(0);
  const undoTimer=useRef<number|null>(null);

  /** 行程切换时把面板的全部临时状态清空（父级另有 key 重挂载，这里兜底）。 */
  useEffect(()=>{
    setBudget(null);setLoading(true);setError('');setNotice('');
    setAmountInput('');setAmountInvalid(false);
    setDraft(emptyDraft());setDraftInvalid(false);
    setEditing(null);setEdit(emptyDraft());setEditInvalid(false);
    setSaving(false);
    setEstimate([]);setEstimateNote('');setEstimateError('');setEstimateAt(0);setEstimating(false);
    setPendingDelete(null);
    if(undoTimer.current!=null){window.clearTimeout(undoTimer.current);undoTimer.current=null}
  },[tripId]);

  useEffect(()=>{
    let alive=true;
    setLoading(true);setError('');setBudget(null);
    api<Budget>(`/trips/${tripId}/budget`)
      .then(data=>{if(!alive)return;setBudget(data);setAmountInput(data.amount_cents==null?'':String(data.amount_cents/100))})
      .catch(e=>{if(alive)setError(message(e))})
      .finally(()=>{if(alive)setLoading(false)});
    return ()=>{alive=false};
  },[tripId,reloadKey]);

  useEffect(()=>()=>{
    if(undoTimer.current!=null)window.clearTimeout(undoTimer.current);
  },[]);

  // 估算结果存在时每分钟刷新一次，让「已过期」提示能自己出现。
  useEffect(()=>{
    if(!estimate.length)return;
    const timer=window.setInterval(()=>setClock(Date.now()),60000);
    return ()=>window.clearInterval(timer);
  },[estimate.length]);

  const expenses=budget?.expenses??[];
  const spent=expenses.reduce((total,item)=>total+item.amount_cents,0);
  const remaining=budget?.amount_cents==null?null:budget.amount_cents-spent;
  const estimateStale=estimate.length>0&&estimateAt>0&&clock>0&&clock-estimateAt>ESTIMATE_TTL;
  const readFailed=!!error&&!budget&&!loading;

  function sortExpenses(list:Expense[]) {
    return [...list].sort((a,b)=>b.expense_date.localeCompare(a.expense_date)||b.id-a.id);
  }
  async function saveAmount(e:React.FormEvent) {
    e.preventDefault();
    const parsed=parseMoney(amountInput);
    if(parsed.invalid){setAmountInvalid(true);return}
    setAmountInvalid(false);
    setSaving(true);setError('');setNotice('');
    try{
      const result=await api<{amount_cents:number|null}>(`/trips/${tripId}/budget`,{method:'PUT',body:JSON.stringify({amount_cents:parsed.cents})});
      setBudget(current=>current?{...current,amount_cents:result.amount_cents}:current);
      setAmountInput(result.amount_cents==null?'':String(result.amount_cents/100));
      setNotice(result.amount_cents==null?'总预算已清空':'总预算已保存');
    }catch(e){setError(message(e))}finally{setSaving(false)}
  }
  async function addExpense(e:React.FormEvent) {
    e.preventDefault();
    const parsed=parseMoney(draft.amount);
    if(parsed.invalid||parsed.cents==null){setDraftInvalid(true);return}
    setDraftInvalid(false);
    setSaving(true);setError('');setNotice('');
    try{
      const expense=await api<Expense>(`/trips/${tripId}/expenses`,{method:'POST',body:JSON.stringify({amount_cents:parsed.cents,category:draft.category,expense_date:draft.date||today(),note:draft.note.trim()||undefined})});
      setBudget(current=>current?{...current,expenses:sortExpenses([expense,...current.expenses])}:current);
      setDraft({amount:'',category:draft.category,date:draft.date,note:''});setNotice('支出已记录');
    }catch(e){setError(message(e))}finally{setSaving(false)}
  }
  function startEdit(expense:Expense) {
    setEditing(expense.id);setEditInvalid(false);
    setEdit({amount:String(expense.amount_cents/100),category:CATEGORIES.includes(expense.category)?expense.category:'其他',date:expense.expense_date||today(),note:expense.note||''});
  }
  async function saveEdit(id:number) {
    const parsed=parseMoney(edit.amount);
    if(parsed.invalid||parsed.cents==null){setEditInvalid(true);return}
    setEditInvalid(false);
    setSaving(true);setError('');setNotice('');
    try{
      const expense=await api<Expense>(`/trips/${tripId}/expenses/${id}`,{method:'PUT',body:JSON.stringify({amount_cents:parsed.cents,category:edit.category,expense_date:edit.date||today(),note:edit.note.trim()||undefined})});
      setBudget(current=>current?{...current,expenses:sortExpenses(current.expenses.map(item=>item.id===id?expense:item))}:current);
      setEditing(null);setNotice('支出已更新');
    }catch(e){setError(message(e))}finally{setSaving(false)}
  }
  async function remove(expense:Expense) {
    setSaving(true);setError('');setNotice('');
    try{
      await api<{ok:boolean}>(`/trips/${tripId}/expenses/${expense.id}`,{method:'DELETE'});
      setBudget(current=>current?{...current,expenses:current.expenses.filter(item=>item.id!==expense.id)}:current);
      if(editing===expense.id)setEditing(null);
      setNotice('');
      setPendingDelete(expense);
      if(undoTimer.current!=null)window.clearTimeout(undoTimer.current);
      undoTimer.current=window.setTimeout(()=>{setPendingDelete(null);undoTimer.current=null},UNDO_MS);
    }catch(e){setError(message(e))}finally{setSaving(false)}
  }
  /** 撤销删除：用原字段重新建一笔（后端不支持恢复原 id，金额与日期保持一致）。 */
  async function undoRemove() {
    const expense=pendingDelete;
    if(!expense)return;
    if(undoTimer.current!=null){window.clearTimeout(undoTimer.current);undoTimer.current=null}
    setPendingDelete(null);
    setSaving(true);setError('');
    try{
      const restored=await api<Expense>(`/trips/${tripId}/expenses`,{method:'POST',body:JSON.stringify({amount_cents:expense.amount_cents,category:expense.category,expense_date:expense.expense_date,note:expense.note||undefined,place_id:expense.place_id||undefined})});
      setBudget(current=>current?{...current,expenses:sortExpenses([restored,...current.expenses])}:current);
      setNotice('已恢复这笔支出');
    }catch(e){setError(message(e))}finally{setSaving(false)}
  }
  async function runEstimate() {
    setEstimating(true);setEstimateError('');setEstimateNote('');
    try{
      const data=await api<{items:EstimateItem[]}>(`/trips/${tripId}/budget/estimate`,{method:'POST'});
      setEstimate(data.items||[]);setEstimateAt(Date.now());setClock(Date.now());
      if(!data.items.length)setEstimateNote('AI 没有给出估算结果，稍后再试一次');
    }catch(e){setEstimateError(message(e))}finally{setEstimating(false)}
  }

  return <div className="budget-panel budget-panel--flat">
    <div className="budget-body">
    <div className="budget-head">
      <span className="budget-kicker">预算与支出</span>
      <button type="button" className="secondary" onClick={runEstimate} disabled={estimating||!budget}>{estimating?'AI 估算中…':'AI 估算'}</button>
    </div>
    {error&&<div className="error" role="alert">{error}
      {readFailed&&<button type="button" className="text-btn budget-retry" onClick={()=>{setError('');setReloadKey(key=>key+1)}}>重试</button>}
    </div>}
    {notice&&<div className="notice" role="status">{notice}</div>}
    {pendingDelete&&<div className="undo-bar budget-undo" role="status">
      <span>已删除一笔支出</span>
      <button type="button" className="text-btn" onClick={undoRemove}>撤销</button>
    </div>}
    {loading
      ? <p className="budget-hint">正在读取预算…</p>
      : !budget
        ? <div className="budget-hint">预算暂时读不出来。
            <button type="button" className="text-btn" onClick={()=>{setError('');setReloadKey(key=>key+1)}}>重试</button>
          </div>
        : <>
          <dl className="budget-stats">
            <div><dt>总预算</dt><dd>{budget.amount_cents==null?'未设置':`${yuan(budget.amount_cents)} 元`}</dd></div>
            <div><dt>已花费</dt><dd>{yuan(spent)} 元</dd></div>
            <div><dt>剩余</dt><dd className={remaining!=null&&remaining<0?'is-over':''}>{remaining==null?'—':`${yuan(remaining)} 元`}</dd></div>
          </dl>
          {canEditBudget
            ? <form className="budget-amount" onSubmit={saveAmount} noValidate>
                <label>总预算（元）
                  <input inputMode="decimal" value={amountInput} aria-invalid={amountInvalid} aria-describedby={amountInvalid?'budget-amount-error':undefined} onChange={e=>{setAmountInput(e.target.value);setAmountInvalid(false)}} placeholder="例如 3000" aria-label="总预算（元）"/>
                </label>
                <button className="secondary" disabled={saving}>保存预算</button>
                {amountInvalid&&<p className="field-error" id="budget-amount-error" role="alert">{MONEY_HINT}</p>}
              </form>
            : <p className="budget-hint">总预算仅创建者可修改；你仍可以记录和编辑支出。</p>}

          <div className="budget-list">
            <div className="grouphead"><span>支出记录</span><span>{expenses.length} 笔</span></div>
            {expenses.length===0
              ? <p className="budget-empty">还没有记录支出。先添加一笔，或让 AI 估个大概。</p>
              : <ul>{expenses.map(expense=>editing===expense.id
                ? <li className="budget-item is-editing" key={expense.id}>
                    <div className="budget-edit-fields">
                      <label>分类<select value={edit.category} onChange={e=>setEdit(current=>({...current,category:e.target.value}))}>{CATEGORIES.map(category=><option key={category} value={category}>{category}</option>)}</select></label>
                      <label>金额（元）<input inputMode="decimal" value={edit.amount} aria-invalid={editInvalid} aria-describedby={editInvalid?`budget-edit-error-${expense.id}`:undefined} onChange={e=>{setEdit(current=>({...current,amount:e.target.value}));setEditInvalid(false)}}/></label>
                      <label>日期<input type="date" value={edit.date} onChange={e=>setEdit(current=>({...current,date:e.target.value}))}/></label>
                      <label>备注<input value={edit.note} onChange={e=>setEdit(current=>({...current,note:e.target.value}))} maxLength={120} placeholder="可选"/></label>
                    </div>
                    {editInvalid&&<p className="field-error" id={`budget-edit-error-${expense.id}`} role="alert">{MONEY_HINT}</p>}
                    <div className="budget-item-actions"><button type="button" className="primary" onClick={()=>saveEdit(expense.id)} disabled={saving}>保存</button><button type="button" className="text-btn" onClick={()=>setEditing(null)}>取消</button></div>
                  </li>
                : <li className="budget-item" key={expense.id}>
                    <span className="budget-category">{expense.category}</span>
                    <div className="budget-item-body"><strong className="mono">{yuan(expense.amount_cents)} 元</strong><span>{expense.expense_date}{expense.note?` · ${expense.note}`:''}</span></div>
                    <div className="budget-item-actions"><button type="button" className="text-btn" onClick={()=>startEdit(expense)}>编辑</button><button type="button" className="text-btn" onClick={()=>remove(expense)} disabled={saving}>删除</button></div>
                  </li>)}</ul>}
          </div>

          <form className="budget-form" onSubmit={addExpense} noValidate>
            <span className="budget-form-title">记一笔</span>
            <div className="budget-form-fields">
              <label>分类<select value={draft.category} onChange={e=>setDraft(current=>({...current,category:e.target.value}))}>{CATEGORIES.map(category=><option key={category} value={category}>{category}</option>)}</select></label>
              <label>金额（元）<input inputMode="decimal" value={draft.amount} aria-invalid={draftInvalid} aria-describedby={draftInvalid?'budget-draft-error':undefined} onChange={e=>{setDraft(current=>({...current,amount:e.target.value}));setDraftInvalid(false)}} placeholder="0"/></label>
              <label>日期<input type="date" value={draft.date} onChange={e=>setDraft(current=>({...current,date:e.target.value}))}/></label>
              <label>备注<input value={draft.note} onChange={e=>setDraft(current=>({...current,note:e.target.value}))} maxLength={120} placeholder="可选"/></label>
              <button className="primary" disabled={saving}>添加支出</button>
            </div>
            {draftInvalid&&<p className="field-error" id="budget-draft-error" role="alert">{MONEY_HINT}</p>}
          </form>

          {(estimate.length>0||estimateNote||estimating||estimateError)&&<div className="budget-estimate">
            <div className="grouphead"><span>AI 估算（元）</span><span>{estimating?'估算中…':'参考 · 人民币 · 不含大交通'}</span></div>
            {estimateError&&<div className="error" role="alert">{estimateError}
              <button type="button" className="text-btn" onClick={runEstimate} disabled={estimating}>重试</button>
            </div>}
            {estimateNote&&<p className="budget-hint" role="status">{estimateNote}</p>}
            {estimateStale&&<p className="budget-stale" role="status">估算已超过 10 分钟，行程有改动后建议重新估算。</p>}
            {estimate.length>0&&<ul>{estimate.map((item,index)=><li key={`${item.category}-${index}`}><strong>{item.category}</strong><span className="mono">{item.low}–{item.high} 元</span>{item.assumption&&<p>{item.assumption}</p>}</li>)}</ul>}
          </div>}
        </>}
    </div>
  </div>;
}
