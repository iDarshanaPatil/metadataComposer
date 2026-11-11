let csrf = '';
export function setCsrf(value:string){csrf=value;}
export async function api<T=any>(path:string,method='GET',body?:unknown):Promise<T>{
 const response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok)throw new Error(data.error||'Request failed');
 return data;
}
export const path=(...parts:string[])=>parts.map(encodeURIComponent).join('/');
export type Row={id:number|string;key:string;value:string|null;type:'string'|'number'|'boolean'|'ref';secret:boolean;description:string;fresh?:boolean};
export type Change={op:'put'|'delete';key:string;value?:string;type?:Row['type'];secret?:boolean;description?:string};
export function changesFor(rows:Row[],drafts:Record<string,Row>,removed:Set<string>):Change[]{
 const changes:Change[]=[];
 for(const row of rows){
  const id=String(row.id);if(removed.has(id)){if(!row.fresh)changes.push({op:'delete',key:row.key});continue;}
  const next=drafts[id];if(!next)continue;
  const change:Change={op:'put',key:next.key};
  for(const field of ['value','type','secret','description'] as const){
   if((row.fresh||next[field]!==row[field])&&next[field]!==null)Object.assign(change,{[field]:next[field]});
  }
  if(row.fresh||Object.keys(change).length>2)changes.push(change);
 }
 return changes;
}
export function appColor(name:string){let h=0;for(const c of name)h=(h*31+c.charCodeAt(0))>>>0;return ['#f5b544','#2dd4bf','#a78bfa','#fb7185','#38bdf8','#a3e635','#f472b6','#fb923c'][h%8];}
