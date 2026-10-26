import axios from 'axios';

// Use IPv4 explicitly: on this Windows setup Lexora Uvicorn binds 127.0.0.1:8010.
export const API_BASE_URL=import.meta.env.VITE_API_URL||'http://127.0.0.1:8010/api';
export const api=axios.create({baseURL:API_BASE_URL,timeout:180000,headers:{'Content-Type':'application/json'}});
export type Language='cpp'|'java'|'python';
export type ModelId='fine_tuned_hf'|'openai/gpt-oss-20b';
export type Health={status:string;database_connected:boolean;environment:string;timestamp:string};
export type AstMetrics={total_lines_of_code:number;function_count:number;class_count:number;loop_count:number;conditional_count:number;cyclomatic_complexity:number;complexity_rating:string};
export type Analysis={language:Language;metrics:AstMetrics;ast_tree_string:string};
export type TranslationResult={model_name:ModelId;translated_code:string;execution_time_seconds:number;file_path:string};
export type Migration={migration_id:string;source_language:string;target_language:string;ast_metrics:Record<string,number|string>;applied_rag_rules:Array<Record<string,unknown>>;results:TranslationResult[];repair_summaries?:Array<{model_name:string;total_attempts:number;final_status:string}>};
export type Compilation={migration_id:string;model_name:ModelId;status:'SUCCESS'|'FAILED';stdout:string;stderr:string;execution_time_seconds:number;error_type:string};
export type TargetFramework=string;
export type TargetFrameworkOption={id:string;label:string;language?:string;icon?:string;recommended?:boolean};
export type DetectedFramework={name:string;type:'node'|'spring'|'python'|'go'|'unknown';icon:string};
export type DetectedComponent={role:string;detected_framework:DetectedFramework};
export type ProjectProfile={kind:'single_component'|'multi_component'|'unknown';components:DetectedComponent[];data_platforms:string[];full_repository_migration_supported:boolean;warning:string};
export type ProjectUpload={migration_id:string;target_framework:TargetFramework;detected_framework:DetectedFramework;project_profile?:ProjectProfile;source_type:DetectedFramework['type'];source_tree:string[];target_tree:string[];structural_map:Record<string,string>;total_files:number;next_step:string;available_targets:TargetFrameworkOption[]};
export type ProjectFileResult={source_path:string;target_path?:string;model_name?:string;latency_seconds?:number;status:string;reason?:string};
export type ProjectModelResult={model_name:string;status:string;target_tree:string[];files?:ProjectFileResult[];translated_files?:number;expected_files?:number;error?:string|null;latency_seconds?:number;wall_time_seconds?:number};
export type ProjectMigration={migration_id:string;source_type?:DetectedFramework['type'];target_framework:TargetFramework;source_tree:string[];target_tree:string[];translation_order:string[];files:ProjectFileResult[];model_results?:ProjectModelResult[];dependencies:{manifest:string;source_dependencies:string[];target_dependencies:string[]};target_root:string};
export type ProjectOutputs={migration_id:string;outputs?:Record<string,Record<string,string>>;models?:Record<string,Record<string,string>>};
export type ProjectStatus={migration_id:string;status:string;target_framework?:string;models:Record<string,{status:string;current_file?:string;completed_files?:number;total_files?:number}>};
export type ProjectDeployment={status:'RUNNING';migration_id:string;target_framework:string;host_port:number;base_url:string};
export type ProxyMethod='GET'|'POST';
export type ProjectProxyRequest={method:ProxyMethod;route:string;body:Record<string,unknown>};

export const getHealth=()=>api.get<Health>('/health').then(r=>r.data);
export const analyzeAST=(code:string,lang:Language)=>api.post<Analysis>('/analyze',{source_code:code,language:lang}).then(r=>r.data);
export const runMigration=(code:string,srcLang:string,tgtLang:string,models:ModelId[])=>api.post<Migration>('/migrate',{source_code:code,source_language:srcLang,target_language:tgtLang,selected_models:models},{timeout:600_000}).then(r=>r.data);
export const compileCode=(migrationId:string,modelName:ModelId)=>api.post<Compilation>('/compile',{migration_id:migrationId,model_name:modelName}).then(r=>r.data);

export const uploadRepository=(file:File,onProgress:(pct:number)=>void,targetFramework:TargetFramework='spring-boot')=>{
 const form=new FormData();form.append('file',file);form.append('target_framework',targetFramework);
 return api.post<Partial<ProjectUpload>>('/project/upload',form,{headers:{'Content-Type':'multipart/form-data'},onUploadProgress:event=>{if(event.total)onProgress(Math.round(event.loaded/event.total*100));},timeout:180000}).then(r=>normalizeProjectUpload(r.data));
};

function normalizeProjectUpload(payload:Partial<ProjectUpload>):ProjectUpload{
 const paths=payload.source_tree||[];
 // Keep the UI usable with an older API process while it is being restarted;
 // new backend responses remain the authoritative framework classification.
 const has=(name:string)=>paths.some(path=>path.toLowerCase().split('/').at(-1)===name);
 const inferred= (
  has('package.json')?{name:'Node.js · framework unknown',type:'node' as const,icon:'nodejs'}:
  has('pom.xml')||has('build.gradle')?{name:'Java / Spring Boot',type:'spring' as const,icon:'java'}:
  has('requirements.txt')||has('pipfile')?{name:'Python / FastAPI',type:'python' as const,icon:'python'}:
  has('go.mod')?{name:'Go / Fiber',type:'go' as const,icon:'golang'}:
  {name:'Generic Backend',type:'unknown' as const,icon:'code'}
 );
 const detected=payload.detected_framework?.type&&payload.detected_framework.type!=='unknown'?payload.detected_framework:inferred;
 const availableTargets=(Array.isArray(payload.available_targets)?payload.available_targets:[]).filter((item):item is TargetFrameworkOption=>!!item&&typeof item.id==='string'&&typeof item.label==='string');
 const fallbackTargets:TargetFrameworkOption[]=[{id:'spring-boot',label:'Spring Boot · Java',language:'Java',icon:'java',recommended:detected.type==='node'},{id:'go-fiber',label:'Go Fiber · Go',language:'Go',icon:'golang',recommended:detected.type==='python'}];
 const targets=availableTargets.length?availableTargets:fallbackTargets;
 const target=payload.target_framework&&targets.some(item=>item.id===payload.target_framework)?payload.target_framework:targets.find(item=>item.recommended)?.id||targets[0]?.id||'spring-boot';
 return {...payload,target_framework:target,available_targets:targets,detected_framework:detected,source_type:payload.source_type||detected.type} as ProjectUpload;
}
export const executeMigration=(migrationId:string,target:TargetFramework,modelNames?:string[])=>
 api.post<ProjectMigration>('/project/migrate',{
  migration_id:migrationId,
  target_framework:target,
  model_names:modelNames&&modelNames.length?modelNames:['openai/gpt-oss-20b','fine_tuned_hf']
 },{timeout:0}).then(r=>r.data);
export const getProjectOutputs=(migrationId:string)=>api.get<ProjectOutputs>(`/project/results/${encodeURIComponent(migrationId)}`,{timeout:180000}).then(r=>r.data);
export const getProjectStatus=(migrationId:string)=>api.get<ProjectStatus>(`/project/status/${encodeURIComponent(migrationId)}`,{timeout:10000}).then(r=>r.data);
export const deployProject=(migrationId:string,targetFramework:TargetFramework)=>api.post<ProjectDeployment>(`/project/deploy/${encodeURIComponent(migrationId)}`,{target_framework:targetFramework},{timeout:900000}).then(r=>r.data);
export const proxyProjectRequest=(migrationId:string,payload:ProjectProxyRequest)=>api.post(`/project/proxy/${encodeURIComponent(migrationId)}`,payload,{timeout:120000}).then(response=>({status:response.status,data:response.data}));
async function saveBlob(response: {data:Blob}, filename:string){
 const url=URL.createObjectURL(response.data);const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;document.body.appendChild(anchor);anchor.click();anchor.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export const downloadArtifact=async(migrationId:string,modelName?:string)=>{
 const response=await api.get<Blob>(`/project/download/${encodeURIComponent(migrationId)}`,{params:modelName?{model_name:modelName}:undefined,responseType:'blob',timeout:180000});
 await saveBlob(response,`lexora-${migrationId}${modelName?`-${modelName.replace(/[^a-zA-Z0-9_-]+/g,'-')}`:''}-target.zip`);
};
export const downloadMigrationReport=async(migrationId:string)=>{
 const response=await api.get<Blob>(`/project/report/${encodeURIComponent(migrationId)}`,{responseType:'blob',timeout:60000});
 await saveBlob(response,`lexora-${migrationId}-comparison-report.md`);
};

export type AstFileRecord = {
  file_path: string;
  language: string;
  loc: number;
  functions: number;
  classes: number;
  loops: number;
  conditionals: number;
  complexity: number;
  integrity: string;
  ast_tree_string: string;
};

export type RetrievedRagRule = {
  source_construct: string;
  target_construct: string;
  description: string;
  match_distance: number;
};

export type AstAnalysisResponse = {
  migration_id: string;
  total_loc: number;
  total_functions: number;
  total_classes: number;
  total_loops: number;
  total_branching: number;
  cyclomatic_complexity: number;
  complexity_rating: string;
  files: AstFileRecord[];
  retrieved_rules: RetrievedRagRule[];
};

export type ContractEndpoint = {
  method: string;
  route_path: string;
  backend_route_file: string;
  frontend_caller_file: string;
  status: 'VERIFIED_MATCH' | 'BACKEND_ONLY';
};

export type ContractTest = {
  test_num: string;
  target_endpoint: string;
  declared_component: string;
  caller_output: string;
  status: 'PASSED' | 'FAILED';
};

export type ContractVerificationResponse = {
  migration_id: string;
  sync_rate_percent: number;
  verified_count: number;
  total_endpoints: number;
  syntax_verification: string;
  endpoints: ContractEndpoint[];
  verification_tests: ContractTest[];
};

export type ImplementationCompleteness = {
  total_files: number;
  translated_modules: number;
  real_implementation_percent: number;
  placeholders_count: number;
  contract_sync_rate: number;
};

export type MathematicalFormulation = {
  formula: string;
  compilation_term_display: string;
  semantic_term_display: string;
  coverage_term_display: string;
  composite_score: number;
  explanation: string;
};

export type EvaluationMetricsResponse = {
  migration_id: string;
  compilation_syntax_validity: number;
  semantic_contract_accuracy: number;
  composite_confidence_score: number;
  pipeline_latency_seconds: number;
  implementation_completeness: ImplementationCompleteness;
  mathematical_formulation: MathematicalFormulation;
};

export type MigrationHistoryItem = {
  mode: string;
  migration_id: string;
  language_path: string;
  loc: number;
  accuracy: string;
  confidence: number;
  timestamp: string;
  status: string;
};

export type ReportContentResponse = {
  migration_id: string;
  format: 'markdown' | 'json' | 'html';
  content: string;
};

export const getAstAnalysis = (migrationId: string) =>
  api.get<AstAnalysisResponse>(`/project/ast-analysis/${encodeURIComponent(migrationId)}`).then(r => r.data);

export const getContractVerification = (migrationId: string) =>
  api.get<ContractVerificationResponse>(`/project/contract-verification/${encodeURIComponent(migrationId)}`).then(r => r.data);

export const getEvaluationMetrics = (migrationId: string) =>
  api.get<EvaluationMetricsResponse>(`/project/evaluation-metrics/${encodeURIComponent(migrationId)}`).then(r => r.data);

export const getMigrationHistory = () =>
  api.get<MigrationHistoryItem[]>('/project/history').then(r => r.data);

export const getReportContent = (migrationId: string, format: 'markdown' | 'json' | 'html' = 'markdown') =>
  api.get<ReportContentResponse>(`/project/report-content/${encodeURIComponent(migrationId)}`, { params: { format } }).then(r => r.data);

export const downloadReportFormatted = async (migrationId: string, format: 'markdown' | 'json' | 'html' = 'markdown') => {
  const ext = format === 'markdown' ? 'md' : format === 'html' ? 'html' : 'json';
  const response = await api.get<Blob>(`/project/report/${encodeURIComponent(migrationId)}`, {
    params: { format },
    responseType: 'blob',
    timeout: 60000,
  });
  await saveBlob(response, `lexora-${migrationId}-datascience-report.${ext}`);
};
