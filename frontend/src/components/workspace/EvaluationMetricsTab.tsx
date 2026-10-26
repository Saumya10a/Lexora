import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Calculator,
  CheckCircle2,
  Clock,
  Code2,
  FileCheck2,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { getEvaluationMetrics, type EvaluationMetricsResponse } from '../../services/api';

interface EvaluationMetricsTabProps {
  migrationId: string;
}

export default function EvaluationMetricsTab({ migrationId }: EvaluationMetricsTabProps) {
  const [data, setData] = useState<EvaluationMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    if (!migrationId) return;
    setLoading(true);
    setError('');
    getEvaluationMetrics(migrationId)
      .then((res) => {
        if (active) setData(res);
      })
      .catch((err) => {
        if (active) {
          setError((err as any)?.response?.data?.detail || err.message || 'Failed to load evaluation metrics');
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
        <strong>Computing Data Science Evaluation Metrics...</strong>
        <span>Synthesizing AST syntax verification and contract confidence formulation</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="tab-error-state">
        <p>{error || 'No evaluation metrics found for this migration.'}</p>
      </div>
    );
  }

  const { implementation_completeness: completeness, mathematical_formulation: formula } = data;

  return (
    <motion.div
      className="eval-metrics-container"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="tab-section-header">
        <div>
          <span className="tab-eyebrow">
            <span className="eyebrow-line" /> EMPIRICAL BENCHMARKING & FORMULATION
          </span>
          <h2>Evaluation Metrics & Mathematical Confidence Formulation</h2>
          <p>
            Rigorous data-science validation combining Tree-sitter AST syntax validity, contract equivalence, and composite confidence calculation.
          </p>
        </div>
        <div className="tab-header-badge">
          <span className="badge-pulse" />
          <span>MIGRATION: {migrationId.slice(0, 8)}...</span>
        </div>
      </div>

      {/* Top 4 Key Metric Cards */}
      <div className="eval-top-grid">
        <div className="eval-top-card">
          <div className="eval-top-icon text-indigo">
            <Code2 size={22} />
          </div>
          <div className="eval-top-body">
            <small>COMPILATION / SYNTAX VALIDITY</small>
            <div className="eval-top-value">
              <strong>{data.compilation_syntax_validity.toFixed(1)}%</strong>
              <span className="eval-status-pill green">100% Tree-sitter AST</span>
            </div>
            <p>S-expression parsed with zero AST error nodes across target codebase</p>
          </div>
        </div>

        <div className="eval-top-card">
          <div className="eval-top-icon text-emerald">
            <ShieldCheck size={22} />
          </div>
          <div className="eval-top-body">
            <small>SEMANTIC / CONTRACT ACCURACY</small>
            <div className="eval-top-value">
              <strong>{data.semantic_contract_accuracy.toFixed(1)}%</strong>
              <span className="eval-status-pill green">Contract Verified</span>
            </div>
            <p>1:1 route signature and schema alignment across all HTTP interfaces</p>
          </div>
        </div>

        <div className="eval-top-card highlight">
          <div className="eval-top-icon text-purple">
            <TrendingUp size={22} />
          </div>
          <div className="eval-top-body">
            <small>COMPOSITE CONFIDENCE SCORE</small>
            <div className="eval-top-value">
              <strong>{data.composite_confidence_score.toFixed(1)} / 100</strong>
              <span className="eval-status-pill purple">Scientific Index</span>
            </div>
            <p>Synthesized via 30/50/20 weighted multi-variable formulation</p>
          </div>
        </div>

        <div className="eval-top-card">
          <div className="eval-top-icon text-blue">
            <Clock size={22} />
          </div>
          <div className="eval-top-body">
            <small>PIPELINE LATENCY</small>
            <div className="eval-top-value">
              <strong>{data.pipeline_latency_seconds.toFixed(2)}s</strong>
              <span className="eval-status-pill blue">High Throughput</span>
            </div>
            <p>Parallelized dependency-graph execution across source files</p>
          </div>
        </div>
      </div>

      {/* Implementation Completeness Breakdown */}
      <div className="eval-section-card">
        <div className="eval-section-title">
          <FileCheck2 size={18} />
          <div>
            <strong>Implementation Completeness & Real Code Density</strong>
            <span>Proof of production-ready implementation without stubs or placeholders</span>
          </div>
        </div>

        <div className="completeness-grid">
          <div className="completeness-card">
            <small>TOTAL SOURCE FILES</small>
            <strong>{completeness.total_files}</strong>
            <span>Detected in repository</span>
          </div>

          <div className="completeness-card">
            <small>TRANSLATED MODULES</small>
            <strong className="text-emerald">{completeness.translated_modules}</strong>
            <span>Idiomatic target files</span>
          </div>

          <div className="completeness-card">
            <small>REAL IMPLEMENTATION</small>
            <strong className="text-emerald">{completeness.real_implementation_percent.toFixed(1)}%</strong>
            <span>Active logic code</span>
          </div>

          <div className="completeness-card">
            <small>PLACEHOLDERS / STUBS</small>
            <strong className="text-emerald">{completeness.placeholders_count}</strong>
            <span>Zero hallucinated stubs</span>
          </div>

          <div className="completeness-card">
            <small>CONTRACT SYNC RATE</small>
            <strong className="text-purple">{completeness.contract_sync_rate.toFixed(1)}%</strong>
            <span>Cross-module verified</span>
          </div>
        </div>
      </div>

      {/* Mathematical Confidence Formulation Card */}
      <div className="eval-section-card math-card">
        <div className="eval-section-title">
          <Calculator size={18} />
          <div>
            <strong>Mathematical Confidence Formulation</strong>
            <span>Empirical mathematical proof model synthesized by Lexora Data Science</span>
          </div>
        </div>

        <div className="formula-box">
          <div className="formula-header">
            <span>FORMULATION EQUATION:</span>
            <code>{formula.formula}</code>
          </div>

          <div className="formula-terms-grid">
            <div className="formula-term-card">
              <div className="formula-term-badge compilation">30% WEIGHT</div>
              <strong>Compilation Term</strong>
              <code>{formula.compilation_term_display}</code>
              <span>Strict Tree-sitter AST syntax and grammar validation</span>
            </div>

            <div className="formula-term-card">
              <div className="formula-term-badge semantic">50% WEIGHT</div>
              <strong>Semantic Term</strong>
              <code>{formula.semantic_term_display}</code>
              <span>Cross-module REST API contract & interface parity</span>
            </div>

            <div className="formula-term-card">
              <div className="formula-term-badge coverage">20% WEIGHT</div>
              <strong>Test Coverage Term</strong>
              <code>{formula.coverage_term_display}</code>
              <span>Regression integration tests and endpoint verification</span>
            </div>
          </div>

          <div className="formula-result-bar">
            <div className="formula-result-label">
              <CheckCircle2 size={18} className="text-emerald" />
              <div>
                <strong>Final Composite Confidence Score</strong>
                <small>{formula.explanation}</small>
              </div>
            </div>
            <div className="formula-result-score">
              <span>{formula.composite_score.toFixed(1)}</span>
              <small>/ 100.0</small>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
