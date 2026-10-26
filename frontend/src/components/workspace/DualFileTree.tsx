import {useMemo} from 'react';
import {ArrowLeftRight,Braces,Layers3,Waypoints} from 'lucide-react';
import type {ProjectMigration,ProjectUpload,TargetFramework} from '../../services/api';
import AnimatedTreeItem from './AnimatedTreeItem';
import FrameworkBridge from './FrameworkBridge';

export type TreeNode={name:string;path:string;children:TreeNode[]};
type Props={upload:ProjectUpload;migration?:ProjectMigration|null;framework:TargetFramework;onFrameworkChange:(framework:TargetFramework)=>void;selectedPath?:string;onSelectPath:(path:string)=>void;remapping?:boolean};

function makeTree(paths:string[]):TreeNode{
 const root:TreeNode={name:'project',path:'',children:[]};
 for(const filePath of paths){let cursor=root;const parts=filePath.replaceAll('\\','/').split('/').filter(Boolean);parts.forEach((part,index)=>{const path=parts.slice(0,index+1).join('/');let child=cursor.children.find(node=>node.name===part);if(!child){child={name:part,path,children:[]};cursor.children.push(child);}cursor=child;});}
 const sort=(node:TreeNode)=>{node.children.sort((a,b)=>Number(b.children.length>0)-Number(a.children.length>0)||a.name.localeCompare(b.name));node.children.forEach(sort);};sort(root);return root;
}
function countNodes(node:TreeNode):number{return node.children.reduce((sum,child)=>sum+1+countNodes(child),0);}

export default function DualFileTree({upload,migration,framework,onFrameworkChange,selectedPath,onSelectPath,remapping=false}:Props){
 const source=useMemo(()=>makeTree(upload.source_tree),[upload.source_tree]);
 const targetPaths=migration?.target_tree||upload.target_tree;
 const target=useMemo(()=>makeTree(targetPaths),[targetPaths]);
 const selectedTarget=selectedPath?upload.structural_map[selectedPath]:undefined;
 const phaseFiles=migration?.files||[];
 const translated=phaseFiles.filter(file=>file.status==='TRANSLATED').length;
 return <section className="dual-tree-grid">
  <aside className="tree-pane source-tree-pane">
   <div className="tree-pane-heading"><div><span className="tree-kicker">SOURCE REPOSITORY</span><h3>Original structure</h3></div><span className="file-count">{countNodes(source)} items</span></div>
   <div className="tree-project-root"><Braces size={14}/><span>{upload.source_tree[0]?.split('/')[0]||'repository'}</span><small>{upload.total_files} files</small></div>
   <div className="tree-scroll"><AnimatedTreeItem node={source} onSelect={onSelectPath} selectedPath={selectedPath}/></div>
   <div className="tree-footer"><span className="tree-status-dot"/> ZIP ingested · source preserved</div>
  </aside>

  <div className="mapping-center">
   <div className="mapping-head"><div className="mapping-icon"><Waypoints size={17}/></div><div><span className="tree-kicker">STRUCTURAL MAPPING</span><h3>{migration?'Translation DAG':'Framework bridge'}</h3></div></div>
   <FrameworkBridge source={upload.detected_framework} target={framework} availableTargets={upload.available_targets} onTargetChange={onFrameworkChange} disabled={remapping||!!migration}/>
   <div className="mapping-line"/>
   {selectedPath?<div className="selected-map-card"><span className="tree-kicker">SELECTED FILE MAPPING</span><div className="map-path source-path">{selectedPath}</div><ArrowLeftRight size={15}/><div className="map-path target-path">{selectedTarget||'Mapping generated during migration'}</div></div>:<div className="mapping-empty"><Layers3 size={24}/><strong>Select a source file</strong><span>View its target path mapping and follow the generated project structure.</span></div>}
   <div className="layer-flow"><span className="tree-kicker">TARGET LAYERS</span>{['Entities','Repositories','Services','Controllers'].map((name,index)=><div className={`layer-step ${migration&&translated>index?'layer-done':''}`} key={name}><span>{String(index+1).padStart(2,'0')}</span><b>{name}</b><i/></div>)}</div>
   {remapping&&<div className="remap-state"><span className="remap-spinner"/> Refreshing target architecture…</div>}
  </div>

  <aside className="tree-pane target-tree-pane">
   <div className="tree-pane-heading target-heading"><div><span className="tree-kicker">TARGET REPOSITORY</span><h3>Mapped structure</h3></div><span className="file-count">{countNodes(target)} items</span></div>
   <div className="tree-project-root target-root"><Braces size={14}/><span>{framework==='spring-boot'?'spring-boot-project':'go-fiber-project'}</span><small>{migration?`${translated} translated`:'preview'}</small></div>
   <div className="tree-scroll"><AnimatedTreeItem node={target} onSelect={path=>{const sourcePath=Object.entries(upload.structural_map).find(([,targetPath])=>targetPath===path)?.[0];if(sourcePath)onSelectPath(sourcePath);}} selectedPath={selectedTarget}/></div>
   <div className="tree-footer"><span className={migration?'tree-status-dot':'tree-status-dot idle'}/>{migration?'DAG output · target ready':'Select architecture to remap'}</div>
  </aside>
 </section>;
}
