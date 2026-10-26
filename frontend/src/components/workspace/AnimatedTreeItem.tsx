import {useState} from 'react';
import {AnimatePresence,motion} from 'framer-motion';
import {ChevronRight,FileCode2,Folder,FolderOpen} from 'lucide-react';
import type {TreeNode} from './DualFileTree';

type Props={node:TreeNode;depth?:number;selectedPath?:string;onSelect:(path:string)=>void};

export default function AnimatedTreeItem({node,depth=0,selectedPath,onSelect}:Props){
 const [open,setOpen]=useState(depth===0);
 const isFolder=node.children.length>0;
 return <motion.div layout transition={{type:'spring',stiffness:220,damping:26}} className="tree-node-wrap">
  <motion.button layout type="button" className={`tree-row ${selectedPath===node.path?'is-selected':''} ${isFolder?'is-folder':''}`} style={{paddingLeft:12+depth*15}} onClick={()=>isFolder?setOpen(v=>!v):onSelect(node.path)}>
   {isFolder?<motion.span className="tree-chevron" animate={{rotate:open?90:0}} transition={{type:'spring',stiffness:200,damping:18}}><ChevronRight size={13}/></motion.span>:<span className="tree-chevron-spacer"/>}
   {isFolder?(open?<FolderOpen size={14}/>:<Folder size={14}/>):<FileCode2 size={13}/>}
   <span className="tree-name" title={node.path}>{node.name}</span>
  </motion.button>
  <AnimatePresence initial={false}>
   {isFolder&&open&&<motion.div className="tree-children" initial={{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={{opacity:0,height:0}} transition={{type:'spring',stiffness:220,damping:26}}>
    {node.children.map((child,index)=><motion.div key={child.path} initial={{opacity:0,y:-4}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{delay:index*.018,duration:.18}}><AnimatedTreeItem node={child} depth={depth+1} selectedPath={selectedPath} onSelect={onSelect}/></motion.div>)}
   </motion.div>}
  </AnimatePresence>
 </motion.div>;
}

