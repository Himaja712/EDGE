import os
import uuid
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from models import Band, CycleStatus, Employee, PerformanceCycle, PerformanceDiary, RoleEnum, SelfStatus

load_dotenv(Path(__file__).with_name(".env"))

NEST_EMPLOYEE_LIST_URL = os.getenv(
    "NEST_EMPLOYEE_LIST_URL",
    os.getenv("NEST_API_URL", "https://api.nicesoftwaresolutions.com/pms/employee-list"),
)


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _pick(item, *keys):
    for key in keys:
        value = _clean(item.get(key))
        if value:
            return value
    return None


def _extract_employee_rows(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("NEST employee API response must be JSON object or list")

    for key in ("data", "Data", "employees", "Employees", "items", "Items", "result", "Result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            try:
                return _extract_employee_rows(value)
            except ValueError:
                pass

    raise ValueError("NEST employee API response did not include an employee list")


def _nest_datetime(value):
    value = _clean(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _fetch_nest_employees():
    nest_api_token = os.getenv("NEST_API_TOKEN")
    if not nest_api_token:
        raise ValueError("NEST_API_TOKEN is not configured")

    response = requests.get(
        NEST_EMPLOYEE_LIST_URL,
        headers={"Authorization": f"Bearer {nest_api_token}"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError(payload.get("message") or "NEST employee API returned success=false")

    return _extract_employee_rows(payload)


def _employee_code(item):
    return _pick(
        item,
        "EmpCode",
        "EmployeeCode",
        "Employee Code",
        "Code",
        "EmpID",
        "EmployeeID",
        "EmployeeId",
        "EmployeeNumber",
    )


def _employee_email(item):
    return _pick(item, "EmpEmail", "EmployeeEmail", "Email", "EmailID", "EmailId", "OfficialEmail", "WorkEmail")


def _employee_name(item):
    return _pick(item, "EmpName", "EmployeeName", "Name", "FullName", "DisplayName")


def _manager_code(item):
    return _pick(item, "ReportingManagerCode", "ManagerCode", "Reporting Manager Code")


def _approver_code(item):
    return _pick(item, "SeniorManagerCode", "ApproverCode", "Senior Manager Code")


def _band_code(item):
    band = item.get("Band")
    if isinstance(band, dict):
        value = _pick(band, "Value", "BandValue", "Code", "Name")
        if value:
            return value[:20]
        return None
    if band is not None and not isinstance(band, str):
        return None
    value = _pick(item, "BandValue", "BandCode", "Band Code", "Band")
    return value[:20] if value else None


def _designation(item):
    return _pick(item, "Designation", "JobTitle", "Title", "Role")


def _is_active(item):
    value = item.get("Active", item.get("IsActive", item.get("Status")))
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    value = str(value).strip().lower()
    return value in {"1", "true", "yes", "y", "active"}


def _is_intern_band(band_name):
    value = _clean(band_name)
    return bool(value and value.lower() == "intern")


def _role_for_employee(emp_code, manager_codes, approver_codes):
    if emp_code in approver_codes:
        return RoleEnum.approver
    if emp_code in manager_codes:
        return RoleEnum.manager
    return RoleEnum.reportee


def _band_id_for_nest_band(nest_band, band_by_code):
    value = _clean(nest_band)
    if not value:
        return None

    return band_by_code.get(value.upper())


def _should_update_employee(emp, emp_code, nest_modified_at):
    if emp.employee_code != emp_code:
        return True
    if not emp.updated_at:
        return True
    if nest_modified_at and nest_modified_at > emp.updated_at:
        return True
    return False


def _sync_open_diary_relationships(db, employees_by_code):
    employees_by_id = {
        emp.id: emp
        for emp in employees_by_code.values()
        if emp.role != RoleEnum.admin and emp.is_active
    }
    if not employees_by_id:
        return 0

    open_diaries = (
        db.query(PerformanceDiary)
        .join(PerformanceCycle, PerformanceDiary.cycle_id == PerformanceCycle.id)
        .filter(
            PerformanceCycle.status != CycleStatus.closed,
            PerformanceDiary.employee_id.in_(list(employees_by_id.keys())),
        )
        .all()
    )

    updated = 0
    for diary in open_diaries:
        emp = employees_by_id.get(diary.employee_id)
        if not emp:
            continue

        manager_id = emp.manager_id or emp.approver_id
        approver_id = emp.approver_id or manager_id
        if not manager_id or not approver_id:
            continue

        if diary.manager_id != manager_id or diary.approver_id != approver_id:
            diary.manager_id = manager_id
            diary.approver_id = approver_id
            diary.updated_at = datetime.utcnow()
            updated += 1

    return updated


def _initial_self_status_for_cycle(cycle, now):
    if cycle.status != CycleStatus.step2:
        return SelfStatus.not_open
    return SelfStatus.open


def _create_missing_open_cycle_diaries(db, employees_by_code):
    employees = [
        emp
        for emp in employees_by_code.values()
        if emp.role != RoleEnum.admin and emp.is_active
    ]
    if not employees:
        return 0

    open_cycles = (
        db.query(PerformanceCycle)
        .filter(PerformanceCycle.status != CycleStatus.closed)
        .all()
    )
    if not open_cycles:
        return 0

    cycle_ids = [cycle.id for cycle in open_cycles]
    employee_ids = [emp.id for emp in employees]
    existing_diaries = {
        (cycle_id, employee_id)
        for cycle_id, employee_id in db.query(
            PerformanceDiary.cycle_id,
            PerformanceDiary.employee_id,
        )
        .filter(
            PerformanceDiary.cycle_id.in_(cycle_ids),
            PerformanceDiary.employee_id.in_(employee_ids),
        )
        .all()
    }

    now = datetime.utcnow()
    created = 0
    for cycle in open_cycles:
        for emp in employees:
            if (cycle.id, emp.id) in existing_diaries:
                continue

            manager_id = emp.manager_id or emp.approver_id
            approver_id = emp.approver_id or manager_id
            if not manager_id or not approver_id:
                continue

            db.add(PerformanceDiary(
                id=uuid.uuid4(),
                cycle_id=cycle.id,
                employee_id=emp.id,
                manager_id=manager_id,
                approver_id=approver_id,
                self_status=_initial_self_status_for_cycle(cycle, now),
                created_at=now,
                updated_at=now,
            ))
            existing_diaries.add((cycle.id, emp.id))
            created += 1

    return created


def sync_nest_employees(db):
    nest_employees = _fetch_nest_employees()

    manager_codes = {
        _manager_code(item)
        for item in nest_employees
        if _manager_code(item)
    }
    approver_codes = {
        _approver_code(item)
        for item in nest_employees
        if _approver_code(item)
    }

    band_by_code = {
        b.band_code.upper(): b.id
        for b in db.query(Band).filter(Band.is_active == True).all()
    }
    employees_by_code = {
        e.employee_code: e
        for e in db.query(Employee).all()
    }
    employees_by_email = {
        e.email.lower(): e
        for e in employees_by_code.values()
        if e.email
    }

    inserted = 0
    updated = 0
    unchanged = 0
    relationships_updated = 0
    diary_relationships_updated = 0
    diaries_created = 0
    deactivated_missing_from_nest = 0
    skipped = 0
    current_nest_codes = {
        _employee_code(item)
        for item in nest_employees
        if _employee_code(item)
    }
    current_nest_emails = {
        _employee_email(item).lower()
        for item in nest_employees
        if _employee_email(item)
    }

    # First pass: insert new employees or update changed employee details only.
    for item in nest_employees:
        emp_code = _employee_code(item)
        email = _employee_email(item)
        full_name = _employee_name(item)
        band_code = _band_code(item)
        band_name = _designation(item)

        if not emp_code or not email or not full_name:
            skipped += 1
            continue

        role = _role_for_employee(emp_code, manager_codes, approver_codes)
        band_id = _band_id_for_nest_band(band_code, band_by_code)
        is_active = _is_active(item) and not _is_intern_band(band_name)
        created_at = _nest_datetime(item.get("CreatedDate")) or datetime.utcnow()
        modified_at = _nest_datetime(item.get("ModifiedDate")) or datetime.utcnow()

        emp = employees_by_code.get(emp_code) or employees_by_email.get(email.lower())
        if emp:
            should_update = _should_update_employee(emp, emp_code, modified_at)
            old_code = emp.employee_code
            old_values = (
                emp.full_name,
                emp.employee_code,
                emp.email,
                emp.band_id,
                emp.band_code,
                emp.band_name,
                emp.is_active,
            )

            # Role is derived from the full NEST hierarchy, so keep it fresh even
            # when the employee's own ModifiedDate did not change.
            if emp.role != RoleEnum.admin:
                emp.role = role

            emp.full_name = full_name
            emp.employee_code = emp_code
            emp.email = email
            emp.band_id = band_id
            emp.band_code = band_code
            emp.band_name = band_name
            emp.is_active = is_active
            emp.created_at = emp.created_at or created_at
            new_values = (
                emp.full_name,
                emp.employee_code,
                emp.email,
                emp.band_id,
                emp.band_code,
                emp.band_name,
                emp.is_active,
            )
            if should_update or old_values != new_values:
                emp.updated_at = modified_at
                if old_code != emp_code:
                    employees_by_code.pop(old_code, None)
                employees_by_code[emp_code] = emp
                employees_by_email[email.lower()] = emp
                updated += 1
            else:
                unchanged += 1
        else:
            emp = Employee(
                id=uuid.uuid4(),
                employee_code=emp_code,
                full_name=full_name,
                email=email,
                band_id=band_id,
                band_code=band_code,
                band_name=band_name,
                role=role,
                is_active=is_active,
                manager_id=None,
                approver_id=None,
                created_at=created_at,
                updated_at=modified_at,
            )
            db.add(emp)
            employees_by_code[emp_code] = emp
            employees_by_email[email.lower()] = emp
            inserted += 1

    db.flush()

    # Second pass: after all employees exist, wire manager/approver UUIDs.
    for item in nest_employees:
        emp_code = _employee_code(item)
        if not emp_code:
            continue

        emp = employees_by_code.get(emp_code)
        if not emp:
            continue

        manager_code = _manager_code(item)
        approver_code = _approver_code(item)
        manager = employees_by_code.get(manager_code) if manager_code else None
        approver = employees_by_code.get(approver_code) if approver_code else None

        manager_id = manager.id if manager else None
        approver_id = approver.id if approver else None
        if emp.manager_id != manager_id or emp.approver_id != approver_id:
            emp.manager_id = manager_id
            emp.approver_id = approver_id
            relationships_updated += 1

    # Do not delete historical diaries; deactivate PMS employees missing from
    # the latest NEST response so active counts stay aligned with NEST.
    for emp in employees_by_code.values():
        if emp.role == RoleEnum.admin or not emp.is_active:
            continue
        email = emp.email.lower() if emp.email else None
        if emp.employee_code in current_nest_codes or email in current_nest_emails:
            continue
        emp.is_active = False
        emp.updated_at = datetime.utcnow()
        deactivated_missing_from_nest += 1

    diary_relationships_updated = _sync_open_diary_relationships(db, employees_by_code)
    diaries_created = _create_missing_open_cycle_diaries(db, employees_by_code)

    db.commit()

    return {
        "fetched": len(nest_employees),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "relationships_updated": relationships_updated,
        "diary_relationships_updated": diary_relationships_updated,
        "diaries_created": diaries_created,
        "deactivated_missing_from_nest": deactivated_missing_from_nest,
        "skipped": skipped,
    }


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        print(sync_nest_employees(db))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
