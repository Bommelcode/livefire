/**
 * Companion actions — these become Stream Deck button bindings. Each
 * action sends an OSC command to liveFire.
 */
import type { CompanionActionDefinitions } from '@companion-module/base'
import type { default as LivefireInstance } from './index'

export function buildActions(
  self: any /* LivefireInstance — circular import workaround */,
): CompanionActionDefinitions {
  return {
    go: {
      name: 'GO',
      description: 'Fire the cue at the playhead and advance.',
      options: [],
      callback: () => self.osc?.send('/livefire/go'),
    },
    stop_all: {
      name: 'Stop All',
      description: 'Stop all currently running cues (panic).',
      options: [],
      callback: () => self.osc?.send('/livefire/stop_all'),
    },
    playhead_next: {
      name: 'Playhead: next',
      description: 'Move the playhead one cue down.',
      options: [],
      callback: () => self.osc?.send('/livefire/playhead/next'),
    },
    playhead_prev: {
      name: 'Playhead: previous',
      description: 'Move the playhead one cue up.',
      options: [],
      callback: () => self.osc?.send('/livefire/playhead/prev'),
    },
    playhead_goto: {
      name: 'Playhead: go to index',
      description: 'Set the playhead to a specific 0-based index.',
      options: [
        {
          type: 'number',
          id: 'index',
          label: 'Index (0-based)',
          default: 0,
          min: 0,
          max: 9999,
        },
      ],
      callback: async (event) => {
        const idx = Number(event.options.index)
        self.osc?.send('/livefire/playhead/goto', [idx])
      },
    },
    fire_by_number: {
      name: 'Fire cue by number',
      description: "Fire any cue matching this cue_number (the cuelist's 'Nr' column).",
      options: [
        {
          type: 'textinput',
          id: 'cue_number',
          label: 'Cue number',
          default: '1',
          useVariables: true,
        },
      ],
      callback: async (event, ctx) => {
        const num = String(
          await ctx.parseVariablesInString(String(event.options.cue_number ?? '')),
        ).trim()
        if (!num) return
        self.osc?.send(`/livefire/fire/${num}`)
      },
    },
  }
}
