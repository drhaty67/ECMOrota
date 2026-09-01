from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Duty(StrEnum):
    C1 = "C1"
    C2 = "C2"
    T = "T"
    WEEKEND = "WEEKEND"


class WeekendMode(StrEnum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    REQUIRED = "REQUIRED"


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Absence:
    request_id: str
    consultant: str
    kind: str
    interval: Interval
    reason: str = ""
    note: str = ""
    review_status: str = "Recorded"
    source_location: str = ""


@dataclass(frozen=True)
class WeekPreference:
    consultant: str
    week_start: date
    duty: Duty | None
    wants_work: bool
    weight: int = 10
    hard: bool = False
    note: str = ""


@dataclass
class Consultant:
    name: str
    t_target: int
    weekend_target: int
    c_day_target: int
    weekend_mode: WeekendMode = WeekendMode.STANDARD
    preferred_split_partners: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RotaWeek:
    index: int
    start: date
    duties: dict[Duty, Interval]
    c_intervals: dict[Duty, tuple[Interval, ...]]
    c_dates: dict[Duty, tuple[date, ...]]
    half_a: tuple[Interval, Interval]
    half_b: Interval


@dataclass
class SolverInput:
    period_start: date
    period_end: date
    consultants: list[Consultant]
    absences: list[Absence]
    weeks: list[RotaWeek]
    bank_holidays: tuple[date, ...] = ()
    preferences: list[WeekPreference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Assignment:
    week_start: date
    duty: str
    consultant: str
    credit: float = 0.0
    c_day_credit: int = 0
    duty_dates: tuple[date, ...] = ()


@dataclass
class SolveResult:
    status: str
    assignments: list[Assignment] = field(default_factory=list)
    objective_value: float | None = None
    diagnostics: list[str] = field(default_factory=list)
