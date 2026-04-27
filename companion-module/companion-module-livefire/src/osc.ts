/**
 * OSC client + server. Outgoing UDPPort sends commands to liveFire's
 * OSC-input. Incoming UDPPort listens for liveFire's feedback push and
 * dispatches to a callback.
 */
import { InstanceStatus } from '@companion-module/base'
import * as osc from 'osc'

export interface LivefireOscOptions {
  host: string
  cmdPort: number
  feedbackPort: number
  onMessage: (address: string, args: any[]) => void
  onStatus: (status: InstanceStatus, message?: string) => void
}

export class LivefireOsc {
  private opts: LivefireOscOptions
  private outgoing: osc.UDPPort | undefined
  private incoming: osc.UDPPort | undefined

  constructor(opts: LivefireOscOptions) {
    this.opts = opts
  }

  async start(): Promise<void> {
    // Outgoing port — we don't need to receive on it, but the osc lib
    // requires an open port to send. Bind to localhost ephemeral.
    this.outgoing = new osc.UDPPort({
      localAddress: '0.0.0.0',
      localPort: 0,
      remoteAddress: this.opts.host,
      remotePort: this.opts.cmdPort,
      metadata: false,
    })
    this.outgoing.on('error', (err) => {
      this.opts.onStatus(
        InstanceStatus.UnknownWarning,
        `OSC out error: ${err}`,
      )
    })
    this.outgoing.open()

    // Incoming port — bound to feedbackPort, listens for liveFire pushes.
    this.incoming = new osc.UDPPort({
      localAddress: '0.0.0.0',
      localPort: this.opts.feedbackPort,
      metadata: false,
    })
    this.incoming.on('message', (msg) => {
      const args = (msg.args || []).map((a: any) => {
        // osc lib wraps args as { type, value } when metadata=true; we
        // turned that off so args are raw values, but be defensive.
        return typeof a === 'object' && a !== null && 'value' in a
          ? a.value
          : a
      })
      this.opts.onMessage(msg.address, args)
    })
    this.incoming.on('error', (err) => {
      this.opts.onStatus(
        InstanceStatus.UnknownWarning,
        `OSC in error: ${err}`,
      )
    })
    this.incoming.open()
  }

  send(address: string, args: any[] = []): void {
    if (!this.outgoing) return
    try {
      this.outgoing.send({ address, args })
    } catch (e) {
      this.opts.onStatus(
        InstanceStatus.UnknownWarning,
        `OSC send failed: ${e}`,
      )
    }
  }

  shutdown(): void {
    try {
      this.outgoing?.close()
    } catch {
      /* ignore */
    }
    try {
      this.incoming?.close()
    } catch {
      /* ignore */
    }
    this.outgoing = undefined
    this.incoming = undefined
  }
}
