"""Regression checks for the combined safety and analysis branches."""
import sqlite3

import pytest

from app.db.measurements_dao import Measurement
from app.models.patient import Patient


def test_measurement_failure_rolls_back_before_next_write(app_env):
    _, db = app_env
    with pytest.raises(sqlite3.IntegrityError):
        db.measurements.insert(Measurement(patient_id=999, kind="nuclear", value=20))
    assert not db._conn.in_transaction
    pid = db.patients.insert(Patient(chart_no="SAFE-M", name="통합 테스트"))
    mid = db.measurements.insert(Measurement(patient_id=pid, kind="nuclear", value=20))
    assert db.measurements.latest(pid, "nuclear").id == mid
