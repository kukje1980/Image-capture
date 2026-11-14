import pytest

from fundusview.extract.normalize import clean_name, norm_date, norm_eye, norm_sex, norm_time, parse_key_values
from fundusview.models import ExtractedMeta


@pytest.mark.parametrize("raw,expected", [
    ("20240305", "2024-03-05"), ("2024-03-05", "2024-03-05"), ("2024.3.5", "2024-03-05"),
    ("2024_10_08", "2024-10-08"), ("2024:10:08 10:46:27", "2024-10-08"), ("2024-10-08 10:46:27", "2024-10-08"),
    ("05.03.2024", "2024-03-05"), ("20241345", None), ("12345678", None), ("", None),
])
def test_norm_date(raw, expected):
    assert norm_date(raw) == expected


def test_norm_date_two_digit_year():
    assert norm_date("700101") == "1970-01-01"


@pytest.mark.parametrize("raw,expected", [
    ("101500", "10:15:00"), ("10:15", "10:15:00"), ("10_46_27", "10:46:27"), ("111502.123", "11:15:02"),
    ("2561", None),
])
def test_norm_time(raw, expected):
    assert norm_time(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("R", "OD"), ("od", "OD"), ("RIGHT", "OD"), ("우안", "OD"), ("L", "OS"), ("LE", "OS"), ("좌안", "OS"), ("x", None),
])
def test_norm_eye(raw, expected):
    assert norm_eye(raw) == expected


def test_norm_sex_and_names():
    assert norm_sex("여") == "F" and norm_sex("male") == "M" and norm_sex("?") is None
    assert clean_name("HONG^GILDONG") == "HONG GILDONG"
    assert clean_name("박^지호") == "박지호"


def test_parse_key_values_mixed_text():
    m = ExtractedMeta()
    parse_key_values("PatientID=12345; Name: 홍길동\nDOB: 1970-01-02\nSex=M\nEye: OS\n촬영일: 2024/03/05", m, "t")
    assert (m.patient_id, m.name, m.birth_date, m.sex, m.laterality, m.exam_date) == (
        "12345", "홍길동", "1970-01-02", "M", "OS", "2024-03-05")
    assert m.sources["patient_id"] == "t"
