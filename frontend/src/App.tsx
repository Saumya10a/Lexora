import { Route, Routes } from 'react-router-dom';
import LandingPage from './pages/LandingPage';
import AppWorkspace from './pages/AppWorkspace';
export default function App(){return <Routes><Route path="/" element={<LandingPage/>}/><Route path="/app" element={<AppWorkspace/>}/><Route path="*" element={<LandingPage/>}/></Routes>}
