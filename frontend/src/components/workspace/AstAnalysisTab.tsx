import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Code2,
  FileCode,
  GitBranch,
  Layers,
  Search,
  Sparkles,
  CheckCircle2,
  Cpu,
  BookOpen,
} from 'lucide-react';
import { getAstAnalysis, type AstAnalysisResponse } from '../../services/api';

interface AstAnalysisTabProps {
  migrationId: string;
}

export default function AstAnalysisTab({ migrationId }: AstAnalysisTabProps) {
  const [data, setData] = useState<AstAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedFileIdx, setSelectedFileIdx] = useState(0);
  const [ruleSearch, setRuleSearch] = useState('');

  useEffect(() => {
    let active = true;
    if (!migrationId) return;
    setLoading(true);
    setError('');
    getAstAnalysis(migrationId)
      .then((res) => {
        if (active) {
          setData(res);
          setSelectedFileIdx(0);
        }
      })
      .catch((err) => {
        if (active) {
          setError((err as any)?.response?.data?.detail || err.message || 'Failed to load AST analysis');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [migrationId]);

  if (loading) {
    return (
      <div className="tab-loading-state">
        <div className="tab-spinner" />
        <strong>Decomposing AST Abstract Syntax Trees...</strong>
        <span>Running Tree-sitter parser across staged source files</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="tab-error-state">
        <p>{error || 'No AST data found for this migration.'}</p>
      </div>
    );
  }

  const selectedFile = data.files[selectedFileIdx] || data.files[0];
  const filteredRules = (data.retrieved_rules || []).filter(
    (r) =>
      r.source_construct.toLowerCase().includes(ruleSearch.toLowerCase()) ||
      r.target_construct.toLowerCase().includes(ruleSearch.toLowerCase()) ||
      r.description.toLowerCase().includes(ruleSearch.toLowerCase())
  );

  return (
    <motion.div
      className="ast-analysis-container"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="tab-section-header">
        <div>
          <span className="tab-eyebrow">
            <span className="eyebrow-line" /> TREE-SITTER STRUCTURAL ANALYSIS
          </span>
          <h2>AST Structural Analysis & Complexity</h2>
          <p>
            Language-agnostic Concrete & Abstract Syntax Tree parsing with cyclomatic complexity decomposition and vector-retrieved RAG rules.
          </p>
        </div>
        <div className="tab-header-badge">
          <span className="badge-pulse" />
          <span>MIGRATION: {migrationId.slice(0, 8)}...</span>
        </div>
      </div>

      {/* Top 5 Metric Stat Cards */}
      <div className="ast-stat-grid">
        <div className="ast-stat-card">
          <div className="ast-stat-icon">
            <FileCode size={20} />
          </div>
          <div className="ast-stat-content">
            <small>TOTAL LOC</small>
            <strong>{data.total_loc.toLocaleString()}</strong>
            <span>Active code lines</span>
          </div>
        </div>

        <div className="ast-stat-card">
          <div className="ast-stat-icon">
            <Code2 size={20} />
          </div>
          <div className="ast-stat-content">
            <small>FUNCTIONS</small>
            <strong>{data.total_functions}</strong>
            <span>Parsed signatures</span>
          </div>
        </div>

        <div className="ast-stat-card">
          <div className="ast-stat-icon">
            <Layers size={20} />
          </div>
          <div className="ast-stat-content">
            <small>CLASSES</small>
            <strong>{data.total_classes}</strong>
            <span>Declared models & types</span>
          </div>
        </div>

        <div className="ast-stat-card">
          <div className="ast-stat-icon">
            <GitBranch size={20} />
          </div>
          <div className="ast-stat-content">
            <small>LOOPS / BRANCHING</small>
            <strong>
              {data.total_loops} / {data.total_branching}
            </strong>
            <span>Control flow structures</span>
          </div>
        </div>

        <div className="ast-stat-card highlight">
          <div className="ast-stat-icon complexity">
            <Cpu size={20} />
          </div>
          <div className="ast-stat-content">
            <small>CYCLOMATIC COMPLEXITY</small>
            <strong>{data.cyclomatic_complexity}</strong>
            <span className="complexity-pill">{data.complexity_rating}</span>
          </div>
        </div>
      </div>

      {/* AST S-Expression Inspector */}
      <div className="ast-inspector-card">
        <div className="ast-inspector-header">
          <div className="ast-inspector-title">
            <Sparkles size={16} />
            <strong>Tree-Sitter Concrete Syntax Tree (CST / S-Expression)</strong>
          </div>
          <div className="ast-file-select-wrap">
            <label htmlFor="ast-file-select">File:</label>
            <select
              id="ast-file-select"
              value={selectedFileIdx}
              onChange={(e) => setSelectedFileIdx(Number(e.target.value))}
            >
              {data.files.map((file, idx) => (
                <option key={file.file_path} value={idx}>
                  {file.file_path} ({file.loc} LOC)
                </option>
              ))}
            </select>
          </div>
        </div>

        {selectedFile && (
          <div className="ast-file-meta-bar">
            <div className="file-meta-pills">
              <span className="meta-pill integrity">
                <CheckCircle2 size={13} /> {selectedFile.integrity}
              </span>
              <span className="meta-pill">Lang: {selectedFile.language.toUpperCase()}</span>
              <span className="meta-pill">LOC: {selectedFile.loc}</span>
              <span className="meta-pill">Functions: {selectedFile.functions}</span>
              <span className="meta-pill">Classes: {selectedFile.classes}</span>
              <span className="meta-pill">Complexity: {selectedFile.complexity}</span>
            </div>
            <span className="s-exp-note">S-Expression Parser Representation</span>
          </div>
        )}

        <pre className="ast-sexp-viewer">
          <code>
            {selectedFile?.ast_tree_string ||
              ';; No syntax tree could be extracted for this file.'}
          </code>
        </pre>
      </div>

      {/* Retrieved RAG Migration Rules Table */}
      <div className="ast-rules-card">
        <div className="ast-rules-header">
          <div className="ast-rules-title">
            <BookOpen size={18} />
            <div>
              <strong>Retrieved RAG Migration Rules</strong>
              <span>Vector embeddings matched against ChromaDB knowledge store</span>
            </div>
          </div>
          <div className="ast-search-wrap">
            <Search size={14} />
            <input
              type="text"
              placeholder="Filter rules by construct or target..."
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
            />
          </div>
        </div>

        <div className="ast-rules-table-container">
          <table className="ast-rules-table">
            <thead>
              <tr>
                <th>Source Construct</th>
                <th>Target Construct</th>
                <th>Description</th>
                <th>Match Distance</th>
              </tr>
            </thead>
            <tbody>
              {filteredRules.length > 0 ? (
                filteredRules.map((rule, idx) => (
                  <tr key={idx}>
                    <td>
                      <code className="source-code-tag">{rule.source_construct}</code>
                    </td>
                    <td>
                      <code className="target-code-tag">{rule.target_construct}</code>
                    </td>
                    <td>{rule.description}</td>
                    <td>
                      <span className="distance-badge">
                        {rule.match_distance.toFixed(3)}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="empty-rules">
                    No matching migration rules found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </motion.div>
  );
}
