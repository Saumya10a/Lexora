import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Clock,
  ExternalLink,
  FolderGit2,
  RefreshCw,
  Search,
  Check,
  Copy,
} from 'lucide-react';
import { getMigrationHistory, type MigrationHistoryItem } from '../../services/api';

interface DashboardHistoryTabProps {
  onInspect: (migrationId: string) => void;
  activeMigrationId?: string;
}

export default function DashboardHistoryTab({ onInspect, activeMigrationId }: DashboardHistoryTabProps) {
  const [runs, setRuns] = useState<MigrationHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchHistory = () => {
    setLoading(true);
    setError('');
    getMigrationHistory()
      .then((data) => {
        setRuns(data);
      })
      .catch((err) => {
        setError((err as any)?.response?.data?.detail || err.message || 'Failed to load migration history');
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const copyToClipboard = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const filteredRuns = runs.filter(
    (run) =>
      run.migration_id.toLowerCase().includes(search.toLowerCase()) ||
      run.language_path.toLowerCase().includes(search.toLowerCase()) ||
      run.mode.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <motion.div
      className="dashboard-history-container"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="tab-section-header">
        <div>
          <span className="tab-eyebrow">
            <span className="eyebrow-line" /> PERSISTENT MIGRATION AUDIT TRAIL
          </span>
          <h2>Dashboard History & Previous Runs</h2>
          <p>
            Inspect and load completed multi-model translation runs directly into active AST inspection, contract verification, and report viewers.
          </p>
        </div>

        <div className="history-header-actions">
          <button type="button" className="reverify-button" onClick={fetchHistory} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} />
            {loading ? 'Refreshing...' : 'Refresh History'}
          </button>
        </div>
      </div>

      <div className="history-table-card">
        <div className="history-card-header">
          <div className="history-card-title">
            <FolderGit2 size={18} />
            <div>
              <strong>Recent Migration Runs</strong>
              <span>MongoDB collection & output filesystem repository records</span>
            </div>
          </div>

          <div className="ast-search-wrap">
            <Search size={14} />
            <input
              type="text"
              placeholder="Filter by UUID or language..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="tab-loading-state">
            <div className="tab-spinner" />
            <span>Scanning migration records...</span>
          </div>
        ) : error ? (
          <div className="tab-error-state">
            <p>{error}</p>
          </div>
        ) : (
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Mode</th>
                  <th>Migration ID</th>
                  <th>Language Path</th>
                  <th>LOC</th>
                  <th>Accuracy</th>
                  <th>Confidence</th>
                  <th>Timestamp</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.length > 0 ? (
                  filteredRuns.map((run) => {
                    const isActive = activeMigrationId === run.migration_id;
                    return (
                      <tr key={run.migration_id} className={isActive ? 'active-run-row' : ''}>
                        <td>
                          <span className="mode-pill-badge">{run.mode}</span>
                        </td>
                        <td>
                          <div className="id-cell">
                            <code>{run.migration_id.slice(0, 8)}...</code>
                            <button
                              type="button"
                              className="copy-btn"
                              onClick={(e) => copyToClipboard(run.migration_id, e)}
                              title="Copy full Migration UUID"
                            >
                              {copiedId === run.migration_id ? (
                                <Check size={12} className="text-emerald" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                            {isActive && <span className="active-pill">ACTIVE</span>}
                          </div>
                        </td>
                        <td>
                          <span className="lang-path-cell">{run.language_path}</span>
                        </td>
                        <td>
                          <span className="loc-cell">{run.loc.toLocaleString()}</span>
                        </td>
                        <td>
                          <span className="accuracy-pill text-emerald">{run.accuracy}</span>
                        </td>
                        <td>
                          <span className="confidence-pill">{run.confidence.toFixed(1)}</span>
                        </td>
                        <td>
                          <span className="timestamp-cell">
                            <Clock size={12} /> {run.timestamp}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            type="button"
                            className="inspect-btn"
                            onClick={() => onInspect(run.migration_id)}
                          >
                            <ExternalLink size={13} />
                            Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={8} className="empty-rules">
                      No migration records match your search criteria.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </motion.div>
  );
}
