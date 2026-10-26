import { Canvas } from '@react-three/fiber';
import { Float, Icosahedron, Sphere, Torus } from '@react-three/drei';

function Scene(){return <>
  <ambientLight intensity={1.6}/><directionalLight position={[5,8,6]} intensity={2.5} color="#fffdf5"/><pointLight position={[-5,-2,2]} intensity={18} color="#aad9ce"/>
  <Float speed={0.65} rotationIntensity={0.12} floatIntensity={0.4}><Sphere args={[1.05,48,48]} position={[4.8,2.7,-3]}><meshPhysicalMaterial color="#d9ebe4" roughness={0.15} metalness={0.08} clearcoat={0.9} transparent opacity={0.38}/></Sphere></Float>
  <Float speed={0.8} rotationIntensity={0.1} floatIntensity={0.3}><Icosahedron args={[.8,1]} position={[-5,-2.7,-4]}><meshStandardMaterial color="#e8e1d5" roughness={0.52} metalness={0.04} transparent opacity={0.52}/></Icosahedron></Float>
  <Float speed={0.55} rotationIntensity={0.08} floatIntensity={0.2}><Torus args={[.7,.035,16,80]} position={[5,-3,-5]} rotation={[.7,.4,.5]}><meshStandardMaterial color="#b1d3c6" roughness={0.26} metalness={0.12} transparent opacity={0.43}/></Torus></Float>
</>}
export default function SoftGeometryBackground(){return <div className="geometry-bg" aria-hidden="true"><Canvas camera={{position:[0,0,10],fov:42}} dpr={[1,1.4]}><Scene/></Canvas></div>}
