import type {ReactNode} from 'react';
export function BentoGrid({children,className=''}:{children:ReactNode;className?:string}){return <div className={`bento-grid ${className}`}>{children}</div>}
export function BentoPanel({children,className='',label}:{children:ReactNode;className?:string;label?:string}){return <section className={`bento-panel ${className}`}>{label&&<div className="panel-label">{label}</div>}{children}</section>}
