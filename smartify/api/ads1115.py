"""
ADS1115 ADC API endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Request, Header

from smartify.auth import require_auth
from smartify.services.ads1115 import ads1115_read_response, ads1115_detect_response


router = APIRouter(tags=["ads1115"])


@router.get("/api/ads1115/read")
def api_ads1115_read(
    request: Request,
    channel: int = 0,
    bus: int = 1,
    addr: int = 0x48,
    pga: float = 4.096,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Read voltage from ADS1115 ADC channel.
    
    Args:
        channel: Channel number (0-3)
        bus: I2C bus number (default 1)
        addr: I2C address (default 0x48)
        pga: PGA voltage range (default 4.096V)
    
    Returns:
        JSON with ok, voltage, raw_value, channel, or error/reason
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    return ads1115_read_response(channel=channel, bus=bus, addr=addr, pga=pga)


@router.get("/api/ads1115/detect")
def api_ads1115_detect(
    request: Request,
    bus: int = 1,
    addr: int = 0x48,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Detect if ADS1115 is present on I2C bus.
    
    Returns:
        JSON with ok, detected, bus, addr
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    return ads1115_detect_response(bus=bus, addr=addr)
