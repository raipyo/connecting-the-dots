'use client';

interface ResearchStatusProps {
  status: 'idle' | 'processing' | 'completed' | 'error';
  message?: string;
}

export function ResearchStatus({ status, message }: ResearchStatusProps) {
  if (status === 'idle') return null;

  const statusConfig = {
    processing: {
      icon: '⏳',
      color: 'text-blue-600',
      bg: 'bg-blue-50',
      text: 'Processing your research...',
    },
    completed: {
      icon: '✅',
      color: 'text-green-600',
      bg: 'bg-green-50',
      text: 'Research completed!',
    },
    error: {
      icon: '❌',
      color: 'text-red-600',
      bg: 'bg-red-50',
      text: message || 'An error occurred',
    },
  };

  const config = statusConfig[status];

  return (
    <div className={`${config.bg} p-4 rounded-lg flex items-center gap-3`}>
      <span className={`text-2xl ${config.color}`}>{config.icon}</span>
      <span className={config.color}>{config.text}</span>
    </div>
  );
}