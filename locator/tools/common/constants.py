"""Shared constants and room physics (LOCATOR_BRIEF.md sections 4.3, 6.1, 8.6)."""

from __future__ import annotations

#: RMT tick used by the firmware for edge quantization: 0.1 us (10 MHz).
TICK_S: float = 1e-7

#: Default air temperature for the speed of sound (brief section 8.6).
DEFAULT_TEMPERATURE_C: float = 22.0


def speed_of_sound(temperature_c: float = DEFAULT_TEMPERATURE_C) -> float:
    """Speed of sound in m/s at ``temperature_c`` (brief section 6.1).

    c = 331.3 + 0.606 * T_celsius
    """
    return 331.3 + 0.606 * float(temperature_c)
