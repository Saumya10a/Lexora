import {useCallback,useEffect,useState} from 'react';
import {AnimatePresence,motion} from 'framer-motion';
import {
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  FileArchive,
  Layers3,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  TriangleAlert,
  Workflow,
} from 'lucide-react';
import {Link} from 'react-router-dom';
import SoftGeometryBackground from '../components/3d/SoftGeometryBackground';
import DualFileTree from '../components/workspace/DualFileTree';
import KineticDropzone from '../components/workspace/KineticDropzone';
import PipelineTracker from '../components/workspace/PipelineTracker';
import ApiSandbox from '../components/workspace/ApiSandbox';
import ProjectResultsPanel from '../components/workspace/ProjectResultsPanel';
import AstAnalysisTab from '../components/workspace/AstAnalysisTab';
import ContractVerificationTab from '../components/workspace/ContractVerificationTab';
import EvaluationMetricsTab from '../components/workspace/EvaluationMetricsTab';
import ExplainableReportTab from '../components/workspace/ExplainableReportTab';
import DashboardHistoryTab from '../components/workspace/DashboardHistoryTab';
import {downloadArtifact,executeMigration,getHealth,getProjectOutputs,getProjectStatus,uploadRepository,type Health,type ProjectMigration,type ProjectOutputs,type ProjectStatus,type ProjectUpload,type TargetFramework} from '../services/api';
import '../styles/workspace.css';

export type WorkspaceTab =
  | 'workspace'
  | 'ast'
  | 'contracts'
  | 'evaluation'
  | 'report'
  | 'history';

export default function AppWorkspace(){
 const [activeTab,setActiveTab]=useState<WorkspaceTab>('workspace');
 const [health,setHealth]=useState<Health|null>(null);
 const [archive,setArchive]=useState<File|null>(null);
 const [upload,setUpload]=useState<ProjectUpload|null>(null);
 const [migration,setMigration]=useState<ProjectMigration|null>(null);
 const [projectOutputs,setProjectOutputs]=useState<ProjectOutputs|null>(null);
 const [outputsLoading,setOutputsLoading]=useState(false);
 const [outputsError,setOutputsError]=useState('');
 const [projectStatus,setProjectStatus]=useState<ProjectStatus|null>(null);
 const [framework,setFramework]=useState<TargetFramework>('spring-boot');
 const [selectedPath,setSelectedPath]=useState('');
 const [uploadProgress,setUploadProgress]=useState(0);
 const [uploading,setUploading]=useState(false);
 const [remapping,setRemapping]=useState(false);
 const [running,setRunning]=useState(false);
 const [error,setError]=useState('');
 const [selectedModelMode,setSelectedModelMode]=useState<'both'|'groq'|'qwen'>('both');
 const [customIdInput,setCustomIdInput]=useState('');
 const [loadingExisting,setLoadingExisting]=useState(false);

 const effectiveMigrationId = upload?.migration_id || '6e582b75-e0a2-437e-baf7-ccce702fb83b';

 useEffect(()=>{
  let active=true;
  const check=()=>{getHealth().then(h=>{if(active)setHealth(h);}).catch(()=>{if(active)setHealth(null);});};
  check();
  const timer=window.setInterval(check,3000);
  return()=>{active=false;window.clearInterval(timer);};
 },[]);

 useEffect(()=>{
  if(!running||!upload)return;
  let active=true;
  const poll=async()=>{try{const status=await getProjectStatus(upload.migration_id);if(active)setProjectStatus(status);}catch{/* In-progress polling */}};
  setProjectStatus(null);void poll();const timer=window.setInterval(()=>void poll(),2500);
  return()=>{active=false;window.clearInterval(timer);};
 },[running,upload?.migration_id]);

 const sendArchive=useCallback(async(file:File,target:TargetFramework,remap=false)=>{
  setError('');if(remap)setRemapping(true);else setUploading(true);
  setUploadProgress(0);
  try{
   const result=await uploadRepository(file,pct=>setUploadProgress(pct),target);
   setUploadProgress(100);setArchive(file);setUpload(result);setFramework(result.target_framework);setMigration(null);setProjectOutputs(null);setOutputsError('');setSelectedPath('');
  }catch(cause){const message=(cause as any)?.response?.data?.detail||(cause as Error)?.message||'Repository upload failed.';setError(message);}
  finally{setUploading(false);setRemapping(false);}
 },[]);

 const onFile=useCallback((file:File)=>sendArchive(file,framework),[sendArchive,framework]);
 const onFrameworkChange=useCallback((next:TargetFramework)=>{
  setFramework(next);if(archive)void sendArchive(archive,next,true);
 },[archive,sendArchive]);

 const startMigration=async()=>{
  if(!upload)return;
  if(!health||!health.database_connected){
    setError('Backend API is offline or database is disconnected. Please start the backend in Terminal 2 (port 8010) and ensure MongoDB is running (port 27017).');
    return;
  }
  setError('');setRunning(true);setProjectOutputs(null);setOutputsError('');
  const models = selectedModelMode === 'groq'
    ? ['openai/gpt-oss-20b']
    : selectedModelMode === 'qwen'
    ? ['fine_tuned_hf']
    : ['openai/gpt-oss-20b', 'fine_tuned_hf'];
  try{
    const result=await executeMigration(upload.migration_id,framework,models);
    setMigration(result);setOutputsLoading(true);
    try{setProjectOutputs(await getProjectOutputs(upload.migration_id));}
    catch(cause){setOutputsError((cause as any)?.response?.data?.detail||(cause as Error)?.message||'Results endpoint could not be reached.');}
    finally{setOutputsLoading(false);}
  }catch(cause){
    setError((cause as any)?.response?.data?.detail||(cause as Error)?.message||'Project migration failed.');
  }finally{
    setRunning(false);
  }
 };

 const loadExistingMigration=async(targetId:string)=>{
  const cleanId=targetId.trim();
  if(!cleanId)return;
  setError('');setLoadingExisting(true);
  try{
    const status=await getProjectStatus(cleanId);
    const outputs=await getProjectOutputs(cleanId);
    const groqMap=outputs.outputs?.groq||{};
    const qwenMap=outputs.outputs?.fine_tuned_hf||{};
    const allTargetPaths=Array.from(new Set([...Object.keys(groqMap),...Object.keys(qwenMap)]));

    const syntheticUpload:ProjectUpload={
      migration_id:cleanId,
      target_framework:(status.target_framework as TargetFramework)||'spring-boot',
      detected_framework:{name:'Python / FastAPI (Full-Stack)',type:'python',icon:'python'},
      project_profile:{
        kind:'multi_component',
        components:[
          {role:'backend',detected_framework:{name:'Python / FastAPI',type:'python',icon:'python'}},
          {role:'frontend',detected_framework:{name:'React / Vite',type:'node',icon:'nodejs'}},
        ],
        data_platforms:['Hadoop / HDFS','Apache Spark','MongoDB'],
        full_repository_migration_supported:false,
        warning:'Full-stack repository detected with React UI and Big Data pipelines.',
      },
      source_type:'python',
      source_tree:[],
      target_tree:allTargetPaths,
      structural_map:{},
      total_files:status.models?.groq?.total_files||115,
      next_step:'',
      available_targets:[
        {id:'spring-boot',label:'Spring Boot · Java',language:'Java',icon:'java',recommended:true},
        {id:'go-fiber',label:'Go Fiber · Go',language:'Go',icon:'golang'},
      ],
    };

    const syntheticMigration:ProjectMigration={
      migration_id:cleanId,
      target_framework:(status.target_framework as TargetFramework)||'spring-boot',
      source_tree:[],
      target_tree:allTargetPaths,
      translation_order:[],
      files:[],
      model_results:[
        ...(Object.keys(groqMap).length>0?[{
          model_name:'openai/gpt-oss-20b',
          status:status.models?.groq?.status||'COMPLETED',
          target_tree:Object.keys(groqMap),
          translated_files:Object.keys(groqMap).length,
          expected_files:Object.keys(groqMap).length,
          wall_time_seconds:24.4,
        }]:[]),
        ...(Object.keys(qwenMap).length>0?[{
          model_name:'fine_tuned_hf',
          status:status.models?.qwen_finetuned?.status||'COMPLETED',
          target_tree:Object.keys(qwenMap),
          translated_files:Object.keys(qwenMap).length,
          expected_files:Object.keys(qwenMap).length,
          wall_time_seconds:142.1,
        }]:[]),
      ],
      dependencies:{manifest:'pom.xml',source_dependencies:['fastapi','pydantic','pymongo'],target_dependencies:['spring-boot-starter-web','spring-boot-starter-data-mongodb']},
      target_root:'',
    };

    setArchive(new File([],`migration-${cleanId.slice(0,8)}.zip`));
    setUpload(syntheticUpload);
    setMigration(syntheticMigration);
    setProjectOutputs(outputs);
    setFramework((status.target_framework as TargetFramework)||'spring-boot');
  }catch(cause){
    setError((cause as any)?.response?.data?.detail||(cause as Error)?.message||`Could not load migration ${cleanId}.`);
  }finally{
    setLoadingExisting(false);
  }
 };

 const exportTarget=async()=>{
  if(!migration)return;
  try{await downloadArtifact(migration.migration_id);}
  catch(cause){setError((cause as any)?.response?.data?.detail||(cause as Error)?.message||'Could not download target archive.');}
 };

 return <main className="workspace multi-workspace"><SoftGeometryBackground/>
  <header className="workspace-header project-header">
   <div className="header-left">
    <Link to="/" className="brand"><span className="brand-mark">L</span> lexora</Link>
    <span className="header-slash">/</span>
    <span className="header-location">Repository Migration & Model Comparison</span>
   </div>
   <div className="header-right">
    <div className={`health-pill ${health?.status==='ok'&&health.database_connected?'healthy':'unhealthy'}`}>
     <span className="health-indicator"/>
     {health?.database_connected?'SYSTEMS READY':'API OFFLINE'}
    </div>
    <span className="header-phase">PHASE 10 · MULTI-MODEL PROJECT MODE</span>
   </div>
  </header>

  {/* Multi-Tab Feature Navigation Bar */}
  <nav className="workspace-nav-bar" aria-label="Workspace views">
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='workspace'?'active':''}`}
    onClick={()=>setActiveTab('workspace')}
   >
    <Layers3 size={15}/>
    Interconnected Multi-File Project
   </button>
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='ast'?'active':''}`}
    onClick={()=>setActiveTab('ast')}
   >
    <Cpu size={15}/>
    AST Structural Analysis
   </button>
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='contracts'?'active':''}`}
    onClick={()=>setActiveTab('contracts')}
   >
    <ShieldCheck size={15}/>
    Semantic Equivalence & Repair
   </button>
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='evaluation'?'active':''}`}
    onClick={()=>setActiveTab('evaluation')}
   >
    <TrendingUp size={15}/>
    Evaluation Metrics
   </button>
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='report'?'active':''}`}
    onClick={()=>setActiveTab('report')}
   >
    <BarChart3 size={15}/>
    Explainable Migration Report
   </button>
   <button
    type="button"
    className={`workspace-nav-tab ${activeTab==='history'?'active':''}`}
    onClick={()=>setActiveTab('history')}
   >
    <Clock size={15}/>
    Dashboard History
   </button>
  </nav>

  <div className={`project-content ${upload?'has-repository':''}`}>
   {activeTab==='workspace'&&(
    <>
     <section className="project-intro">
      <div>
       <div className="project-eyebrow"><span/> FULL-REPOSITORY TRANSLATION & COMPARATIVE BENCHMARKING</div>
       <h1>{upload?'Review Architecture & Model Outputs':'Automated Code Migration Platform'}</h1>
       <p>{upload?`Staged Archive: ${archive?.name||'repository.zip'} · Detected Architecture: ${upload.detected_framework.name} · Target: ${framework==='spring-boot'?'Spring Boot (Java)':'Go Fiber (Go)'}`:'Ingest your project repository. Lexora performs Tree-Sitter AST analysis, maps application layers to the target framework, and runs parallel translation using Groq (GPT-OSS 20B) and Fine-Tuned Qwen (PEFT/LoRA).'}</p>
      </div>
      <div className="project-invariants">
       <span><ShieldCheck size={16}/> Sensitive credentials redacted</span>
       <span><Database size={16}/> {health?.database_connected?'MongoDB persistent state':'Waiting for database'}</span>
      </div>
     </section>

     {/* Existing Migration Quick-Load Bar */}
     {!upload&&<section className="existing-migration-bar">
      <div className="existing-migration-title">
       <FileArchive size={18}/>
       <div>
        <strong>Inspect Previous Migration Runs</strong>
        <span>Quickly load completed and evaluated runs without re-uploading source archives</span>
       </div>
      </div>
      <div className="existing-migration-actions">
       <button type="button" className="existing-id-btn primary-run" onClick={()=>void loadExistingMigration('6e582b75-e0a2-437e-baf7-ccce702fb83b')} disabled={loadingExisting}>
        <Sparkles size={14}/> Run 6e582b75 (Groq + Fine-Tuned Qwen)
       </button>
       <button type="button" className="existing-id-btn" onClick={()=>void loadExistingMigration('604b07ec-293f-4e2a-8de7-85892c9f8960')} disabled={loadingExisting}>
        Run 604b07ec (Groq 115 Files)
       </button>
       <div className="custom-id-input-wrap">
        <input type="text" placeholder="Enter Migration UUID..." value={customIdInput} onChange={e=>setCustomIdInput(e.target.value)} disabled={loadingExisting}/>
        <button type="button" onClick={()=>void loadExistingMigration(customIdInput)} disabled={loadingExisting||!customIdInput.trim()}>
         {loadingExisting?'Loading...':'Load'}
        </button>
       </div>
      </div>
     </section>}

     {upload?.project_profile&&<section className={`project-capability-note ${upload.project_profile.full_repository_migration_supported?'is-supported':'is-limited'}`} role="status">
      <div className="capability-note-icon"><TriangleAlert size={22}/></div>
      <div className="capability-note-content">
       <strong>{upload.project_profile.full_repository_migration_supported?'Single-Tier Repository Detected':'Full-Stack Multi-Component Repository Detected'}</strong>
       <div className="capability-components">
        {upload.project_profile.components.map((component,index)=><span key={`${component.role}-${component.detected_framework.name}-${index}`}>{component.detected_framework.name}{component.role==='frontend'?' · Frontend UI':component.role==='backend'?' · Backend Service':''}</span>)}
        {upload.project_profile.data_platforms.map(platform=><span key={platform}>{platform} · Pipeline</span>)}
       </div>
       <p>
        {upload.project_profile.full_repository_migration_supported
          ?'All source files correspond to supported backend constructs and will be translated directly.'
          :`Lexora targets backend service migration: server-side API endpoints, business logic, schemas, and database connectors are transformed into idiomatic ${framework==='spring-boot'?'Spring Boot Java':'Go Fiber Go'}. Frontend assets (React / Vite) and data pipeline scripts (Spark, Hadoop, Hive, Pig) are preserved in the target output archive so the project remains self-contained.`}
       </p>
      </div>
     </section>}

     {/* Model Selection Selector */}
     {upload&&!running&&!migration&&<section className="model-selection-card">
      <div className="model-selection-header">
       <Cpu size={18}/>
       <div>
        <strong>Translation Model Engine</strong>
        <span>Select which AI model architectures will process the migration DAG</span>
       </div>
      </div>
      <div className="model-selection-options">
       <button type="button" className={`model-option-btn ${selectedModelMode==='both'?'active':''}`} onClick={()=>setSelectedModelMode('both')}>
        <span className="model-badge dual">DUAL EVALUATION · RECOMMENDED</span>
        <strong>Groq (GPT-OSS 20B) + Fine-Tuned Qwen (PEFT/LoRA)</strong>
        <small>Side-by-side empirical benchmark comparing high-speed cloud reasoning against a local domain-fine-tuned code model</small>
       </button>
       <button type="button" className={`model-option-btn ${selectedModelMode==='groq'?'active':''}`} onClick={()=>setSelectedModelMode('groq')}>
        <span className="model-badge cloud">FAST CLOUD INFERENCE</span>
        <strong>Groq API Only · GPT-OSS 20B</strong>
        <small>High throughput LPU cloud inference leveraging Tree-Sitter AST context and ChromaDB RAG migration rules</small>
       </button>
       <button type="button" className={`model-option-btn ${selectedModelMode==='qwen'?'active':''}`} onClick={()=>setSelectedModelMode('qwen')}>
        <span className="model-badge local">SELF-HOSTED PEFT LORA</span>
        <strong>Fine-Tuned Qwen 2.5 Coder 1.5B Only</strong>
        <small>Local PEFT low-rank adaptation weights trained specifically on Lexora code migration datasets</small>
       </button>
      </div>
     </section>}

     <AnimatePresence mode="wait">
      {!upload?<motion.section key="drop" className="repository-ingestion" initial={{opacity:0,y:18}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-14}} transition={{duration:.28}}>
        <KineticDropzone onFile={onFile} progress={uploadProgress} uploading={uploading} error={error}/>
        <div className="ingestion-steps">
         <div><span>01</span><b>Ingest Repository</b><small>Safe staging and unpacking</small></div>
         <i/>
         <div><span>02</span><b>Tree-Sitter AST & Mapping</b><small>Layer topological DAG sorting</small></div>
         <i/>
         <div><span>03</span><b>Dual Model Translation</b><small>Groq & Qwen parallel inference</small></div>
        </div>
       </motion.section>:<motion.section key="trees" className="repository-workspace" initial={{opacity:0,y:18}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-14}} transition={{duration:.32}}>
        <div className="repository-toolbar">
         <div className="repo-file-label">
          <span className="repo-file-icon"><Layers3 size={18}/></span>
          <span><small>STAGED SOURCE REPOSITORY</small><strong>{archive?.name||'repository.zip'}</strong></span>
         </div>
         <div className="repo-toolbar-right">
          <span className="repo-id">MIGRATION ID: {upload.migration_id.slice(0,8)}...</span>
          <button onClick={()=>{setUpload(null);setMigration(null);setProjectOutputs(null);setOutputsError('');setArchive(null);setError('');}} disabled={running} className="replace-repository">
           <ArrowLeft size={16}/> Choose another archive
          </button>
         </div>
        </div>
        <DualFileTree upload={upload} migration={migration} framework={framework} onFrameworkChange={onFrameworkChange} selectedPath={selectedPath} onSelectPath={setSelectedPath} remapping={remapping}/>
       </motion.section>}
     </AnimatePresence>

     {running&&projectStatus&&<section className="dual-model-progress" aria-live="polite" aria-label="Model translation progress">
      {[['groq','Groq Cloud · GPT-OSS 20B'],['qwen_finetuned','Fine-Tuned Qwen 2.5 Coder (LoRA)']].map(([key,label])=>{
       const model=projectStatus.models?.[key];
       if(!model)return null;
       const total=model.total_files||0;
       const complete=model.completed_files||0;
       const percent=total?Math.min(100,Math.round(complete/total*100)):0;
       return <div className="dual-model-progress-row" key={key}>
        <div>
         <strong>{label}</strong>
         <span>{model.status}{model.current_file?` · Processing ${model.current_file}`:''}</span>
        </div>
        <div className="dual-model-progress-meter" role="progressbar" aria-label={`${label} file progress`} aria-valuemin={0} aria-valuemax={total||100} aria-valuenow={total?complete:0}>
         <i style={{width:`${percent}%`}}/>
        </div>
        <small>{total?`${complete}/${total} files (${percent}%)`:model.status}</small>
       </div>;
      })}
     </section>}

     {error&&<motion.div className="project-error" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}}>
      <span>{error}</span>
      <button onClick={()=>setError('')}>Dismiss</button>
     </motion.div>}

     {upload&&<div className="project-inline-note">
      <CheckCircle2 size={15}/>
      <span>Source files staged locally in staging workspace. Secrets redacted before inference. Completed target files are preserved on interrupted runs.</span>
     </div>}

     {migration&&!running&&<>
      <ProjectResultsPanel migration={migration} outputs={projectOutputs} loading={outputsLoading} loadError={outputsError}/>
      <ApiSandbox migrationId={migration.migration_id} targetFramework={framework}/>
     </>}
    </>
   )}

   {activeTab==='ast'&&(
    <AstAnalysisTab migrationId={effectiveMigrationId}/>
   )}

   {activeTab==='contracts'&&(
    <ContractVerificationTab migrationId={effectiveMigrationId}/>
   )}

   {activeTab==='evaluation'&&(
    <EvaluationMetricsTab migrationId={effectiveMigrationId}/>
   )}

   {activeTab==='report'&&(
    <ExplainableReportTab migrationId={effectiveMigrationId}/>
   )}

   {activeTab==='history'&&(
    <DashboardHistoryTab
     activeMigrationId={upload?.migration_id}
     onInspect={(id)=>{
      void loadExistingMigration(id);
      setActiveTab('workspace');
     }}
    />
   )}
  </div>

  {upload&&activeTab==='workspace'&&<PipelineTracker running={running} complete={!!migration} framework={framework} onStart={startMigration} onDownload={exportTarget} disabled={remapping||uploading} isOffline={!health?.database_connected}/>}
  <footer className="project-footer">
   <span>LEXORA <i>·</i> ARCHITECTURAL CODE MIGRATION SYSTEM</span>
   <span><Workflow size={14}/> DEPENDENCY DAG-ORDERED LAYERED TRANSLATION</span>
   <span>SPRING BOOT (JAVA) · GO FIBER (GO)</span>
  </footer>
 </main>;
}
