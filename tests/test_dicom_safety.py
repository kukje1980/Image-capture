"""Patient reassignment and corrected acquisition information must survive DICOM export."""
from dataclasses import replace

import numpy as np
from PIL import Image

from fundusview import dicomnet
from fundusview.config import Settings
from fundusview.dicomnet import EXPLICIT_LE, Item, OP_8BIT, Order


def imported_photo(tmp_path, *, gray=False):
    jpg = tmp_path / "photo.jpg"
    if gray:
        Image.fromarray(np.arange(32 * 24, dtype=np.uint8).reshape(24, 32)).save(jpg)
    else:
        rgb = np.zeros((24, 32, 3), np.uint8)
        rgb[..., 0] = np.arange(32, dtype=np.uint8) * 6
        rgb[..., 1] = 70
        Image.fromarray(rgb).save(jpg)
    original = Item(image_id=1, path=str(jpg), sha256="ab" * 32, patient_id="A", name="Patient A",
                    birth_date="1980-01-02", sex="M", exam_date="2026-11-21", exam_time="11:22:33",
                    laterality="OD", kind="color")
    ds = dicomnet.wrap_photo(original, Settings())
    ds.Laterality = "R"
    ds.PatientBirthTime = "091200"
    ds.PatientAge = "046Y"
    ds.IssuerOfPatientID = "Old clinic"
    ds.AccessionNumber = "Old order"
    ds.AcquisitionDateTime = "20261121112233.125+0900"
    ds.AcquisitionDate = "20261121"
    ds.AcquisitionTime = "112233.125"
    path = tmp_path / "original.dcm"
    ds.save_as(path, enforce_file_format=True)
    return replace(original, path=str(path)), ds


def test_patient_reassignment_clears_previous_demographics_and_order(tmp_path):
    item, source = imported_photo(tmp_path)
    before = (tmp_path / "original.dcm").read_bytes()
    other = replace(item, patient_id="B", name="", birth_date="", sex="")
    result = dicomnet.dataset_of(other, Settings())
    assert result.PatientID == "B"
    assert str(result.PatientName) == ""
    assert result.PatientBirthDate == result.PatientSex == ""
    for keyword in ("PatientBirthTime", "PatientAge", "IssuerOfPatientID", "AccessionNumber"):
        assert keyword not in result
    assert result.StudyInstanceUID != source.StudyInstanceUID
    assert result.SeriesInstanceUID != source.SeriesInstanceUID
    assert result.SOPInstanceUID != source.SOPInstanceUID
    repeated = dicomnet.dataset_of(other, Settings())
    assert repeated.SOPInstanceUID == result.SOPInstanceUID == result.file_meta.MediaStorageSOPInstanceUID
    assert repeated.SeriesInstanceUID == result.SeriesInstanceUID
    assert (tmp_path / "original.dcm").read_bytes() == before


def test_patient_reassignment_uses_target_demographics_and_worklist(tmp_path):
    item, source = imported_photo(tmp_path)
    other = replace(item, patient_id="B", name="Patient B", birth_date="1990-03-04", sex="F",
                    order=Order(patient_id="B", name="Patient B", accession="NEW", study_uid="1.2.3.40"))
    result = dicomnet.dataset_of(other, Settings())
    assert (result.PatientID, str(result.PatientName), result.PatientBirthDate, result.PatientSex) == (
        "B", "Patient B", "19900304", "F")
    assert (result.StudyInstanceUID, result.AccessionNumber) == ("1.2.3.40", "NEW")
    assert result.SeriesInstanceUID != source.SeriesInstanceUID


def test_corrected_eye_date_time_are_consistent_in_all_existing_tags(tmp_path):
    item, source = imported_photo(tmp_path)
    corrected = replace(item, laterality="OS", exam_date="2026-11-22", exam_time="12:34:56")
    result = dicomnet.dataset_of(corrected, Settings())
    assert result.ImageLaterality == result.Laterality == "L"
    for keyword in ("SeriesDate", "ContentDate", "AcquisitionDate"):
        assert getattr(result, keyword) == "20261122"
    for keyword in ("SeriesTime", "ContentTime", "AcquisitionTime"):
        assert getattr(result, keyword) == "123456"
    assert result.AcquisitionDateTime == "20261122123456+0900"
    assert result.StudyInstanceUID == source.StudyInstanceUID
    assert result.StudyDate == source.StudyDate and result.StudyTime == source.StudyTime
    assert result.SeriesInstanceUID != source.SeriesInstanceUID
    assert result.SeriesInstanceUID == dicomnet.dataset_of(corrected, Settings()).SeriesInstanceUID
    assert result.SOPInstanceUID != source.SOPInstanceUID
    assert result.SOPInstanceUID == dicomnet.dataset_of(corrected, Settings()).SOPInstanceUID
    assert result.file_meta.MediaStorageSOPInstanceUID == result.SOPInstanceUID


def test_unchanged_metadata_preserves_acquisition_and_study_timestamps(tmp_path):
    item, source = imported_photo(tmp_path)
    source.StudyDate = "20261120"
    source.StudyTime = "090000"
    source.save_as(item.path, enforce_file_format=True)
    result = dicomnet.dataset_of(item, Settings())
    assert result.StudyDate == "20261120" and result.StudyTime == "090000"
    assert result.AcquisitionDateTime == "20261121112233.125+0900"
    assert result.AcquisitionTime == "112233.125"
    assert result.SeriesInstanceUID == source.SeriesInstanceUID
    assert result.SOPInstanceUID == source.SOPInstanceUID
    assert result.PixelData == source.PixelData


def test_date_only_correction_preserves_fractional_acquisition_time(tmp_path):
    item, _ = imported_photo(tmp_path)
    result = dicomnet.dataset_of(replace(item, exam_date="2026-11-22"), Settings())
    assert result.AcquisitionDateTime == "20261122112233.125+0900"
    assert result.AcquisitionTime == "112233.125"


def test_eye_correction_also_repairs_conflicting_series_laterality(tmp_path):
    item, source = imported_photo(tmp_path)
    source.Laterality = "L"
    source.save_as(item.path, enforce_file_format=True)
    result = dicomnet.dataset_of(item, Settings())
    assert result.ImageLaterality == result.Laterality == "R"
    assert result.SeriesInstanceUID != source.SeriesInstanceUID


def test_new_worklist_study_gets_stable_separate_series_and_instance(tmp_path):
    item, source = imported_photo(tmp_path)
    ordered = replace(item, order=Order(patient_id="A", study_uid="1.2.3.999", accession="NEW"))
    first = dicomnet.dataset_of(ordered, Settings())
    again = dicomnet.dataset_of(ordered, Settings())
    assert first.StudyInstanceUID == "1.2.3.999"
    assert first.SeriesInstanceUID != source.SeriesInstanceUID
    assert first.SOPInstanceUID != source.SOPInstanceUID
    assert first.SeriesInstanceUID == again.SeriesInstanceUID
    assert first.SOPInstanceUID == again.SOPInstanceUID == first.file_meta.MediaStorageSOPInstanceUID


def db_item(item, **changes):
    """Build the production Item from a library record, including explicitly cleared values."""
    row = dict(id=item.image_id, file_path=item.path, sha256=item.sha256, meta_json="{}", modality=item.kind,
               exam_date=item.exam_date, exam_time=item.exam_time, laterality=item.laterality,
               device=item.device, fov_deg=item.fov_deg, note=item.note)
    row.update(changes)
    patient = dict(patient_id=item.patient_id, name=item.name, birth_date=item.birth_date, sex=item.sex)
    return dicomnet.item_of(row, patient)


def test_production_item_explicitly_cleared_metadata_does_not_revive_source_tags(tmp_path):
    item, source = imported_photo(tmp_path)
    cleared = db_item(item, exam_date=None, exam_time=None, laterality=None)
    assert cleared.metadata_authoritative
    result = dicomnet.dataset_of(cleared, Settings())
    assert result.ImageLaterality == "U" and result.Laterality == ""
    for keyword in ("SeriesDate", "ContentDate", "AcquisitionDate", "SeriesTime", "ContentTime",
                    "AcquisitionTime", "AcquisitionDateTime"):
        assert str(getattr(result, keyword)) == ""
    assert result.StudyDate == source.StudyDate and result.StudyTime == source.StudyTime
    assert result.SOPInstanceUID != source.SOPInstanceUID
    assert result.SOPInstanceUID == dicomnet.dataset_of(cleared, Settings()).SOPInstanceUID


def test_production_item_clearing_only_time_keeps_date_without_old_time_or_zone(tmp_path):
    item, _ = imported_photo(tmp_path)
    result = dicomnet.dataset_of(db_item(item, exam_time=None), Settings())
    assert result.AcquisitionDateTime == "20261121"
    assert result.AcquisitionTime == result.ContentTime == ""
    assert result.ContentDate == "20261121"


def test_unchanged_production_item_preserves_source_hierarchy_and_fractional_time(tmp_path):
    item, source = imported_photo(tmp_path)
    result = dicomnet.dataset_of(db_item(item), Settings())
    assert result.SOPInstanceUID == source.SOPInstanceUID
    assert result.SeriesInstanceUID == source.SeriesInstanceUID
    assert result.AcquisitionDateTime == source.AcquisitionDateTime


def test_manual_item_unspecified_metadata_preserves_source_values(tmp_path):
    item, source = imported_photo(tmp_path)
    result = dicomnet.dataset_of(replace(item, exam_date="", exam_time="", laterality=""), Settings())
    assert result.ImageLaterality == "R"
    assert result.AcquisitionDateTime == source.AcquisitionDateTime
    assert result.SOPInstanceUID == source.SOPInstanceUID


def test_repeat_compressed_dicom_fallback_has_stable_rgb_conversion_identity(tmp_path):
    item, source = imported_photo(tmp_path)
    accepted = {(OP_8BIT, EXPLICIT_LE)}
    one = dicomnet._fit(dicomnet.dataset_of(item, Settings()), item, Settings(), accepted)
    two = dicomnet._fit(dicomnet.dataset_of(item, Settings()), item, Settings(), accepted)
    assert one.PhotometricInterpretation == "RGB"
    assert one.SOPInstanceUID == two.SOPInstanceUID == one.file_meta.MediaStorageSOPInstanceUID
    assert one.SOPInstanceUID != source.SOPInstanceUID
    assert one.PixelData == two.PixelData


def test_grayscale_decompression_preserves_source_instance(tmp_path):
    item, source = imported_photo(tmp_path, gray=True)
    result = dicomnet._fit(dicomnet.dataset_of(item, Settings()), item, Settings(), {(OP_8BIT, EXPLICIT_LE)})
    assert result.PhotometricInterpretation == "MONOCHROME2"
    assert result.SOPInstanceUID == source.SOPInstanceUID == result.file_meta.MediaStorageSOPInstanceUID


def test_bilateral_image_has_bilateral_image_tag_and_unknown_series_side(tmp_path):
    item, _ = imported_photo(tmp_path)
    result = dicomnet.dataset_of(replace(item, laterality="OU"), Settings())
    assert result.ImageLaterality == "B"
    assert result.Laterality == ""
    jpeg_item = replace(item, path=str(tmp_path / "photo.jpg"), laterality="OU", derived=True)
    wrapped = dicomnet.wrap_photo(jpeg_item, Settings())
    assert wrapped.ImageLaterality == "B" and wrapped.Laterality == ""


def test_acquisition_correction_keeps_distinct_study_metadata_under_same_uid(tmp_path):
    item, source = imported_photo(tmp_path)
    source.StudyDate, source.StudyTime = "20261101", "090000"
    source.save_as(item.path, enforce_file_format=True)
    corrected = replace(item, exam_date="2026-11-22", exam_time="12:34:56")
    result = dicomnet.dataset_of(corrected, Settings())
    assert result.StudyInstanceUID == source.StudyInstanceUID
    assert result.StudyDate == "20261101" and result.StudyTime == "090000"
    assert result.SeriesDate == result.ContentDate == "20261122"
    assert result.SeriesTime == result.ContentTime == "123456"


def test_reassignment_removes_all_old_patient_group_metadata(tmp_path):
    item, source = imported_photo(tmp_path)
    source.AdditionalPatientHistory = "Old patient's private medical history"
    source.MedicalAlerts = "Old patient alert"
    source.Allergies = "Old allergy"
    source.EthnicGroup = "Old group"
    source.PatientMotherBirthName = "Old family name"
    source.save_as(item.path, enforce_file_format=True)
    result = dicomnet.dataset_of(replace(item, patient_id="B", name="B", birth_date="", sex=""), Settings())
    assert {element.keyword for element in result if element.tag.group == 0x0010} == {
        "PatientID", "PatientName", "PatientBirthDate", "PatientSex"}
    assert result.PatientID == "B" and str(result.PatientName) == "B"
    assert result.PatientBirthDate == result.PatientSex == ""


def test_new_study_metadata_uses_target_capture_or_explicit_worklist_schedule(tmp_path):
    item, source = imported_photo(tmp_path)
    source.StudyDate, source.StudyTime = "20261101", "090000"
    source.save_as(item.path, enforce_file_format=True)
    target = replace(item, patient_id="B", exam_date="2026-11-22", exam_time="12:34:56")
    reassigned = dicomnet.dataset_of(target, Settings())
    assert reassigned.StudyDate == "20261122" and reassigned.StudyTime == "123456"
    ordered = replace(target, order=Order(patient_id="B", study_uid="1.2.3.400", date="2026-11-20",
                                          time="08:30:00", accession="B-NEW"))
    with_order = dicomnet.dataset_of(ordered, Settings())
    assert with_order.StudyInstanceUID == "1.2.3.400" and with_order.AccessionNumber == "B-NEW"
    assert with_order.StudyDate == "20261120" and with_order.StudyTime == "083000"
    assert with_order.ContentDate == "20261122" and with_order.ContentTime == "123456"
