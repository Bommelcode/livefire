/**
 * Companion presets — kant-en-klare button-layouts die de operator
 * van het Companion-paneel naar een Stream Deck-pagina kan slepen.
 *
 * Vier categorieën:
 *  - Transport (GO, Stop All, Next, Prev)
 *  - Status display (remaining-time, active-count)
 *  - Quick-fire 1..16 (toetst /livefire/fire/N) — een 4×4 of 8×2 raster
 *    dat operator met cue-numbers in liveFire matcht.
 *
 * Stream Deck-friendly kleuren: GO groen, Stop rood, info-tegels donker
 * met witte tekst.
 */
import {
  combineRgb,
  type CompanionPresetDefinitions,
} from '@companion-module/base'

const COLORS = {
  go: { bg: combineRgb(60, 160, 60), fg: combineRgb(255, 255, 255) },
  stop: { bg: combineRgb(200, 60, 60), fg: combineRgb(255, 255, 255) },
  nav: { bg: combineRgb(60, 60, 60), fg: combineRgb(255, 255, 255) },
  info: { bg: combineRgb(35, 35, 35), fg: combineRgb(225, 225, 225) },
  fire: { bg: combineRgb(60, 162, 230), fg: combineRgb(255, 255, 255) },
  fireRunning: { bg: combineRgb(60, 160, 60), fg: combineRgb(255, 255, 255) },
}

export function buildPresets(): CompanionPresetDefinitions {
  const presets: CompanionPresetDefinitions = {}

  presets['go'] = {
    type: 'button',
    category: 'Transport',
    name: 'GO',
    style: {
      text: 'GO',
      size: '24',
      bgcolor: COLORS.go.bg,
      color: COLORS.go.fg,
    },
    steps: [
      {
        down: [{ actionId: 'go', options: {} }],
        up: [],
      },
    ],
    feedbacks: [],
  }

  presets['stop_all'] = {
    type: 'button',
    category: 'Transport',
    name: 'Stop All',
    style: {
      text: 'STOP\\nALL',
      size: '14',
      bgcolor: COLORS.stop.bg,
      color: COLORS.stop.fg,
    },
    steps: [
      {
        down: [{ actionId: 'stop_all', options: {} }],
        up: [],
      },
    ],
    feedbacks: [],
  }

  presets['playhead_next'] = {
    type: 'button',
    category: 'Transport',
    name: 'Playhead next',
    style: {
      text: 'NEXT\\n▼',
      size: '14',
      bgcolor: COLORS.nav.bg,
      color: COLORS.nav.fg,
    },
    steps: [
      {
        down: [{ actionId: 'playhead_next', options: {} }],
        up: [],
      },
    ],
    feedbacks: [],
  }

  presets['playhead_prev'] = {
    type: 'button',
    category: 'Transport',
    name: 'Playhead prev',
    style: {
      text: 'PREV\\n▲',
      size: '14',
      bgcolor: COLORS.nav.bg,
      color: COLORS.nav.fg,
    },
    steps: [
      {
        down: [{ actionId: 'playhead_prev', options: {} }],
        up: [],
      },
    ],
    feedbacks: [],
  }

  presets['remaining'] = {
    type: 'button',
    category: 'Status',
    name: 'Remaining time',
    style: {
      text: '$(livefire:remaining_formatted)',
      size: '18',
      bgcolor: COLORS.info.bg,
      color: COLORS.info.fg,
    },
    steps: [{ down: [], up: [] }],
    feedbacks: [
      {
        feedbackId: 'countdown_active',
        options: {},
        style: {
          bgcolor: combineRgb(60, 60, 30),
          color: combineRgb(220, 130, 30),
        },
      },
    ],
  }

  presets['active_count'] = {
    type: 'button',
    category: 'Status',
    name: 'Active cue count',
    style: {
      text: 'Active\\n$(livefire:active)',
      size: '14',
      bgcolor: COLORS.info.bg,
      color: COLORS.info.fg,
    },
    steps: [{ down: [], up: [] }],
    feedbacks: [
      {
        feedbackId: 'has_active',
        options: {},
        style: {
          bgcolor: combineRgb(40, 100, 140),
          color: combineRgb(255, 255, 255),
        },
      },
    ],
  }

  presets['playhead_label'] = {
    type: 'button',
    category: 'Status',
    name: 'Playhead label',
    style: {
      text: '►$(livefire:playhead)\\n$(livefire:playhead_name)',
      size: '14',
      bgcolor: COLORS.info.bg,
      color: COLORS.info.fg,
    },
    steps: [{ down: [], up: [] }],
    feedbacks: [],
  }

  // Quick-fire 1..16 — Stream Deck XL fits these on one page; smaller
  // decks will paginate. Buttons light up green when their cue is
  // running, blue otherwise.
  for (let n = 1; n <= 16; n++) {
    presets[`fire_${n}`] = {
      type: 'button',
      category: 'Fire by number',
      name: `Fire cue ${n}`,
      style: {
        text: `${n}\\n$(livefire:cue_${n}_name)`,
        size: '14',
        bgcolor: COLORS.fire.bg,
        color: COLORS.fire.fg,
      },
      steps: [
        {
          down: [
            {
              actionId: 'fire_by_number',
              options: { cue_number: String(n) },
            },
          ],
          up: [],
        },
      ],
      feedbacks: [
        {
          feedbackId: 'cue_state',
          options: { cue_number: String(n), state: 'running' },
          style: {
            bgcolor: COLORS.fireRunning.bg,
            color: COLORS.fireRunning.fg,
          },
        },
      ],
    }
  }

  return presets
}
