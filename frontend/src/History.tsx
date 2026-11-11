import {useEffect,useState} from 'react';
import {Clock3,ArrowDown} from 'lucide-react';
import {api,path} from './api';
type Entry={id:number;app:string|null;namespace:string;key:string;action:string;old_value:string;changed_at:string;changed_by:string};
export function History({org,initialApp='',initialNamespace='',initialKey=''}:{org:string;initialApp?:string;initialNamespace?:string;initialKey?:string}){
 const [filters,setFilters]=useState({app_name:initialApp,namespace:initialNamespace,key:initialKey,person:''});
 const [rows,setRows]=useState<Entry[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const [more,setMore]=useState(false);
 const query=()=>new URLSearchParams(Object.entries(filters).filter(([,v])=>v));
 useEffect(()=>{let active=true;setLoading(true);setError('');const timer=setTimeout(()=>{api<Entry[]>('/v1/history/'+path(org)+'?'+query()).then(data=>{if(active){setRows(data);setMore(data.length===100);}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});},200);return()=>{active=false;clearTimeout(timer);};},[org,filters]);
 async function next(){setLoading(true);try{const q=query();q.set('before',String(rows.at(-1)?.id));const data=await api<Entry[]>('/v1/history/'+path(org)+'?'+q);setRows([...rows,...data]);setMore(data.length===100);}catch(e){setError((e as Error).message);}finally{setLoading(false);}}
 return <div className="history"><div className="filter-grid">{Object.entries(filters).map(([key,value])=><label key={key}>{({app_name:'App',namespace:'Namespace',key:'Variable',person:'Person'} as Record<string,string>)[key]}<input placeholder="All" value={value} onChange={e=>setFilters({...filters,[key]:e.target.value})}/></label>)}</div>
 {error&&<p role="alert" className="error">{error}</p>}
 <div className="table-scroll"><table className="history-table"><thead><tr><th>When</th><th>Who</th><th>Change</th><th>Variable / entity</th><th>Where</th><th>Previous value</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td title={r.changed_at}>{new Date(r.changed_at).toLocaleString()}</td><td>{r.changed_by}</td><td><span className={'action '+r.action}>{r.action}</span></td><td className="mono">{r.key||'namespace'}</td><td>{[r.app,r.namespace].filter(Boolean).join(' / ')||org}</td><td className="mono">{r.old_value||'—'}</td></tr>)}</tbody></table></div>
 {!loading&&!rows.length&&<div className="empty compact"><Clock3/><h3>No matching history</h3><p>Changes and secret reveals will appear here.</p></div>}
 {loading&&<p className="muted">Loading history…</p>}{more&&<button onClick={next} disabled={loading}><ArrowDown size={14}/> Load earlier entries</button>}
 </div>;
}
