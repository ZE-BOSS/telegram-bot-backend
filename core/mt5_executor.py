"""
MT5 trade execution engine (Railway-safe).

This module does NOT import MetaTrader5.
It sends trade commands to a Windows MT5 Gateway over HTTP.
"""

import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
import httpx
import os

logger = logging.getLogger(__name__)

# This is the Windows MT5 gateway
# Example: http://192.168.1.50:9000
MT5_GATEWAY_URL = os.getenv("MT5_GATEWAY_URL")


class MT5Executor:
    """
    Executes trades by forwarding commands to a Windows MT5 service.
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.is_connected = False
        self.account_key: Optional[str] = None

    # ------------------------
    # Connection
    # ------------------------

    async def connect(self, login: int, password: str, server: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{MT5_GATEWAY_URL}/connect",
                    json={
                        "login": login,
                        "password": password,
                        "server": server,
                    },
                )

                if r.status_code != 200:
                    logger.error(f"MT5 connect failed: {r.text}")
                    return False

                self.is_connected = True
                self.account_key = f"{login}_{server}"
                return True

        except Exception as e:
            logger.error(f"MT5 gateway unreachable: {e}")
            return False

    # ------------------------
    # Market Orders
    # ------------------------

    async def execute_market_order(
        self,
        symbol: str,
        side: str,
        volume: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        comment: str = "Trading Signal",
    ) -> Dict[str, Any]:

        if not self.is_connected:
            return {"success": False, "error": "MT5 not connected"}

        payload = {
            "symbol": symbol,
            "side": side,
            "volume": float(volume),
            "comment": comment,
        }

        if stop_loss:
            payload["stop_loss"] = float(stop_loss)
        if take_profit:
            payload["take_profit"] = float(take_profit)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{MT5_GATEWAY_URL}/trade/market", json=payload)

                if r.status_code != 200:
                    return {"success": False, "error": r.text}

                data = r.json()
                data["success"] = True
                return data

        except Exception as e:
            logger.error(f"Market order error: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------
    # Limit Orders
    # ------------------------

    async def execute_limit_order(
        self,
        symbol: str,
        side: str,
        price: float,
        volume: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        comment: str = "Limit Order",
        expiration: Optional[datetime] = None,
    ) -> Dict[str, Any]:

        if not self.is_connected:
            return {"success": False, "error": "MT5 not connected"}

        payload = {
            "symbol": symbol,
            "side": side,
            "price": price,
            "volume": float(volume),
            "comment": comment,
        }

        if stop_loss:
            payload["stop_loss"] = float(stop_loss)
        if take_profit:
            payload["take_profit"] = float(take_profit)
        if expiration:
            payload["expiration"] = int(expiration.timestamp())

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{MT5_GATEWAY_URL}/trade/limit", json=payload)

                if r.status_code != 200:
                    return {"success": False, "error": r.text}

                data = r.json()
                data["success"] = True
                return data

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------
    # Positions
    # ------------------------

    async def close_position(self, ticket: int) -> Dict[str, Any]:
        if not self.is_connected:
            return {"success": False, "error": "MT5 not connected"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{MT5_GATEWAY_URL}/trade/close",
                    json={"ticket": ticket},
                )

                if r.status_code != 200:
                    return {"success": False, "error": r.text}

                data = r.json()
                data["success"] = True
                return data

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def modify_position(
        self,
        ticket: int,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Dict[str, Any]:

        payload = {"ticket": ticket}
        if stop_loss:
            payload["stop_loss"] = float(stop_loss)
        if take_profit:
            payload["take_profit"] = float(take_profit)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{MT5_GATEWAY_URL}/trade/modify", json=payload)

                if r.status_code != 200:
                    return {"success": False, "error": r.text}

                data = r.json()
                data["success"] = True
                return data

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------
    # Info
    # ------------------------

    async def get_account_info(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{MT5_GATEWAY_URL}/account")
                return r.json()
        except Exception:
            return {"error": "MT5 gateway unreachable"}

    async def get_positions(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{MT5_GATEWAY_URL}/positions")
                return r.json()
        except Exception:
            return []

    # ------------------------
    # Disconnect
    # ------------------------

    async def disconnect(self):
        self.is_connected = False
        self.account_key = None
