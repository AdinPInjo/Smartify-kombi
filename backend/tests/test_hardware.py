import pytest

from smartify.hardware import HardwareError, build_hardware, nmea
from smartify.hardware.mock import MockRelayDriver
from smartify.hardware.pi.ads1115 import config_word, raw_to_voltage

# --- NMEA ------------------------------------------------------------------

RMC = "$GPRMC,123519,A,4413.614,N,01739.948,E,022.4,084.4,230394,003.1,W*6E"
GGA = "$GPGGA,123519,4413.614,N,01739.948,E,1,08,0.9,545.4,M,46.9,M,,*4F"


def _with_checksum(body: str) -> str:
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def test_rmc_is_parsed():
    sentence = nmea.parse(_with_checksum(RMC[1:].split("*")[0]))
    assert isinstance(sentence, nmea.RmcSentence)
    assert sentence.valid
    assert sentence.lat == pytest.approx(44.226900, abs=1e-5)
    assert sentence.lon == pytest.approx(17.665800, abs=1e-5)
    assert sentence.speed_kmh == pytest.approx(22.4 * 1.852)
    assert sentence.course == pytest.approx(84.4)


def test_gga_is_parsed_with_any_talker():
    body = GGA[1:].split("*")[0].replace("GPGGA", "GNGGA")
    sentence = nmea.parse(_with_checksum(body))
    assert isinstance(sentence, nmea.GgaSentence)
    assert sentence.has_fix
    assert sentence.satellites == 8
    assert sentence.altitude_m == pytest.approx(545.4)


def test_bad_checksum_and_garbage_are_ignored():
    body = RMC[1:].split("*")[0]
    assert nmea.parse(f"${body}*00") is None
    assert nmea.parse("not nmea") is None
    assert nmea.parse("$GPGSV,1,1,00*79") is None


@pytest.mark.parametrize(
    ("coord", "hemi", "expected"),
    [
        ("4413.614", "N", 44.2269),
        ("01739.948", "W", -17.6658),
        ("", "N", None),
        ("4413", "N", None),
    ],
)
def test_to_decimal(coord, hemi, expected):
    result = nmea.to_decimal(coord, hemi)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=1e-4)


# --- ADS1115 register math (no I2C needed) ---------------------------------


def test_ads1115_config_word_matches_datasheet():
    # Channel 0, ±4.096 V, 128 SPS, single shot, comparator off
    assert config_word(0, 4.096, 128) == 0xC383
    assert config_word(1, 4.096, 128) == 0xD383


def test_ads1115_rejects_invalid_values():
    with pytest.raises(ValueError):
        config_word(4, 4.096, 128)
    with pytest.raises(ValueError):
        config_word(0, 3.3, 128)


def test_ads1115_raw_to_voltage():
    assert raw_to_voltage(0x40, 0x00, 4.096) == pytest.approx(2.048)
    assert raw_to_voltage(0xFF, 0xFF, 4.096) == pytest.approx(-0.000125)


# --- Mock hardware -----------------------------------------------------------


def test_mock_relay_respects_active_low():
    relays = MockRelayDriver()
    relays.set_state(25, on=True, active_low=True)
    assert relays.pin_levels[25] is False
    assert relays.is_on(25, active_low=True)


def test_mock_relay_can_simulate_failure():
    relays = MockRelayDriver()
    relays.fail_pins.add(26)
    with pytest.raises(HardwareError):
        relays.set_state(26, on=True, active_low=False)


def test_mock_hardware_produces_plausible_readings(settings):
    hardware = build_hardware(settings)
    assert len(hardware.climate_sensors) == len(settings.dht22_sensors)

    readings = [hardware.climate_sensors[0].read() for _ in range(50)]
    good = [r for r in readings if r.ok]
    assert good, "at least some reads should succeed"
    assert all(-20 < r.temperature_c < 50 and 0 <= r.humidity <= 100 for r in good)

    signal, supply = hardware.analog.read_voltages((0, 1))
    battery = supply * 57 / 10
    assert 12.0 < battery < 14.0
    assert 0.03 < signal / battery < 0.17

    fix = hardware.gps.read_fix(timeout_seconds=1)
    assert fix is not None and -90 <= fix.lat <= 90
