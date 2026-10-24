"""Regression for simulator reflection controls used by pipeline acceptance."""
import numpy as np
from tools.common.config import DEFAULT_BEACONS
from tools.common.constants import speed_of_sound
from tools.sim_beacons import FLOOR_COEFF, WALL_COEFF, _images_for, run_sim


def render(**kwargs):
    return run_sim(duration_s=0.3, tau_s=0.05, clock_error_ppm=0,
                   noise_snr_db=None, buzzer_response=False, body_shadowing=False,
                   **kwargs)


def test_zero_coefficients_remove_echo_energy():
    clean = render(floor_coeff=0, wall_coeff=0)
    reflected = render()
    direct_end = 0.05 + np.linalg.norm(np.array(DEFAULT_BEACONS[0].position)
                                     - [0, 0, 1.25]) / speed_of_sound() + 0.012
    start = int(np.ceil(direct_end * clean.fs)) + 2
    stop = int((direct_end + 0.005) * clean.fs)
    assert np.max(np.abs(clean.signal[start:stop])) == 0
    assert np.sum(reflected.signal[start:stop] ** 2) > 0.01
    assert clean.truth["floor_reflection_coeff"] == 0
    assert clean.truth["wall_reflection_coeff"] == 0


def test_default_coefficients_preserve_original_images_and_waveform():
    images = _images_for(DEFAULT_BEACONS[0], -2.25)
    assert [image.gain for image in images] == [1, 0.5, 0.3]
    assert images[1].position == (-1.5, 1.5, -1.8)
    assert images[2].position == (-1.5, -6.0, 1.8)
    np.testing.assert_array_equal(render().samples_int16,
                                  render(floor_coeff=FLOOR_COEFF,
                                         wall_coeff=WALL_COEFF).samples_int16)


def test_floor_and_wall_coefficients_control_independent_paths():
    clean = render(floor_coeff=0, wall_coeff=0)
    floor = render(floor_coeff=0.5, wall_coeff=0)
    wall = render(floor_coeff=0, wall_coeff=0.3)
    both = render()
    unscaled = lambda result: result.signal / result.truth["master_gain"]
    np.testing.assert_allclose(unscaled(both), unscaled(floor) + unscaled(wall)
                               - unscaled(clean), atol=1e-14)
