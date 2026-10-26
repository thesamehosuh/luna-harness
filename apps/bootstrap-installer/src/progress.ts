export interface LauncherProgress {
  stage: string
  detail: string
  completed_bytes?: number
  total_bytes?: number | null
  bytes_per_second?: number | null
}

export function progressStep(stage?: string): number {
  if (stage === 'checking' || stage === 'download' || stage === 'verify') {return 0}

  if (stage === 'runtime' || stage === 'dependencies') {return 1}

  if (stage === 'chat-runtime' || stage === 'native-tools' || stage === 'personal-home' || stage === 'ready') {return 2}

  return 3
}

export function formatBytes(bytes: number): string {
  if (bytes < 1_000_000) {return `${Math.max(0, bytes / 1000).toFixed(0)} KB`}

  return `${(bytes / 1_000_000).toFixed(1)} MB`
}
