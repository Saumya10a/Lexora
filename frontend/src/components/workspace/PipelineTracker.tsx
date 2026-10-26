import {motion} from 'framer-motion';
import {ArrowDownToLine,CheckCircle2,Loader2,Play,Workflow} from 'lucide-react';
import type {TargetFramework} from '../../services/api';

const phases=['Entities','Repositories','Services','Controllers'];
type Props={running:boolean;complete:boolean;framework:TargetFramework;onStart:()=>void;onDownload:()=>void;disabled?:boolean;isOffline?:boolean};

export default function PipelineTracker({running,complete,framework,onStart,onDownload,disabled,isOffline}:Props){
 return <motion.div layout className={`pipeline-tracker ${complete?'pipeline-complete':''}`} initial={{opacity:0,y:24}} animate={{opacity:1,y:0}} transition={{type:'spring',stiffness:200,damping:22}}>
  {!running&&!complete&&<><span className="pipeline-brand"><Workflow size={18}/><span>READY TO MIGRATE</span></span><div className="pipeline-divider"/><button className={`pipeline-start ${isOffline?'is-offline':''}`} disabled={disabled} onClick={onStart} title={isOffline?'Backend API is offline (port 8010)':'Start DAG Translation'}><Play size={18} fill="currentColor"/> {isOffline?'API OFFLINE · START BACKEND':'INITIALIZE DAG TRANSLATION'}</button></>}
  {running&&<><span className="pipeline-brand running-brand"><Loader2 className="pipeline-spin" size={15}/><span>DAG EXECUTING</span></span><div className="pipeline-divider"/><div className="pipeline-phases">{phases.map((phase,index)=><div className={`pipeline-phase ${index===0?'active':''}`} key={phase}>{index===0?<Loader2 className="pipeline-spin" size={15}/>:<span className="phase-pending"/>}<span>{phase}</span>{index<phases.length-1&&<i/>}</div>)}</div><span className="pipeline-wait-copy">Waiting for API completion response</span></>}
  {complete&&<><span className="pipeline-brand done-brand"><CheckCircle2 size={16}/><span>TRANSLATION COMPLETE</span></span><div className="pipeline-divider"/><div className="pipeline-phases">{phases.map((phase,index)=><div className="pipeline-phase done" key={phase}><CheckCircle2 size={15}/><span>{phase}</span>{index<phases.length-1&&<i/>}</div>)}</div><button className="pipeline-download" onClick={onDownload}><ArrowDownToLine size={15}/> Download {framework==='spring-boot'?'Spring Boot':'Go Fiber'} Target (.zip)</button></>}
 </motion.div>;
}
