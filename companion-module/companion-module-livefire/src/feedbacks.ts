/**
 * Companion feedbacks — visual states on Stream Deck buttons.
 *
 * `cue_state` lights a button when a specific cue (by number) is in
 * a given state. `countdown_active` lights when the countdown clock
 * is running. `has_active` lights when at least one cue is playing.
 * `playhead_at` lights when the playhead points at a given index.
 */
import {
  combineRgb,
  type CompanionFeedbackDefinitions,
} from '@companion-module/base'

export function buildFeedbacks(self: any): CompanionFeedbackDefinitions {
  return {
    cue_state: {
      type: 'boolean',
      name: 'Cue is in state',
      description: 'Light up when a cue is in the chosen state.',
      defaultStyle: {
        bgcolor: combineRgb(50, 130, 50),
        color: combineRgb(255, 255, 255),
      },
      options: [
        {
          type: 'textinput',
          id: 'cue_number',
          label: 'Cue number',
          default: '1',
          useVariables: true,
        },
        {
          type: 'dropdown',
          id: 'state',
          label: 'State',
          default: 'running',
          choices: [
            { id: 'idle', label: 'idle' },
            { id: 'running', label: 'running' },
            { id: 'finished', label: 'finished' },
          ],
        },
      ],
      callback: async (feedback, ctx) => {
        const cueNumber = String(
          await ctx.parseVariablesInString(String(feedback.options.cue_number ?? '')),
        ).trim()
        const wantState = String(feedback.options.state ?? 'running')
        return self.state.cueStates.get(cueNumber) === wantState
      },
    },
    countdown_active: {
      type: 'boolean',
      name: 'Countdown is active',
      description: 'Light up while a cue with finite duration is counting down.',
      defaultStyle: {
        bgcolor: combineRgb(220, 130, 30),
        color: combineRgb(0, 0, 0),
      },
      options: [],
      callback: () => self.state.countdownActive === true,
    },
    has_active: {
      type: 'boolean',
      name: 'Any cue running',
      description: 'Light up when active cue count > 0.',
      defaultStyle: {
        bgcolor: combineRgb(60, 162, 230),
        color: combineRgb(255, 255, 255),
      },
      options: [],
      callback: () => Number(self.state.active) > 0,
    },
    playhead_at: {
      type: 'boolean',
      name: 'Playhead at index',
      description: 'Light up when the playhead is at the given 0-based index.',
      defaultStyle: {
        bgcolor: combineRgb(60, 162, 230),
        color: combineRgb(255, 255, 255),
      },
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
      callback: (feedback) =>
        Number(self.state.playhead) === Number(feedback.options.index),
    },
  }
}
