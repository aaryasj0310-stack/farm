import React, { useState } from 'react';
import { Download, FileText, FileCode, FileSpreadsheet } from 'lucide-react';
import { getExportUrl } from '../api/client';

interface Props {
  jobId: string;
}

export const ExportMenu: React.FC<Props> = ({ jobId }) => {
  const [isOpen, setIsOpen] = useState(false);

  const formats = [
    { id: 'json', label: 'Complete JSON Data (.json)', icon: FileCode },
    { id: 'pdf', label: 'PDF Document (.pdf)', icon: FileText },
    { id: 'md', label: 'Markdown Report (.md)', icon: FileText },
    { id: 'txt', label: 'Plain Text Transcript (.txt)', icon: FileText },
    { id: 'html', label: 'Standalone Webpage (.html)', icon: FileSpreadsheet },
  ];

  return (
    <div style={{ position: 'relative' }}>
      <button className="btn btn-outline" onClick={() => setIsOpen(!isOpen)}>
        <Download size={16} />
        <span>Export Analysis</span>
      </button>

      {isOpen && (
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: '110%',
            width: '240px',
            background: 'white',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)',
            zIndex: 50,
            padding: '0.5rem 0',
          }}
        >
          {formats.map((fmt) => {
            const Icon = fmt.icon;
            return (
              <a
                key={fmt.id}
                href={getExportUrl(jobId, fmt.id)}
                download
                onClick={() => setIsOpen(false)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.5rem 1rem',
                  fontSize: '0.8rem',
                  color: 'var(--text-main)',
                  textDecoration: 'none',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f1f5f9')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <Icon size={16} color="var(--primary)" />
                <span>{fmt.label}</span>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
};
