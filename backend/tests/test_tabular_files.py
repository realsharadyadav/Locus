from pathlib import Path

from openpyxl import Workbook

from backend.app.files import extract_text_from_path


def test_large_incident_csv_gets_deterministic_group_profile(tmp_path: Path):
    path = tmp_path / "snow-incidents.csv"
    rows = ["Date,Region,Severity,Incident Type,Cost"]
    regions = ["North", "South", "North", "West"]
    severities = ["Low", "High", "Medium"]
    incident_types = ["Road closure", "Vehicle delay"]
    for index in range(1_000):
        rows.append(f"2026-{(index % 4) + 1:02d}-01,{regions[index % 4]},{severities[index % 3]},{incident_types[index % 2]},{100 + index}")
    path.write_text("\n".join(rows), encoding="utf-8")

    profile = extract_text_from_path(path.name, path)

    assert "Rows analyzed: 1,000" in profile
    assert "#### Region" in profile
    assert "| North | 500 | 50.0% |" in profile
    assert "#### Severity" in profile
    assert "### Numeric summaries" in profile
    assert "### Time distributions" in profile
    assert "| 2026-01 | 250 |" in profile


def test_xlsx_is_read_in_streaming_mode_and_grouped(tmp_path: Path):
    path = tmp_path / "incidents.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Snow Events")
    sheet.append(["Region", "Status", "Impact"])
    for index in range(200):
        sheet.append(["North" if index % 2 == 0 else "South", "Closed" if index % 4 == 0 else "Open", index])
    workbook.save(path)

    profile = extract_text_from_path(path.name, path)

    assert "## Sheet: Snow Events" in profile
    assert "Rows analyzed: 200" in profile
    assert "| North | 100 | 50.0% |" in profile
    assert "| Closed | 50 | 25.0% |" in profile


def test_tabular_profile_analyzes_text_fields_generically(tmp_path: Path):
    path = tmp_path / "records.csv"
    rows = ["group,headline,details"]
    for index in range(1, 21):
        rows.append(f"Category {index},Password failure {index},Employees cannot authenticate to the portal after password reset")
        rows.append(f"Category {index},Login failure {index},Authentication fails repeatedly after password reset")
    path.write_text("\n".join(rows), encoding="utf-8")

    profile = extract_text_from_path(path.name, path)

    assert "Profile version: 3" in profile
    assert "### Text evidence" in profile
    assert "#### headline" in profile
    assert "#### details" in profile
    assert "Recurring terms" in profile
    assert "Employees cannot authenticate" in profile
