# Companion module workspace

This folder houses the **Bitfocus Companion module** for liveFire. It's a standalone TypeScript / Node.js project — distinct from the Python app — so it can be published to the [Companion module index](https://github.com/bitfocus/companion-module-requests) on its own release schedule.

See [`companion-module-livefire/README.md`](companion-module-livefire/README.md) for setup, OSC spec, and development workflow.

## Why a separate project

Companion modules run inside Companion's Node host, not inside the liveFire process. They speak OSC to the running liveFire instance. The two are coupled only by the contract documented in `companion-module-livefire/README.md` — that contract is the same OSC surface a manual Companion config could target without this module.
