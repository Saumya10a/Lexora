import {useMemo,useState} from 'react';
import Editor from '@monaco-editor/react';
import {AlertTriangle,CheckCircle2,Download,FileCode2,FileText,LoaderCircle} from 'lucide-react';
import {downloadArtifact,downloadMigrationReport,type ProjectMigration,type ProjectOutputs,type ProjectModelResult} from '../../services/api';

type Props={migration:ProjectMigration;outputs:ProjectOutputs|null;loading:boolean;loadError?:string};
const MODEL_ORDER=['openai/gpt-oss-20b','fine_tuned_hf'];
const modelLabel=(id:string)=>id==='fine_tuned_hf'?'Fine-tuned Qwen':'Groq · GPT-OSS 20B';
const canonicalModelId=(id:string)=>id==='groq'?'openai/gpt-oss-20b':id==='qwen_finetuned'?'fine_tuned_hf':id;

function outputMap(payload:ProjectOutputs|null):Record<string,Record<string,string>>{
 const raw=payload?.outputs||payload?.models||{};
 const normalized:Record<string,Record<string,string>>={};
 for(const [rawModel,value] of Object.entries(raw)){
  const model=canonicalModelId(rawModel);
  const fileMap=(value&&typeof value==='object'&&'files' in value?(value as {files:unknown}).files:value) as Record<string,unknown>;
  const files:Record<string,string>={};
  for(const [path,code] of Object.entries(fileMap||{}))if(typeof code==='string')files[path]=code;
  normalized[model]=files;
 }
 return normalized;
}
function statusStyle(status:string){const value=status.toUpperCase();if(value==='PARTIAL')return 'result-status result-status-partial';return value==='COMPLETED'||value==='SUCCESS'||value==='AVAILABLE'? 'result-status result-status-good':'result-status result-status-bad';}

export default function ProjectResultsPanel({migration,outputs,loading,loadError}:Props){
 const textOutputs=useMemo(()=>outputMap(outputs),[outputs]);
 const models=useMemo(()=>{
  const statuses=migration.model_results||[];
  const ids=new Set([...statuses.map(item=>canonicalModelId(item.model_name)),...Object.keys(textOutputs).map(canonicalModelId)]);
  if(!ids.size){for(const id of MODEL_ORDER)ids.add(id);}
  return [...ids].sort((a,b)=>MODEL_ORDER.indexOf(a)-MODEL_ORDER.indexOf(b));
 },[migration.model_results,textOutputs]);
 const [selectedFiles,setSelectedFiles]=useState<Record<string,string>>({});
 const [downloadError,setDownloadError]=useState('');
 const byModel=new Map((migration.model_results||[]).map(item=>[canonicalModelId(item.model_name),item]));
 const reportAvailable=!!migration.model_results?.length;

 const handleDownload=async(model:string)=>{setDownloadError('');try{await downloadArtifact(migration.migration_id,model);}catch(error){setDownloadError((error as any)?.response?.data?.detail||`Could not download the ${modelLabel(model)} archive.`);}};
 const handleReport=async()=>{setDownloadError('');try{await downloadMigrationReport(migration.migration_id);}catch(error){setDownloadError((error as any)?.response?.data?.detail||'The comparison report is not available yet.');}};

 return <section className="project-results" aria-labelledby="project-results-title">
  <header className="project-results-heading"><div><span className="tree-kicker">MIGRATION ARTIFACTS</span><h2 id="project-results-title">Translated project output</h2><p>Inspect the generated files, download the target archive, and review the migration report.</p></div><button className="report-download" onClick={handleReport} disabled={!reportAvailable} title={!reportAvailable?'The report becomes available when model runs finish':'Download migration report'}><FileText size={16}/> Download report</button></header>
  {loading&&<div className="results-loading" role="status"><LoaderCircle className="spin" size={19}/> Loading generated code…</div>}
  {loadError&&<div className="results-alert" role="alert"><AlertTriangle size={17}/><span>Migration finished, but generated source files could not be loaded: {loadError}</span></div>}
  {downloadError&&<div className="results-alert" role="alert"><AlertTriangle size={17}/><span>{downloadError}</span><button onClick={()=>setDownloadError('')} aria-label="Dismiss">×</button></div>}
  <div className="model-output-grid">
   {models.map(model=>{
    const result=byModel.get(model) as ProjectModelResult|undefined;
    const files=textOutputs[model]||{};
    const fileNames=Object.keys(files).sort();
    const selected=selectedFiles[model]&&files[selectedFiles[model]]!==undefined?selectedFiles[model]:fileNames[0]||'';
    const state=result?.status|| (fileNames.length?'COMPLETED':'UNAVAILABLE');
    const translatedCount=result?.translated_files??result?.files?.filter(file=>['TRANSLATED','COPIED_RESOURCE','GENERATED_CONFIG'].includes(file.status)).length??fileNames.length;
    const expectedCount=result?.expected_files??result?.files?.filter(file=>file.status!=='SKIPPED').length??fileNames.length;
    const elapsed=result?.latency_seconds??result?.wall_time_seconds;
    const hasOutput=fileNames.length>0||translatedCount>0;
    return <article className="model-output-panel" key={model}>
     <div className="model-output-head"><div className="model-output-name"><span className="model-output-mark"><FileCode2 size={17}/></span><div><h3>{modelLabel(model)}</h3><span>{result?`${translatedCount}/${expectedCount} files translated`:fileNames.length?`${fileNames.length} files available`:'No file status returned'}</span></div></div><span className={statusStyle(state)}>{state}</span></div>
     {result?.error&&<p className="model-output-error"><AlertTriangle size={14}/>{result.error}</p>}
     <div className="model-output-controls"><label htmlFor={`file-${model}`}>Generated file</label><select id={`file-${model}`} value={selected} onChange={event=>setSelectedFiles(current=>({...current,[model]:event.target.value}))} disabled={!fileNames.length}><option value="">{loading?'Loading files…':'No generated files'}</option>{fileNames.map(path=><option value={path} key={path}>{path}</option>)}</select><button onClick={()=>void handleDownload(model)} disabled={!hasOutput} title={!hasOutput?'No output archive is available for this model':'Download this model’s target ZIP'}><Download size={15}/> ZIP</button></div>
     {selected?<div className="model-code-editor"><Editor height="390px" language={selected.endsWith('.java')?'java':selected.endsWith('.go')?'go':selected.endsWith('.py')?'python':selected.endsWith('.json')?'json':selected.endsWith('.xml')?'xml':'typescript'} theme="vs-light" value={files[selected]} options={{readOnly:true,minimap:{enabled:false},fontSize:12,wordWrap:'on',scrollBeyondLastLine:false,automaticLayout:true,renderLineHighlight:'none'}}/></div>:<div className="model-code-empty" role="status"><FileCode2 size={24}/><strong>{state==='FAILED'?'This model did not produce a complete target tree':'Generated source is not available yet'}</strong><span>{result?.error||'The model status is shown above. Retry the migration after resolving the reported issue.'}</span></div>}
     {elapsed!==undefined&&<div className="model-output-foot"><span>Generation time</span><strong>{elapsed.toFixed(1)}s</strong>{result?.status==='PARTIAL'&&<span className="partial-note">Partial output</span>}</div>}
    </article>;
   })}
  </div>
  {!loading&&!models.length&&<div className="model-code-empty"><strong>No model results were returned.</strong><span>The migration API did not provide model artifacts.</span></div>}
  <div className="results-honesty-note"><CheckCircle2 size={15}/><span>Code is shown exactly as generated. A successful generation status does not by itself confirm the target project builds or preserves source behavior.</span></div>
 </section>;
}
