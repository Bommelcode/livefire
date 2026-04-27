/**
 * liveFire Companion module — main entry.
 *
 * Connects over OSC to a running liveFire app (host:port = liveFire's
 * OSC-input + a separate UDP listener for liveFire's feedback push).
 *
 * Architecture:
 *   - Outgoing commands → liveFire's OSC-input port (default 53000)
 *   - Incoming feedback ← liveFire's feedback push to a port we listen on
 *
 * The user configures both ports in the module's connection settings.
 */
import {
  InstanceBase,
  InstanceStatus,
  Regex,
  runEntrypoint,
  SomeCompanionConfigField,
} from '@companion-module/base'

import { LivefireOsc } from './osc'
import { buildActions } from './actions'
import { buildFeedbacks } from './feedbacks'
import { buildVariables, applySnapshotToVariables } from './variables'
import { buildPresets } from './presets'

export interface LivefireConfig {
  /** liveFire host (where the app is running). */
  host: string
  /** liveFire OSC-input port — that's where we send commands. */
  cmdPort: number
  /** Local UDP port we bind to receive liveFire's feedback push.
   *  Must match the "Port" liveFire sends feedback to in its
   *  Preferences → Companion section. Default 12321. */
  feedbackPort: number
}

class LivefireInstance extends InstanceBase<LivefireConfig> {
  public osc: LivefireOsc | undefined

  /** Last-seen transport snapshot — drives Companion variables. */
  public state = {
    playhead: 0,
    playheadTotal: 0,
    playheadName: '',
    active: 0,
    remaining: 0,
    remainingLabel: '',
    countdownActive: false,
    /** Map cue_number → state ("idle"/"running"/"finished"). */
    cueStates: new Map<string, string>(),
    /** Map cue_number → name. */
    cueNames: new Map<string, string>(),
    /** Map cue_number → cue type (Audio / Video / ...). */
    cueTypes: new Map<string, string>(),
    cueCount: 0,
  }

  async init(config: LivefireConfig): Promise<void> {
    this.updateStatus(InstanceStatus.Connecting)
    this.setActionDefinitions(buildActions(this))
    this.setFeedbackDefinitions(buildFeedbacks(this))
    this.setVariableDefinitions(buildVariables())
    this.setPresetDefinitions(buildPresets())
    await this.configUpdated(config)
  }

  async destroy(): Promise<void> {
    this.osc?.shutdown()
    this.osc = undefined
  }

  async configUpdated(config: LivefireConfig): Promise<void> {
    this.osc?.shutdown()
    this.osc = new LivefireOsc({
      host: config.host || '127.0.0.1',
      cmdPort: Number(config.cmdPort) || 53000,
      feedbackPort: Number(config.feedbackPort) || 12321,
      onMessage: (addr, args) => this.handleIncoming(addr, args),
      onStatus: (status, msg) => this.updateStatus(status, msg),
    })
    try {
      await this.osc.start()
      this.updateStatus(InstanceStatus.Ok)
    } catch (e) {
      this.updateStatus(InstanceStatus.ConnectionFailure, String(e))
    }
  }

  getConfigFields(): SomeCompanionConfigField[] {
    return [
      {
        type: 'static-text',
        id: 'info',
        width: 12,
        label: 'About',
        value:
          'Connect to a running liveFire instance. Enable ' +
          '"Push feedback to Companion" in liveFire ' +
          'Preferences → Companion and match the feedback port below.',
      },
      {
        type: 'textinput',
        id: 'host',
        label: 'liveFire host',
        width: 6,
        default: '127.0.0.1',
        regex: Regex.HOSTNAME,
      },
      {
        type: 'number',
        id: 'cmdPort',
        label: 'liveFire OSC-input port (commands)',
        tooltip: "Match liveFire's Preferences → OSC input → UDP port",
        width: 3,
        default: 53000,
        min: 1,
        max: 65535,
      },
      {
        type: 'number',
        id: 'feedbackPort',
        label: 'Feedback port (we listen here)',
        tooltip:
          "Match liveFire's Preferences → Companion → Port. " +
          'liveFire pushes its state to this port.',
        width: 3,
        default: 12321,
        min: 1,
        max: 65535,
      },
    ]
  }

  // ---- incoming feedback handling -----------------------------------

  private handleIncoming(address: string, args: any[]): void {
    if (address === '/livefire/playhead') {
      this.state.playhead = Number(args[0] ?? 0)
      this.state.playheadTotal = Number(args[1] ?? 0)
      this.state.playheadName = String(args[2] ?? '')
    } else if (address === '/livefire/active') {
      this.state.active = Number(args[0] ?? 0)
    } else if (address === '/livefire/remaining') {
      this.state.remaining = Number(args[0] ?? 0)
    } else if (address === '/livefire/remaining/label') {
      this.state.remainingLabel = String(args[0] ?? '')
    } else if (address === '/livefire/countdown_active') {
      this.state.countdownActive = Number(args[0] ?? 0) !== 0
    } else if (address === '/livefire/cuecount') {
      this.state.cueCount = Number(args[0] ?? 0)
    } else if (address.startsWith('/livefire/cue/')) {
      // /livefire/cue/<number>/state | /name | /type
      const rest = address.substring('/livefire/cue/'.length)
      const slash = rest.indexOf('/')
      if (slash <= 0) return
      const cueNumber = rest.substring(0, slash)
      const field = rest.substring(slash + 1)
      const value = String(args[0] ?? '')
      if (field === 'state') {
        this.state.cueStates.set(cueNumber, value)
        this.checkFeedbacks('cue_state')
      } else if (field === 'name') {
        this.state.cueNames.set(cueNumber, value)
      } else if (field === 'type') {
        this.state.cueTypes.set(cueNumber, value)
      }
    } else {
      return
    }
    applySnapshotToVariables(this)
    // Refresh feedbacks that depend on transport-level state.
    this.checkFeedbacks('countdown_active', 'has_active', 'playhead_at')
  }
}

runEntrypoint(LivefireInstance, [])
