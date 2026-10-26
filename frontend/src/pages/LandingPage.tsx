import {ArrowDownRight,ArrowUpRight,Code2,GitBranch,MoveRight} from 'lucide-react';
import {Link} from 'react-router-dom';
import {motion} from 'framer-motion';
import poster from '../assets/background-struggle-poster.svg';

export default function LandingPage(){return <main className="landing-page">
  <video className="landing-video" autoPlay loop muted playsInline poster={poster} aria-label="Developer workspace film">{import.meta.env.VITE_LANDING_VIDEO_URL&&<source src={import.meta.env.VITE_LANDING_VIDEO_URL} type="video/mp4"/>}</video>
  <div className="landing-veil"/><div className="landing-grain"/>
  <header className="landing-nav"><Link to="/" className="brand brand-light"><span className="brand-mark">L</span> lexora</Link><div className="landing-nav-meta"><span className="live-dot"/> INTELLIGENCE SYSTEMS <span className="nav-divider"/> V 1.0</div><Link to="/app" className="nav-enter">Open workspace <ArrowUpRight size={15}/></Link></header>
  <section className="hero-copy"><motion.div initial={{opacity:0,y:18}} animate={{opacity:1,y:0}} transition={{duration:.8}} className="hero-overline"><span className="overline-mark"/> REASON ABOUT CODE. MOVE IT FORWARD.</motion.div><motion.h1 initial={{opacity:0,y:25}} animate={{opacity:1,y:0}} transition={{duration:.9,delay:.08}}>Cognitive<br/><em>Code Migration.</em></motion.h1><motion.div className="hero-bottom" initial={{opacity:0}} animate={{opacity:1}} transition={{duration:.8,delay:.28}}><p>From source to understood. Lexora reads structure, retrieves the right patterns, and brings multiple models to every migration.</p><Link to="/app" className="launch-button"><span>Launch workspace</span><span className="launch-arrow"><MoveRight size={17}/></span></Link></motion.div></section>
  <div className="landing-footer"><span><Code2 size={14}/> AST-AWARE TRANSLATION</span><span><GitBranch size={14}/> MULTI-MODEL REASONING</span><span className="footer-right">SCROLL TO EXPLORE <ArrowDownRight size={14}/></span></div>
</main>}
