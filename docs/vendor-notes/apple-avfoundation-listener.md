# Apple APIs used for the moving listener (UWB walking guidance)

Checked against developer.apple.com on 2026-10-24 for `mac/` (PRD section 10). Not yet compiled: the Mac team builds and verifies.

| API | Declaration (as documented) | Used in |
|---|---|---|
| [`AVAudioEnvironmentNode.listenerPosition`](https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode/listenerposition) | `var listenerPosition: AVAudio3DPoint { get set }`, meters | `AVAudioCueRenderer.applyPoseLocked` |
| [`AVAudioEnvironmentDistanceAttenuationParameters`](https://developer.apple.com/documentation/avfaudio/avaudioenvironmentdistanceattenuationparameters) | `distanceAttenuationModel`, `referenceDistance: Float`, `maximumDistance: Float`, `rolloffFactor: Float`; a node provides the instance (class, mutated in place) | `AVAudioCueRenderer.applyAttenuationLocked` |
| [`AVAudioEnvironmentDistanceAttenuationModel`](https://developer.apple.com/documentation/avfaudio/avaudioenvironmentdistanceattenuationmodel) | `.exponential`, `.inverse`, `.linear` | `.inverse` |
| [`PHASEObject.transform`](https://developer.apple.com/documentation/phase/phaseobject/transform) | `var transform: simd_float4x4 { get set }`; position in `columns.3`; right-handed, +Y up, -Z forward | `PHASECueRenderer.listenerTransform(yawDeg:pitchDeg:position:)` |
| [`PHASESpatialMixerDefinition.distanceModelParameters`](https://developer.apple.com/documentation/phase/phasespatialmixerdefinition) | `var distanceModelParameters: PHASEDistanceModelParameters?` | set at build time |
| [`PHASEGeometricSpreadingDistanceModelParameters`](https://developer.apple.com/documentation/phase/phasegeometricspreadingdistancemodelparameters) | `init()`, `var rolloffFactor: Double` (1.0 = -6 dB per doubling) | `PHASECueRenderer.distanceModel` |
| [`PHASEDistanceModelFadeOutParameters`](https://developer.apple.com/documentation/phase/phasedistancemodelfadeoutparameters) | `init(cullDistance: Double)`: stops sounds beyond it | not used (would silence, not clamp) |
| [`TextField.init(_:value:format:prompt:)`](https://developer.apple.com/documentation/swiftui/textfield/init(_:value:format:prompt:)-3fh51) | `F: ParseableFormatStyle, F.FormatOutput == String`; macOS 12+ | `CalibrationView` cm fields |
| `AccessibilityNotification.Announcement(_:).post()` | SwiftUI, macOS 14+ ([WWDC23 session 10036](https://developer.apple.com/videos/play/wwdc2023/10036/)); the reference page did not load | `CalibrationModel.say` |

Not documented, so check by ear on the Mac:
- The `.inverse` formula. The code assumes the OpenAL-style `ref / (ref + rolloff * (d - ref))`, with no attenuation under `referenceDistance`.
- PHASE geometric spreading has no reference distance. Targets nearer than PHASE's internal reference might get louder. Set Rolloff to 0 in Settings to disable it.
