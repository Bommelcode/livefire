/**
 * Companion variables — text values exposed for use in button text,
 * triggers, etc. liveFire's snapshot pushes drive these directly.
 */
import type { CompanionVariableDefinition } from '@companion-module/base'

export function buildVariables(): CompanionVariableDefinition[] {
  return [
    { variableId: 'playhead', name: 'Playhead index (0-based)' },
    { variableId: 'playhead_total', name: 'Total cue count' },
    { variableId: 'playhead_name', name: 'Name of the cue at the playhead' },
    { variableId: 'active', name: 'Number of currently running cues' },
    { variableId: 'remaining', name: 'Remaining seconds (raw)' },
    {
      variableId: 'remaining_formatted',
      name: 'Remaining time formatted (m:ss / s.s)',
    },
    {
      variableId: 'remaining_label',
      name: 'Name of the cue driving the countdown',
    },
    { variableId: 'cuecount', name: 'Cuecount in the workspace' },
  ]
}

export function applySnapshotToVariables(self: any): void {
  const remaining = Number(self.state.remaining ?? 0)
  self.setVariableValues({
    playhead: self.state.playhead,
    playhead_total: self.state.playheadTotal,
    playhead_name: self.state.playheadName,
    active: self.state.active,
    remaining: remaining.toFixed(1),
    remaining_formatted: formatRemaining(remaining),
    remaining_label: self.state.remainingLabel,
    cuecount: self.state.cueCount,
  })
}

function formatRemaining(seconds: number): string {
  // liveFire pushes negative seconds for count-up (infinite-loop audio).
  // Use a leading '+' so operators can tell it apart on screen.
  const sign = seconds < 0 ? '+' : ''
  const s = Math.abs(seconds)
  if (s < 60) return `${sign}${s.toFixed(1)}s`
  const mins = Math.floor(s / 60)
  const secs = Math.floor(s % 60)
  return `${sign}${mins}:${secs.toString().padStart(2, '0')}`
}
