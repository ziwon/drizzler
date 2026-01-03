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
  Code
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
    rate: 1.0,
    concurrency: 5,
    llm_model: 'qwen2.5:3b'
  });
  const [jobs, setJobs] = useState([]);
  const [submitting, setSubmitting] = useState(false);

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
                  icon={<Code size={18} />}
                  label="Custom Script"
                  active={false}
                  onClick={() => { }}
                  disabled
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
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COMPONENTS
   ═══════════════════════════════════════════════════════════════════════════ */

function ToggleOption({ icon, label, active, onClick, disabled }) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      className={cn(
        "option-toggle",
        active && "active",
        disabled && "opacity-40 cursor-not-allowed"
      )}
    >
      <div className="option-info">
        <span className="option-icon">{icon}</span>
        <span className="option-label">{label}</span>
      </div>
      <div className="toggle-switch" />
    </div>
  );
}

function JobCard({ job, onDelete }) {
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

  // Mock stats for display (in real app, these would come from API)
  const estimatedTime = job.status === 'running' ? '2m 30s' : '--';
  const speed = job.status === 'running' ? '12.5 MB/s' : '--';
  const quality = '1080p';

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

      {/* Progress */}
      <div className="progress-container">
        <div className="progress-bar">
          <div
            className={cn(
              "progress-fill",
              job.status === 'completed' && "completed",
              job.status === 'failed' && "failed"
            )}
            style={{ width: `${job.progress}%` }}
          />
        </div>
        <div className="progress-text">{Math.round(job.progress)}%</div>
      </div>

      {/* Stats */}
      {job.status === 'running' && (
        <div className="job-stats">
          <div className="job-stat">
            <div className="label">Estimated Time</div>
            <div className="value">{estimatedTime}</div>
          </div>
          <div className="job-stat">
            <div className="label">Speed</div>
            <div className="value">{speed}</div>
          </div>
          <div className="job-stat">
            <div className="label">Quality</div>
            <div className="value">{quality}</div>
          </div>
        </div>
      )}

      {/* Files */}
      {job.files && job.files.length > 0 && job.status === 'completed' && (
        <div className="files-dropdown">
          <div className="flex items-center gap-2 text-xs text-white/40 mb-2">
            <Download size={14} />
            <span>Download Files</span>
          </div>
          {job.files.slice(0, 3).map((file, idx) => (
            <a
              key={idx}
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
          ))}
        </div>
      )}

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
  return <FileText size={14} className="text-white/40" />;
}

function getFileLabel(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  if (['mp4', 'mkv', 'webm'].includes(ext)) return 'Video (MP4)';
  if (['json'].includes(ext)) return 'Metadata (JSON)';
  if (['txt'].includes(ext)) return 'Summary (TXT)';
  if (['jpg', 'png', 'webp'].includes(ext)) return 'Thumbnail';
  return filename;
}

export default App;
