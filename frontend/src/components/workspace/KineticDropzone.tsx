import {useCallback,useState} from 'react';
import {useDropzone} from 'react-dropzone';
import {AnimatePresence,motion} from 'framer-motion';
import {Archive,CloudUpload,FileArchive,FolderUp,ShieldCheck,X} from 'lucide-react';

type Props={onFile:(file:File)=>Promise<void>;progress:number;uploading:boolean;error?:string};

export default function KineticDropzone({onFile,progress,uploading,error}:Props){
 const [rejected,setRejected]=useState('');
 const acceptFile=useCallback(async(files:File[])=>{setRejected('');if(files[0])await onFile(files[0]);},[onFile]);
 const {getRootProps,getInputProps,isDragActive,isDragReject,open}=useDropzone({onDropAccepted:acceptFile,onDropRejected:()=>setRejected('Choose a valid .zip repository archive.'),accept:{'application/zip':['.zip'],'application/x-zip-compressed':['.zip'],'application/octet-stream':['.zip']},multiple:false,maxFiles:1,noClick:true,noKeyboard:false});
 const circumference=2*Math.PI*43;
 return <div className="kinetic-zone-shell">
  <div {...getRootProps({className:'kinetic-dropzone-root'})}><motion.div className={`kinetic-dropzone ${isDragActive?'is-drag-active':''} ${isDragReject?'is-drag-reject':''} ${uploading?'is-uploading':''}`} animate={{scale:isDragActive?1.035:1,borderColor:isDragActive?'#10b981':isDragReject?'#ef4444':'rgba(148,163,184,.48)',backgroundColor:isDragActive?'rgba(16,185,129,.09)':'rgba(255,255,255,.52)',boxShadow:isDragActive?'0 22px 80px rgba(16,185,129,.15)':'0 20px 60px rgba(15,23,42,.075)'}} transition={{type:'spring',stiffness:220,damping:20}}>
   <input {...getInputProps()}/>
   <AnimatePresence mode="wait" initial={false}>
    {uploading?<motion.div key="uploading" className="upload-progress-state" initial={{opacity:0,y:14}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-10}}>
      <div className="progress-ring"><svg viewBox="0 0 100 100"><circle className="progress-track" cx="50" cy="50" r="43"/><motion.circle className="progress-value" cx="50" cy="50" r="43" strokeDasharray={circumference} animate={{strokeDashoffset:circumference-(circumference*progress)/100}} transition={{ease:'easeOut',duration:.3}}/></svg><span>{progress}%</span></div>
      <strong>{progress>=100?'Repository staged':'Uploading repository'}</strong><p>{progress>=100?'Building the source and target trees…':'Securely transferring your project archive'}</p><div className="upload-bar"><motion.span animate={{width:`${progress}%`}} transition={{ease:'easeOut',duration:.3}}/></div>
    </motion.div>:<motion.div key="idle" className="dropzone-content" initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-8}}>
      <div className="dropzone-orbit"><motion.div className="dropzone-core" animate={isDragActive?{y:-7,rotate:-8,scale:1.06}:{y:[0,-4,0],rotate:[0,2,0]}} transition={isDragActive?{type:'spring',stiffness:230,damping:16}:{duration:4,repeat:Infinity,ease:'easeInOut'}}><CloudUpload size={29}/></motion.div><span className="orbit-dot one"/><span className="orbit-dot two"/></div>
      <span className="dropzone-kicker">REPOSITORY INGESTION · PHASE 10</span><h2>{isDragActive?'Release to map your project':'Bring your codebase into Lexora'}</h2><p>Drop a ZIP archive here. Lexora maps your project structure into a new framework, file by file.</p>
      <button className="browse-repository" type="button" onClick={event=>{event.stopPropagation();open();}}><FolderUp size={16}/> Choose repository <span>.zip</span></button>
      <div className="dropzone-assurances"><span><ShieldCheck size={13}/> Source stays staged locally</span><i/><span><FileArchive size={13}/> ZIP · up to 50 MB</span></div>
    </motion.div>}
   </AnimatePresence>
  </motion.div></div>
  <AnimatePresence>{(error||rejected)&&<motion.div className="dropzone-error" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:5}}><X size={14}/>{error||rejected}</motion.div>}</AnimatePresence>
  <div className="dropzone-footnote"><Archive size={13}/> Ignored folders like <code>node_modules</code>, <code>.git</code> and build outputs are excluded automatically.</div>
 </div>;
}
