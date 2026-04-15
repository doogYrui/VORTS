from __future__ import annotations

import asyncio
import socket
import time
from collections import deque
from typing import Deque

import psutil

from .models import NetworkHistoryResponse, NetworkSample, NetworkStatsResponse


def auto_detect_public_interface() -> str:
    interfaces = psutil.net_if_addrs()

    for interface, addresses in interfaces.items():
        if interface == "lo":
            continue
        for address in addresses:
            if address.family != socket.AF_INET6:
                continue
            value = address.address.split("%", 1)[0]
            if value == "::1" or value.startswith("fe80:"):
                continue
            return interface

    for interface in interfaces:
        if interface == "lo" or interface.startswith(("docker", "br-", "veth")):
            continue
        return interface

    return "lo"


class NetworkStatsMonitor:
    def __init__(self, interface: str | None, history_seconds: int, logger) -> None:
        self.logger = logger
        self.interface = interface or auto_detect_public_interface()
        self.history: Deque[NetworkSample] = deque(maxlen=history_seconds)
        self.current = NetworkStatsResponse(
            interface=self.interface,
            timestamp=time.time(),
            upload_kbps=0.0,
            download_kbps=0.0,
        )
        self._last_bytes_sent: int | None = None
        self._last_bytes_recv: int | None = None
        self._last_ts: float | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._prime()
        self._task = asyncio.create_task(self._run(), name="network-stats-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    def get_current(self) -> NetworkStatsResponse:
        return self.current.model_copy(deep=True)

    def get_history(self) -> NetworkHistoryResponse:
        return NetworkHistoryResponse(
            interface=self.interface,
            samples=[sample.model_copy(deep=True) for sample in self.history],
        )

    def _prime(self) -> None:
        counters = psutil.net_io_counters(pernic=True).get(self.interface)
        now = time.time()
        if counters is None:
            self.logger.warning("Network interface %s not found, traffic stats will stay at zero", self.interface)
            self._last_ts = now
            return

        self._last_bytes_sent = counters.bytes_sent
        self._last_bytes_recv = counters.bytes_recv
        self._last_ts = now

    async def _run(self) -> None:
        while True:
            self._sample_once()
            await asyncio.sleep(1.0)

    def _sample_once(self) -> None:
        counters = psutil.net_io_counters(pernic=True).get(self.interface)
        now = time.time()

        if counters is None or self._last_ts is None:
            sample = NetworkSample(timestamp=now, upload_kbps=0.0, download_kbps=0.0)
            self.history.append(sample)
            self.current = NetworkStatsResponse(
                interface=self.interface,
                timestamp=now,
                upload_kbps=0.0,
                download_kbps=0.0,
            )
            return

        if self._last_bytes_sent is None or self._last_bytes_recv is None:
            self._last_bytes_sent = counters.bytes_sent
            self._last_bytes_recv = counters.bytes_recv
            self._last_ts = now
            return

        elapsed = max(now - self._last_ts, 1e-6)
        upload_kbps = max(counters.bytes_sent - self._last_bytes_sent, 0) / 1024.0 / elapsed
        download_kbps = max(counters.bytes_recv - self._last_bytes_recv, 0) / 1024.0 / elapsed

        self._last_bytes_sent = counters.bytes_sent
        self._last_bytes_recv = counters.bytes_recv
        self._last_ts = now

        sample = NetworkSample(
            timestamp=now,
            upload_kbps=round(upload_kbps, 2),
            download_kbps=round(download_kbps, 2),
        )
        self.history.append(sample)
        self.current = NetworkStatsResponse(
            interface=self.interface,
            timestamp=now,
            upload_kbps=sample.upload_kbps,
            download_kbps=sample.download_kbps,
        )
