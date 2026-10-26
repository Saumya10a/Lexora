import {useState} from 'react';
import Editor from '@monaco-editor/react';
import {AnimatePresence,motion} from 'framer-motion';
import {Activity,ArrowUpRight,CheckCircle2,ChevronRight,Loader2,Play,Radio,Send,Server,Terminal,TriangleAlert} from 'lucide-react';
import {deployProject,proxyProjectRequest as sendProxyRequest,type ProjectDeployment,type ProxyMethod,type TargetFramework} from '../../services/api';

type Props={migrationId:string;targetFramework:TargetFramework};
type ResponseView={status:number;data:unknown};

function responseText(data:unknown){
 if(typeof data==='string')return data;
 try{return JSON.stringify(data,null,2)??String(data);}catch{return String(data);}
}
function errorMessage(error:unknown){
 const value=error as {response?:{data?:unknown;status?:number};message?:string};
 if(value.response?.data!==undefined)return responseText(value.response.data);
 return value.message||'The request could not be completed.';
}

export default function ApiSandbox({migrationId,targetFramework}:Props){
 const [deployment,setDeployment]=useState<ProjectDeployment|null>(null);
 const [deploying,setDeploying]=useState(false);
 const [deployError,setDeployError]=useState('');
 const [method,setMethod]=useState<ProxyMethod>('GET');
 const [route,setRoute]=useState('/api/health');
 const [body,setBody]=useState(`{
  "name": "Lexora"
}`);
 const [sending,setSending]=useState(false);
 const [requestError,setRequestError]=useState('');
 const [result,setResult]=useState<ResponseView|null>(null);

 const deploy=async()=>{
  setDeploying(true);setDeployError('');setDeployment(null);setResult(null);setRequestError('');
  try{setDeployment(await deployProject(migrationId,targetFramework));}
  catch(error){setDeployError(errorMessage(error));}
  finally{setDeploying(false);}
 };
 const send=async()=>{
  setRequestError('');setResult(null);
  let parsedBody:Record<string,unknown>={};
  try{
   const parsed:unknown=JSON.parse(body||'{}');
   if(parsed===null||Array.isArray(parsed)||typeof parsed!=='object')throw new Error('Request body must be a JSON object.');
   parsedBody=parsed as Record<string,unknown>;
  }catch(error){setRequestError((error as Error).message||'Enter a valid JSON object.');return;}
  setSending(true);
  try{setResult(await sendProxyRequest(migrationId,{method,route:route.startsWith('/')?route:`/${route}`,body:parsedBody}));}
  catch(error){
   const response=(error as {response?:{data?:unknown;status?:number}}).response;
   if(response?.status!==undefined)setResult({status:response.status,data:response.data});
   else setRequestError(errorMessage(error));
  }finally{setSending(false);}
 };

 return <section className="api-sandbox" aria-labelledby="api-sandbox-title">
  <div className="sandbox-heading">
   <div className="sandbox-heading-copy">
    <span className="sandbox-kicker"><span className="sandbox-live-dot"/> POST-MIGRATION RUNTIME</span>
    <h2 id="api-sandbox-title">LIVE ENDPOINT TESTING</h2>
    <p>Deploy the translated service in an isolated local container, then inspect its real HTTP responses.</p>
   </div>
   <div className="sandbox-deploy-meta"><span><Server size={15}/>{targetFramework==='spring-boot'?'Spring Boot':'Go Fiber'} target</span><span><Activity size={15}/>Migration {migrationId.slice(0,8)}</span></div>
  </div>

  {!deployment?<div className="sandbox-deploy-card">
   <div className={`sandbox-deploy-mark ${deploying?'is-deploying':''}`}>{deploying?<Loader2 className="sandbox-spin" size={25}/>:<Radio size={25}/>}</div>
   <div className="sandbox-deploy-copy"><strong>{deploying?'Building Docker Image…':'Run the migrated API locally'}</strong><span>{deploying?'Building and starting the target service. This may take a few minutes.':'Lexora packages the target project and starts an ephemeral container for endpoint testing.'}</span></div>
   <button type="button" className="sandbox-deploy-button" onClick={deploy} disabled={deploying}>
    {deploying?<><Loader2 className="sandbox-spin" size={17}/> Building Docker Image…</>:<><Play size={16} fill="currentColor"/> Deploy to Local Sandbox <ArrowUpRight size={16}/></>}
   </button>
   <AnimatePresence>{deployError&&<motion.div className="sandbox-error deploy-error" role="alert" initial={{opacity:0,y:-5}} animate={{opacity:1,y:0}} exit={{opacity:0}}><TriangleAlert size={16}/><span>{deployError}</span></motion.div>}</AnimatePresence>
  </div>:<motion.div className="sandbox-console" initial={{opacity:0,y:14}} animate={{opacity:1,y:0}} transition={{duration:.24}}>
   <div className="sandbox-ready-bar"><div className="sandbox-ready-label"><CheckCircle2 size={17}/><span><strong>Sandbox online</strong><small>{deployment.base_url}</small></span></div><div className="sandbox-ready-right"><span className="sandbox-port">PORT {deployment.host_port}</span><button type="button" className="sandbox-redeploy" onClick={deploy} disabled={deploying}><Radio size={14}/> Redeploy</button></div></div>
   <div className="sandbox-request-grid">
    <div className="sandbox-request-form">
     <div className="sandbox-field-label"><span>REQUEST</span><span>HTTP</span></div>
     <div className="sandbox-route-row">
      <label className="sandbox-method-wrap"><span className="sr-only">HTTP method</span><select value={method} onChange={event=>setMethod(event.target.value as ProxyMethod)} disabled={sending}><option value="GET">GET</option><option value="POST">POST</option></select><ChevronRight size={14}/></label>
      <label className="sandbox-route-wrap"><span className="sr-only">Endpoint route</span><input value={route} onChange={event=>setRoute(event.target.value)} placeholder="/api/users" disabled={sending} onKeyDown={event=>{if(event.key==='Enter')void send();}}/></label>
      <button type="button" className="sandbox-send-button" onClick={()=>void send()} disabled={sending||!route.trim()}>{sending?<Loader2 className="sandbox-spin" size={16}/>:<Send size={15}/>}<span>{sending?'SENDING':'SEND REQUEST'}</span></button>
     </div>
     <p className="sandbox-route-hint">Requests are proxied to the running translated API. Use a route present in the generated controllers; a 404 at <code>/</code> can simply mean the app has no root route.</p>
     <div className="sandbox-body-heading"><div><span>REQUEST BODY</span><small>JSON</small></div><span>{method==='GET'?'Optional for GET':'Application / JSON'}</span></div>
     <div className="sandbox-json-editor"><Editor height="210px" language="json" theme="vs" value={body} onChange={value=>setBody(value||'{}')} options={{minimap:{enabled:false},fontSize:13,fontFamily:'DM Mono, monospace',lineNumbers:'on',scrollBeyondLastLine:false,automaticLayout:true,tabSize:2,wordWrap:'on',padding:{top:12,bottom:12},readOnly:sending}}/></div>
     {requestError&&<div className="sandbox-error" role="alert"><TriangleAlert size={15}/><span>{requestError}</span></div>}
    </div>
    <div className="sandbox-response">
     <div className="sandbox-response-head"><div><Terminal size={16}/><span>RESPONSE</span></div>{result&&<span className={`sandbox-http-status ${result.status>=200&&result.status<400?'status-success':'status-failed'}`}>HTTP {result.status}</span>}</div>
     <AnimatePresence mode="wait">
      {result?<motion.pre key="result" className="sandbox-terminal-output" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}>{responseText(result.data)}</motion.pre>:<div className="sandbox-terminal-empty"><Terminal size={25}/><strong>{sending?'Waiting for upstream response…':'Response will appear here'}</strong><span>Send a request to view the target API payload and HTTP status.</span></div>}
     </AnimatePresence>
     <div className="sandbox-response-foot"><span className="sandbox-terminal-dot"/> PROXIED THROUGH LEXORA</div>
    </div>
   </div>
  </motion.div>}
 </section>;
}
