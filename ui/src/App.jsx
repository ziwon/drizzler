import React, { useState, useEffect } from 'react';
import {
  Droplets,
  Trash2,
  RefreshCw,
  Loader2,
  ExternalLink,
  FileText,
  Video,
  Image as ImageIcon,
  ArrowUpRight,
  Layers,
  Sparkles,
  Download,
  Github,
  Book,
  Play,
  Clock,
  CheckCircle2,
  XCircle,
  Subtitles,
  X,
  Eye
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs) {
  return twMerge(clsx(inputs));
}

const API_BASE = 'http://localhost:8000';

function App() {
  const [urls, setUrls] = useState('');
  const [options, setOptions] = useState({
    write_video: true,
    write_info_json: true,
    write_thumbnail: false,
    write_subs: true,
    write_txt: true,
    summarize: true,
    summarize_mode: 'default',  // 'default' or 'lecture'
    rate: 1.0,
    concurrency: 5,
    llm_model: ''
  });
  const [jobs, setJobs] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  // Modal state for file preview
  const [previewModal, setPreviewModal] = useState({
    isOpen: false,
    content: '',
    filename: '',
    downloadUrl: '',
    loading: false,
    fileType: 'text' // 'text', 'markdown', 'json'
  });

  const fetchJobs = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs`);
      const data = await response.json();
      setJobs(data);
    } catch (error) {
      console.error('Failed to fetch jobs:', error);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!urls.trim()) return;

    setSubmitting(true);
    try {
      const urlList = urls.split('\n').map(u => u.trim()).filter(u => u);
      const response = await fetch(`${API_BASE}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          urls: urlList,
          ...options
        })
      });

      if (response.ok) {
        setUrls('');
        fetchJobs();
      }
    } catch (error) {
      console.error('Failed to submit job:', error);
    } finally {
      setSubmitting(false);
    }
  };

  const deleteJob = async (id) => {
    try {
      await fetch(`${API_BASE}/api/jobs/${id}`, { method: 'DELETE' });
      fetchJobs();
    } catch (error) {
      console.error('Failed to delete job:', error);
    }
  };

  const previewFile = async (jobId, filename) => {
    const ext = filename.split('.').pop().toLowerCase();
    const isPreviewable = ['txt', 'md', 'json', 'vtt', 'srt'].includes(ext);

    if (!isPreviewable) return null; // Don't preview non-text files

    const downloadUrl = `${API_BASE}/api/jobs/${jobId}/files/${filename}`;

    setPreviewModal({
      isOpen: true,
      content: '',
      filename,
      downloadUrl,
      loading: true,
      fileType: ext === 'md' ? 'markdown' : ext === 'json' ? 'json' : 'text'
    });

    try {
      const response = await fetch(downloadUrl);
      const text = await response.text();
      setPreviewModal(prev => ({
        ...prev,
        content: text,
        loading: false
      }));
    } catch (error) {
      console.error('Failed to fetch file:', error);
      setPreviewModal(prev => ({
        ...prev,
        content: 'Failed to load file content.',
        loading: false
      }));
    }
  };

  const closePreview = () => {
    setPreviewModal({
      isOpen: false,
      content: '',
      filename: '',
      downloadUrl: '',
      loading: false,
      fileType: 'text'
    });
  };

  const currentTime = new Date().toLocaleString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  });

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      {/* Animated Background */}
      <div className="gradient-mesh" />
      <div className="noise-overlay" />

      {/* Main Container */}
      <div className="main-container w-full max-w-[1100px] animate-fade-in">
        {/* Navigation */}
        <nav className="navbar">
          <div className="navbar-brand">
            <div className="navbar-logo">
              <Droplets size={20} className="text-white" />
            </div>
            <span className="navbar-title">Drizzler</span>
          </div>
          <div className="navbar-links">
            <a
              href="https://github.com/ziwon/drizzler"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-pill"
            >
              <Github size={16} />
              <span>GitHub</span>
            </a>
            <a href="#docs" className="btn-pill active">
              <Book size={16} />
              <span>Docs</span>
            </a>
          </div>
        </nav>

        {/* Content */}
        <div className="content-wrapper">
          {/* Left Column - Submission */}
          <div className="space-y-0">
            {/* Hero */}
            <div className="mb-6">
              <h1 className="heading-hero">
                Intelligent<br />
                <span className="gradient-text">Data Extraction</span>
              </h1>
              <p className="text-subtitle">
                Effortlessly extract, process, and analyze data from any source with advanced AI-driven technology.
              </p>
            </div>

            {/* URL Input */}
            <form onSubmit={handleSubmit}>
              <div className="input-container">
                <textarea
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                  placeholder="Paste URL to extract data..."
                  className="input-field"
                />
              </div>

              {/* Options Grid with Toggle Switches */}
              <div className="options-grid">
                <ToggleOption
                  icon={<Video size={18} />}
                  label="Video"
                  active={options.write_video}
                  onClick={() => setOptions({ ...options, write_video: !options.write_video })}
                />
                <ToggleOption
                  icon={<Layers size={18} />}
                  label="Metadata"
                  active={options.write_info_json}
                  onClick={() => setOptions({ ...options, write_info_json: !options.write_info_json })}
                />
                <ToggleOption
                  icon={<ImageIcon size={18} />}
                  label="Thumbnails"
                  active={options.write_thumbnail}
                  onClick={() => setOptions({ ...options, write_thumbnail: !options.write_thumbnail })}
                />
                <ToggleOption
                  icon={<Subtitles size={18} />}
                  label="Subtitles"
                  active={options.write_subs}
                  onClick={() => setOptions({ ...options, write_subs: !options.write_subs })}
                />
                <ToggleOption
                  icon={<Sparkles size={18} />}
                  label="AI Summary"
                  active={options.summarize}
                  onClick={() => setOptions({ ...options, summarize: !options.summarize })}
                />
                <ToggleOption
                  icon={<Book size={18} />}
                  label="Lecture Mode"
                  active={options.summarize_mode === 'lecture'}
                  onClick={() => setOptions({
                    ...options,
                    summarize_mode: options.summarize_mode === 'lecture' ? 'default' : 'lecture',
                    summarize: true  // Auto-enable summarize when lecture mode is on
                  })}
                  hint="Detailed blog-style summary for lectures"
                />
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={submitting || !urls.trim()}
                className="btn-primary"
              >
                {submitting ? (
                  <>
                    <Loader2 size={20} className="animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : (
                  <>
                    <span>Start Extraction</span>
                    <ArrowUpRight size={18} />
                  </>
                )}
              </button>
            </form>
          </div>

          {/* Right Column - Jobs Panel */}
          <div className="jobs-panel">
            <div className="jobs-header">
              <div className="pulse-dot" />
              <h2>Active Jobs</h2>
            </div>

            <div className="space-y-3 max-h-[500px] overflow-y-auto">
              {jobs.length === 0 ? (
                <div className="empty-state">
                  <Droplets className="empty-state-icon" />
                  <p className="empty-state-text">No active jobs</p>
                </div>
              ) : (
                jobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onDelete={() => deleteJob(job.id)}
                    onPreview={(filename) => previewFile(job.id, filename)}
                  />
                ))
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="footer">
          <span className="footer-time">{currentTime}</span>
        </div>
      </div>

      {/* File Preview Modal */}
      <FilePreviewModal
        isOpen={previewModal.isOpen}
        onClose={closePreview}
        content={previewModal.content}
        filename={previewModal.filename}
        downloadUrl={previewModal.downloadUrl}
        loading={previewModal.loading}
        fileType={previewModal.fileType}
      />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COMPONENTS
   ═══════════════════════════════════════════════════════════════════════════ */

function ToggleOption({ icon, label, active, onClick, disabled, hint }) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      className={cn(
        "option-toggle",
        active && "active",
        disabled && "opacity-40 cursor-not-allowed"
      )}
      title={hint}
    >
      <div className="option-info">
        <span className="option-icon">{icon}</span>
        <span className="option-label">{label}</span>
      </div>
      <div className="toggle-switch" />
    </div>
  );
}

function JobCard({ job, onDelete, onPreview }) {
  const statusConfig = {
    pending: {
      badge: 'badge-queued',
      label: 'Queued'
    },
    running: {
      badge: 'badge-running',
      label: 'Running'
    },
    completed: {
      badge: 'badge-completed',
      label: 'Completed'
    },
    failed: {
      badge: 'badge-failed',
      label: 'Failed'
    }
  };

  const config = statusConfig[job.status] || statusConfig.pending;
  const displayUrl = job.urls[0]?.replace(/^https?:\/\//, '').slice(0, 30);

  // Get video progress info from API
  const videoProgress = job.video_progress;
  const currentStage = job.current_stage || '';

  // Format bytes to human readable
  const formatBytes = (bytes) => {
    if (!bytes) return '';
    if (bytes > 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  };

  // Check if file is previewable
  const isPreviewable = (filename) => {
    const ext = filename.split('.').pop().toLowerCase();
    return ['txt', 'md', 'json', 'vtt', 'srt'].includes(ext);
  };

  return (
    <div className="job-card animate-fade-in">
      <div className="job-header">
        <span className="job-url" title={job.urls[0]}>
          {displayUrl}...
        </span>
        <span className={cn("badge", config.badge)}>
          {config.label}
        </span>
      </div>

      {/* Current Stage */}
      {job.status === 'running' && currentStage && (
        <div className="current-stage">
          <Loader2 size={12} className="animate-spin" />
          <span>{currentStage}</span>
        </div>
      )}

      {/* Progress */}
      <div className="progress-container">
        <div className="progress-bar">
          <div
            className={cn(
              "progress-fill",
              job.status === 'completed' && "completed",
              job.status === 'failed' && "failed"
            )}
            style={{ width: `${videoProgress?.percent || job.progress}%` }}
          />
        </div>
        <div className="progress-text">
          {Math.round(videoProgress?.percent || job.progress)}%
        </div>
      </div>

      {/* Video Download Stats - only shown when downloading video */}
      {job.status === 'running' && videoProgress && videoProgress.total_bytes > 0 && (
        <div className="video-stats">
          <span className="video-stat">
            {formatBytes(videoProgress.downloaded_bytes)} / {formatBytes(videoProgress.total_bytes)}
          </span>
          {videoProgress.speed && (
            <span className="video-stat">• {videoProgress.speed}</span>
          )}
          {videoProgress.eta && (
            <span className="video-stat">• ETA {videoProgress.eta}</span>
          )}
        </div>
      )}

      {/* Files */}
      {job.files && job.files.length > 0 && job.status === 'completed' && (() => {
        const cleanFiles = sortFilesByPriority(job.files);
        if (cleanFiles.length === 0) return null;
        return (
          <div className="files-dropdown">
            <div className="flex items-center gap-2 text-xs text-white/40 mb-2">
              <Download size={14} />
              <span>Download Files ({cleanFiles.length})</span>
            </div>
            {cleanFiles.map((file, idx) => (
              <div key={idx} className="file-item">
                {isPreviewable(file) ? (
                  <>
                    <button
                      onClick={() => onPreview(file)}
                      className="file-link file-preview-btn"
                    >
                      <div className="file-name">
                        <FileIcon filename={file} />
                        <span>{getFileLabel(file)}</span>
                      </div>
                      <Eye size={12} className="opacity-40" />
                    </button>
                    <a
                      href={`${API_BASE}/api/jobs/${job.id}/files/${file}`}
                      download
                      className="file-download-btn"
                      title="Download"
                    >
                      <Download size={12} />
                    </a>
                  </>
                ) : (
                  <a
                    href={`${API_BASE}/api/jobs/${job.id}/files/${file}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="file-link"
                  >
                    <div className="file-name">
                      <FileIcon filename={file} />
                      <span>{getFileLabel(file)}</span>
                    </div>
                    <ExternalLink size={12} className="opacity-40" />
                  </a>
                )}
              </div>
            ))}
          </div>
        );
      })()}

      {/* Delete button for non-running jobs */}
      {job.status !== 'running' && (
        <button
          onClick={onDelete}
          className="btn-icon mt-3 ml-auto block text-white/20 hover:text-red-500"
        >
          <Trash2 size={14} />
        </button>
      )}
    </div>
  );
}

function FileIcon({ filename }) {
  const ext = filename.split('.').pop().toLowerCase();

  if (['mp4', 'mkv', 'webm', 'mov', 'avi'].includes(ext)) {
    return <Video size={14} className="text-purple-400" />;
  }
  if (['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(ext)) {
    return <ImageIcon size={14} className="text-cyan-400" />;
  }
  if (['json'].includes(ext)) {
    return <Layers size={14} className="text-amber-400" />;
  }
  if (['txt', 'md'].includes(ext)) {
    return <Sparkles size={14} className="text-pink-400" />;
  }
  if (['vtt', 'srt'].includes(ext)) {
    return <Subtitles size={14} className="text-green-400" />;
  }
  return <FileText size={14} className="text-white/40" />;
}

function getFileLabel(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const name = filename.toLowerCase();

  // Check if it's a summary file
  if (name.includes('summary') || name.includes('_summary')) {
    return 'AI Summary';
  }

  if (['mp4', 'mkv', 'webm'].includes(ext)) return 'Video (MP4)';
  if (['json'].includes(ext)) return 'Metadata (JSON)';
  if (['txt'].includes(ext)) return 'Text Transcript';
  if (['md'].includes(ext)) return 'AI Summary';
  if (['jpg', 'png', 'webp'].includes(ext)) return 'Thumbnail';
  if (['vtt', 'srt'].includes(ext)) return 'Subtitles';
  return filename;
}

// Filter out temporary/incomplete download files
function filterTempFiles(files) {
  const tempExtensions = ['part', 'ytdl', 'temp', 'tmp', 'downloading'];
  const tempPatterns = ['.part-Frag', '.part.', '-Frag'];

  return files.filter(file => {
    const lower = file.toLowerCase();

    // Check for temp extensions
    const ext = lower.split('.').pop();
    if (tempExtensions.includes(ext)) return false;

    // Check for temp patterns in filename
    for (const pattern of tempPatterns) {
      if (lower.includes(pattern.toLowerCase())) return false;
    }

    return true;
  });
}

// Sort files to show summary first, then by type
function sortFilesByPriority(files) {
  // First filter out temp files
  const cleanFiles = filterTempFiles(files);

  const priority = {
    'md': 1,      // Summary first
    'txt': 2,     // Text transcript
    'json': 3,    // Metadata
    'mp4': 4,     // Video
    'webm': 4,
    'mkv': 4,
    'mov': 4,
    'avi': 4,
    'jpg': 5,     // Thumbnail
    'png': 5,
    'webp': 5,
    'jpeg': 5,
    'vtt': 6,     // Subtitles
    'srt': 6,
  };

  return cleanFiles.sort((a, b) => {
    const extA = a.split('.').pop().toLowerCase();
    const extB = b.split('.').pop().toLowerCase();
    const prioA = priority[extA] || 10;
    const prioB = priority[extB] || 10;
    return prioA - prioB;
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   FILE PREVIEW MODAL
   ═══════════════════════════════════════════════════════════════════════════ */

function FilePreviewModal({ isOpen, onClose, content, filename, downloadUrl, loading, fileType }) {
  if (!isOpen) return null;

  // Format JSON content
  const formatContent = () => {
    if (fileType === 'json' && content) {
      try {
        return JSON.stringify(JSON.parse(content), null, 2);
      } catch {
        return content;
      }
    }
    return content;
  };

  // Get file type label
  const getTypeLabel = () => {
    const ext = filename.split('.').pop().toLowerCase();
    if (filename.includes('summary')) return 'AI Summary';
    if (ext === 'md') return 'Markdown';
    if (ext === 'json') return 'JSON';
    if (ext === 'txt') return 'Text';
    if (ext === 'vtt' || ext === 'srt') return 'Subtitles';
    return ext.toUpperCase();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">
            <FileText size={18} className="text-purple-400" />
            <span className="modal-filename">{filename}</span>
            <span className="modal-type-badge">{getTypeLabel()}</span>
          </div>
          <button onClick={onClose} className="modal-close">
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="modal-content">
          {loading ? (
            <div className="modal-loading">
              <Loader2 size={32} className="animate-spin text-purple-400" />
              <span>Loading content...</span>
            </div>
          ) : (
            <pre className={cn(
              "modal-text",
              fileType === 'markdown' && "modal-markdown",
              fileType === 'json' && "modal-json"
            )}>
              {formatContent()}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <a
            href={downloadUrl}
            download
            className="modal-download-btn"
          >
            <Download size={16} />
            <span>Download File</span>
          </a>
          <button onClick={onClose} className="modal-close-btn">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
