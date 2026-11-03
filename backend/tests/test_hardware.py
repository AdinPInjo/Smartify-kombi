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


# --- GGA accuracy and u-blox tuning --------------------------------------------------

from smartify.hardware import ubx  # noqa: E402


def test_gga_hdop_is_parsed():
    sentence = nmea.parse(_with_checksum(GGA[1:].split("*")[0]))
    assert isinstance(sentence, nmea.GgaSentence)
    assert sentence.hdop == pytest.approx(0.9)


def test_ubx_frame_checksum_matches_the_u_blox_manual():
    # CFG-NAV5 poll, as documented: B5 62 06 24 00 00 2A 84
    assert ubx.frame(0x06, 0x24) == bytes.fromhex("b562062400002a84")


def test_ubx_nav5_sets_static_hold_and_automotive_model():
    message = ubx.cfg_nav5(static_hold_cm_s=50)
    assert message[:4] == bytes.fromhex("b5620624") and len(message) == 6 + 36 + 2
    payload = message[6:-2]
    assert int.from_bytes(payload[0:2], "little") == 0x0041  # dyn + static hold applied
    assert payload[2] == ubx.DYN_MODEL_AUTOMOTIVE
    assert payload[22] == 50
    assert ubx.checksum(message[2:-2]) == message[-2:]


def test_ubx_sbas_message():
    message = ubx.cfg_sbas()
    assert message[:4] == bytes.fromhex("b5620616") and len(message) == 6 + 8 + 2
    assert message[6:9] == bytes((0x01, 0x07, 3))


def test_find_ack_between_nmea():
    ack = ubx.frame(0x05, 0x01, bytes((0x06, 0x24)))
    nak = ubx.frame(0x05, 0x00, bytes((0x06, 0x16)))
    noise = b"$GPGSV,3,1,09*40\r\n"
    assert ubx.find_ack(noise + ack + noise, 0x06, 0x24) is True
    assert ubx.find_ack(noise + nak, 0x06, 0x16) is False
    assert ubx.find_ack(noise, 0x06, 0x24) is None
    assert ubx.find_ack(noise + ack, 0x06, 0x16) is None  # ACK for another message


class _FakePort:
    def __init__(self, replies):
        self.replies = list(replies)
        self.written = []
        self.in_waiting = 0

    def write(self, data):
        self.written.append(data)
        self.pending = self.replies.pop(0) if self.replies else b""

    def flush(self):
        pass

    def read(self, n):
        chunk, self.pending = self.pending[:64], self.pending[64:]
        return chunk


def test_receiver_sends_tuning_and_reads_acks(caplog, monkeypatch):
    from smartify.hardware.pi import gps as pi_gps

    monkeypatch.setattr(pi_gps, "_ACK_TIMEOUT", 0.2)
    receiver = pi_gps.SerialGpsReceiver("/dev/null")
    port = _FakePort(
        [
            b"$GPRMC,junk*00\r\n" + ubx.frame(0x05, 0x01, bytes((0x06, 0x24))),
            b"",  # no answer to SBAS
        ]
    )
    with caplog.at_level("INFO"):
        receiver._tune(port)
    assert port.written == [message for _, _, _, message in ubx.TUNING]
    assert "GPS tuning applied: static hold" in caplog.text
    assert "did not confirm tuning (SBAS" in caplog.text
