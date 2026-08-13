# TW3 Custom Player Voice BR — AI Female Voice Pipeline

[Português](README.md) | **English**

Pipeline and documentation for a Brazilian Portuguese synthetic female voice
for lines normally associated with Geralt when the
player uses a female character through the **Custom Player Characters** mod in
*The Witcher 3: Wild Hunt* 4.04 for PC.

This edition changes self-references to **Geralda**, uses nine delivery profiles,
and includes Portuguese, pronunciation, duration, acoustic-quality and voice-
identity audits.

The repository contains code, tests, examples and documentation only. The
installable package is distributed as a GitHub Release asset and is never
committed to Git history.

## Release status

- publication candidate: `1.0.0-rc.1`;
- corpus: 19,376 IDs;
- synthetic lines: 19,359;
- entries preserving official audio: 17;
- delivery profiles: 9;
- validated package size: 1,200,855,572 bytes;
- candidate SHA-256: `F35F986964F18111E2D0DB1CDDE0ED5766B1E4BB14755E47E1A040F67495334E`.

## AI and voice disclosure

A synthetic voice created with **ElevenLabs Voice Design** during a paid
subscription was used as an authorized OmniVoice reference. Its output was
used as an authorized OmniVoice reference. No recording of a *The Witcher 3*
actor was used as the timbre source, and the project does not claim that the
voice belongs to a real person.

The mod must be clearly disclosed as AI-generated. Raw references, `.pt`
prompts, game audio and working datasets are not published. See
[VOICE_ORIGIN.md](VOICE_ORIGIN.md) and [ASSET_LICENSE.md](ASSET_LICENSE.md).

## Compatibility

The installable mod requires *The Witcher 3* 4.04 for PC, Brazilian Portuguese
voice language, and Custom Player Characters. It conflicts with other mods that
replace the same `brpc.w3speech` or Geralt's Brazilian Portuguese lines.

```text
modCustomPlayerVoiceBR_Feminina/
  content/
    brpc.w3speech
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) and the Portuguese
[technical pipeline](docs/PIPELINE.md).

## Tests

```powershell
py -3 -m unittest discover -s tests -v
```

The original source code is MIT-licensed. That license does not cover the game,
CD PROJEKT RED assets, the synthetic voice, generated audio, or the installable
package. This is unofficial fan work and is not approved or endorsed by
CD PROJEKT RED.
