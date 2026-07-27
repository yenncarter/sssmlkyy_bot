"""Service catalog for booking."""

from __future__ import annotations

from dataclasses import dataclass

from domain.enums import ServiceCode


@dataclass(frozen=True, slots=True)
class Service:
    code: ServiceCode
    title: str
    duration_minutes: int


SERVICES: tuple[Service, ...] = (
    Service(ServiceCode.MANICURE, "Маникюр", 90),
    Service(ServiceCode.GEL, "Маникюр + гель-лак", 120),
    Service(ServiceCode.REMOVAL, "Снятие покрытия", 30),
    Service(ServiceCode.DESIGN, "Дизайн", 60),
)

SERVICES_BY_CODE = {s.code.value: s for s in SERVICES}


def get_service(code: str) -> Service | None:
    return SERVICES_BY_CODE.get(code)
