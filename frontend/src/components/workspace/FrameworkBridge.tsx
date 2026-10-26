import {motion} from 'framer-motion';
import {ArrowRight,Braces} from 'lucide-react';
import type {DetectedFramework,TargetFramework,TargetFrameworkOption} from '../../services/api';

type Props={source:DetectedFramework;target:TargetFramework;onTargetChange:(target:TargetFramework)=>void;availableTargets:TargetFrameworkOption[];disabled?:boolean};

function FrameworkGlyph({framework}:{framework:DetectedFramework}){
 return <span className={`bridge-logo bridge-logo-${framework.type}`} aria-hidden="true">
  <svg viewBox="0 0 40 40" role="img" aria-label={`${framework.name} logo`}>
   {framework.type==='node'&&<><path d="M20 3 35 11.5v17L20 37 5 28.5v-17L20 3Z" fill="currentColor"/><text x="20" y="24" textAnchor="middle" fill="white" fontSize="10" fontWeight="800">JS</text></>}
   {framework.type==='spring'&&<><path d="M12 12h16l-2 15a6 6 0 0 1-6 5h-1a6 6 0 0 1-6-5l-1-15Z" fill="currentColor"/><path d="M28 15h3a4 4 0 0 1 0 8h-4" fill="none" stroke="currentColor" strokeWidth="3"/><path d="M15 8c-2-2 2-3 0-5M22 8c-2-2 2-3 0-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>}
   {framework.type==='python'&&<><path d="M20 4c-8 0-8 3-8 8v4h12v2H8c-4 0-6 3-6 8s2 8 7 8h4v-5c0-4 3-7 7-7h7c3 0 5-2 5-5v-5c0-5-4-8-12-8Zm-4 5a2 2 0 1 1 0-4 2 2 0 0 1 0 4Z" fill="#3776ab"/><path d="M20 36c8 0 8-3 8-8v-4H16v-2h16c4 0 6-3 6-8s-2-8-7-8h-4v5c0 4-3 7-7 7h-7c-3 0-5 2-5 5v5c0 5 4 8 12 8Zm4-5a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z" fill="#ffd43b"/></>}
   {framework.type==='go'&&<><circle cx="20" cy="20" r="17" fill="currentColor"/><text x="20" y="25" textAnchor="middle" fill="white" fontSize="12" fontWeight="800">Go</text></>}
   {framework.type==='unknown'&&<><rect x="5" y="7" width="30" height="26" rx="7" fill="currentColor"/><text x="20" y="24" textAnchor="middle" fill="white" fontSize="10" fontWeight="800">{'</>'}</text></>}
  </svg>
 </span>;
}

export default function FrameworkBridge({source,target,onTargetChange,availableTargets,disabled=false}:Props){
 return <div className="framework-bridge" aria-label="Framework translation bridge">
  <div className="bridge-source-node"><FrameworkGlyph framework={source}/><span><small>DETECTED SOURCE</small><strong>{source.name}</strong></span></div>
  <motion.div className="bridge-arrow" animate={{x:[0,5,0]}} transition={{repeat:Infinity,duration:1.5,ease:'easeInOut'}} aria-hidden="true"><ArrowRight size={26}/></motion.div>
  <label className="bridge-target-wrap"><span className="bridge-target-label">TARGET ARCHITECTURE</span><span className="bridge-target-node"><Braces size={22}/><select aria-label="Target architecture" value={target} disabled={disabled} onChange={event=>onTargetChange(event.target.value)}>{availableTargets.map(option=><option value={option.id} key={option.id}>{option.label}</option>)}</select></span></label>
 </div>;
}
