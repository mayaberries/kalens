from enum import Enum
from typing import Dict, List
import datetime

from pydantic import Field, model_validator

from kalens.models.core import CoreModel, DateTimeModelMixin, IDModelMixin


class Weekday(str, Enum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"


class TimeRange(CoreModel):
    start: datetime.time
    end: datetime.time

    @model_validator(mode="after")
    def end_after_start(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


WeeklySchedule = Dict[Weekday, List[TimeRange]]

# Placeholder hours a fresh clinic gets automatically -- see
# ClinicsRepository.create_clinic_for_admin. Not a guess at real hours,
# just something sane for GET to return before the admin has configured
# anything, so the endpoint never has to special-case "never set up yet".
DEFAULT_WEEKLY_SCHEDULE: WeeklySchedule = {
    Weekday.monday: [TimeRange(start=datetime.time(9, 0), end=datetime.time(17, 0))],
    Weekday.tuesday: [TimeRange(start=datetime.time(9, 0), end=datetime.time(17, 0))],
    Weekday.wednesday: [TimeRange(start=datetime.time(9, 0), end=datetime.time(17, 0))],
    Weekday.thursday: [TimeRange(start=datetime.time(9, 0), end=datetime.time(17, 0))],
    Weekday.friday: [TimeRange(start=datetime.time(9, 0), end=datetime.time(17, 0))],
    Weekday.saturday: [],
    Weekday.sunday: [],
}


class ClinicAvailabilityBase(CoreModel):
    schedule: WeeklySchedule = Field(default_factory=dict)
    timezone: str = "UTC"


class ClinicAvailabilityUpdate(CoreModel):
    """
    Body for PUT /clinics/{clinic_id}/availability/. Deliberately a full
    replace, not a per-day patch -- mirrors how Calendly's own hours editor
    behaves (change one day, resend the whole week) and avoids ambiguity
    about what an omitted day means (closed, vs "leave as-is"). Any weekday
    not present in the payload is normalized to closed (empty list) below,
    it is never left as whatever was previously stored.
    """
    schedule: WeeklySchedule = Field(default_factory=dict)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def normalize_and_validate_ranges(self) -> "ClinicAvailabilityUpdate":
        normalized: WeeklySchedule = {}
        for day in Weekday:
            ranges = sorted(self.schedule.get(day, []), key=lambda r: r.start)
            for prev, curr in zip(ranges, ranges[1:]):
                if curr.start < prev.end:
                    raise ValueError(f"Overlapping time ranges for {day.value}")
            normalized[day] = ranges
        self.schedule = normalized
        return self


class ClinicAvailabilityInDB(IDModelMixin, DateTimeModelMixin, ClinicAvailabilityBase):
    clinic_id: str