import {useEffect,useRef,ReactNode} from 'react';
import {X} from 'lucide-react';
export function Dialog({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}){
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{ref.current?.showModal();return()=>ref.current?.close();},[]);
 return <dialog className={wide?'wide':''} ref={ref} onCancel={e=>{e.preventDefault();onClose();}} aria-label={title}>
  <header className="dialog-head"><h2>{title}</h2><button className="icon" onClick={onClose} aria-label="Close dialog"><X size={18}/></button></header>{children}
 </dialog>;
}
