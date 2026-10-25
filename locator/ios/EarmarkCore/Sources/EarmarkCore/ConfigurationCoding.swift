import Foundation

private struct ModeValues<T: Codable>: Codable { var hand: T; var pocket: T }
private struct PriorValue: Codable { var mean_m: Double; var sigma_m: Double }
private struct KalmanValues: Codable { var accel_sigma_mps2: Double; var meas_sigma_ok_m: Double; var meas_sigma_degraded_m: Double }
private struct SpeechValues: Codable { var sample_rate: Int; var chunk_ms: Double }
private struct HubValues: Codable { var url: String; var token: String; var auth_mode: HubAuth }

extension LocatorConfig {
    private enum Keys: String, CodingKey {
        case version, fs, chirp, beacons, mode, gate_ms, lookback_ms, snr_min, snr_acquire, resid_max_ms, resid_ok_ms
        case height_prior, ear_offset_m, kalman, lost_timeout_s, air_temperature_c, mic_audio, hub
    }
    public init(from decoder: Decoder) throws {
        self.init()
        let c = try decoder.container(keyedBy: Keys.self)
        guard try c.decode(Int.self, forKey: .version) == 1 else { throw LocatorError.invalid("Unsupported settings version") }
        fs = try c.decode(Double.self, forKey: .fs)
        chirp = try c.decode(ChirpConfig.self, forKey: .chirp)
        beacons = try c.decodeIfPresent([Beacon].self, forKey: .beacons) ?? Beacon.defaults
        mode = try c.decodeIfPresent(CarryMode.self, forKey: .mode) ?? .hand
        gate_ms = try c.decode(Double.self, forKey: .gate_ms)
        lookback_ms = try c.decode(Double.self, forKey: .lookback_ms)
        snr_min = try c.decode(Double.self, forKey: .snr_min)
        snr_acquire = try c.decode(Double.self, forKey: .snr_acquire)
        resid_max_ms = try c.decode(Double.self, forKey: .resid_max_ms)
        resid_ok_ms = try c.decode(Double.self, forKey: .resid_ok_ms)
        let priors = try c.decode(ModeValues<PriorValue>.self, forKey: .height_prior)
        height_hand = HeightPrior(mean: priors.hand.mean_m, sigma: priors.hand.sigma_m)
        height_pocket = HeightPrior(mean: priors.pocket.mean_m, sigma: priors.pocket.sigma_m)
        let offsets = try c.decode(ModeValues<Vector3>.self, forKey: .ear_offset_m)
        ear_offset_hand = offsets.hand; ear_offset_pocket = offsets.pocket
        let kalman = try c.decode(KalmanValues.self, forKey: .kalman)
        kalman_acceleration_sigma = kalman.accel_sigma_mps2
        kalman_measurement_sigma_ok = kalman.meas_sigma_ok_m
        kalman_measurement_sigma_degraded = kalman.meas_sigma_degraded_m
        lost_timeout = try c.decode(Double.self, forKey: .lost_timeout_s)
        air_temperature = try c.decode(Double.self, forKey: .air_temperature_c)
        let speech = try c.decode(SpeechValues.self, forKey: .mic_audio)
        mic_audio_sample_rate = speech.sample_rate; mic_audio_chunk_ms = speech.chunk_ms
        let hub = try c.decode(HubValues.self, forKey: .hub)
        hub_url = hub.url; hub_token = hub.token; hub_auth_mode = hub.auth_mode
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: Keys.self)
        try c.encode(1, forKey: .version); try c.encode(fs, forKey: .fs); try c.encode(chirp, forKey: .chirp)
        try c.encode(beacons, forKey: .beacons); try c.encode(mode, forKey: .mode)
        try c.encode(gate_ms, forKey: .gate_ms); try c.encode(lookback_ms, forKey: .lookback_ms)
        try c.encode(snr_min, forKey: .snr_min); try c.encode(snr_acquire, forKey: .snr_acquire)
        try c.encode(resid_max_ms, forKey: .resid_max_ms); try c.encode(resid_ok_ms, forKey: .resid_ok_ms)
        try c.encode(ModeValues(hand: PriorValue(mean_m: height_hand.mean, sigma_m: height_hand.sigma),
                                pocket: PriorValue(mean_m: height_pocket.mean, sigma_m: height_pocket.sigma)), forKey: .height_prior)
        try c.encode(ModeValues(hand: ear_offset_hand, pocket: ear_offset_pocket), forKey: .ear_offset_m)
        try c.encode(KalmanValues(accel_sigma_mps2: kalman_acceleration_sigma, meas_sigma_ok_m: kalman_measurement_sigma_ok,
                                  meas_sigma_degraded_m: kalman_measurement_sigma_degraded), forKey: .kalman)
        try c.encode(lost_timeout, forKey: .lost_timeout_s); try c.encode(air_temperature, forKey: .air_temperature_c)
        try c.encode(SpeechValues(sample_rate: mic_audio_sample_rate, chunk_ms: mic_audio_chunk_ms), forKey: .mic_audio)
        try c.encode(HubValues(url: hub_url, token: hub_token, auth_mode: hub_auth_mode), forKey: .hub)
    }
}
