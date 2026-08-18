import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID
from models import Base, Band, Employee, AdminCredential, EmployeeCredential, KRAMaster, KPIMaster, RoleEnum
import bcrypt as _bcrypt
import uuid
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# DATABASE_URL = "postgresql://admin:admin@localhost:5432/pms"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:admin@127.0.0.1:5432/pms_qa")
DEFAULT_EMPLOYEE_PASSWORD = os.getenv("DEFAULT_EMPLOYEE_PASSWORD", "nss@123")

engine = create_engine(
    DATABASE_URL,
    pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "30")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    sync_existing_schema()
    db = SessionLocal()
    try:
        employee_source = os.getenv("EMPLOYEE_SOURCE", "seed").strip().lower()
        if employee_source in {"nest", "manual"}:
            sync_band_reference_data(db)
        elif db.query(Band).count() == 0:
            seed_data(db)
        else:
            sync_band_reference_data(db)
        ensure_admin_credential(db)
        ensure_employee_credentials(db)
    finally:
        db.close()

def sync_existing_schema():
    statements = [
        "ALTER TABLE performance_cycles ALTER COLUMN step2_open_date DROP NOT NULL",
        "ALTER TABLE performance_cycles ALTER COLUMN step2_self_deadline DROP NOT NULL",
        "ALTER TABLE performance_cycles ALTER COLUMN step2_mgr_deadline DROP NOT NULL",
        "ALTER TABLE performance_cycles ALTER COLUMN step2_approval_date DROP NOT NULL",
        "UPDATE performance_diaries SET kra_status = 'draft' WHERE kra_status IS NULL",
        "UPDATE performance_diaries SET self_status = 'not_open' WHERE self_status IS NULL",
        "UPDATE performance_diaries SET mgr_status = 'pending' WHERE mgr_status IS NULL",
        "UPDATE performance_diaries SET final_status = 'pending' WHERE final_status IS NULL",
        "ALTER TABLE bands ALTER COLUMN band_code TYPE VARCHAR(20)",
        "ALTER TABLE bands ALTER COLUMN band_name TYPE VARCHAR(200)",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS band_code VARCHAR(20)",
        "ALTER TABLE employees ADD COLUMN IF NOT EXISTS band_name VARCHAR(80)",
        "ALTER TABLE employees ALTER COLUMN band_name TYPE VARCHAR(200)",
        "ALTER TABLE performance_diaries ADD COLUMN IF NOT EXISTS final_review_open BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE performance_diaries ADD COLUMN IF NOT EXISTS overall_performance_rating SMALLINT",
        "ALTER TABLE performance_diaries ADD COLUMN IF NOT EXISTS overall_performance_comments TEXT",
        "ALTER TABLE employee_credentials ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE employee_credentials ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP",
        "ALTER TABLE performance_diaries ALTER COLUMN kra_status SET DEFAULT 'draft'",
        "ALTER TABLE performance_diaries ALTER COLUMN self_status SET DEFAULT 'not_open'",
        "ALTER TABLE performance_diaries ALTER COLUMN mgr_status SET DEFAULT 'pending'",
        "ALTER TABLE performance_diaries ALTER COLUMN final_status SET DEFAULT 'pending'",
        "ALTER TABLE performance_diaries ALTER COLUMN kra_status SET NOT NULL",
        "ALTER TABLE performance_diaries ALTER COLUMN self_status SET NOT NULL",
        "ALTER TABLE performance_diaries ALTER COLUMN mgr_status SET NOT NULL",
        "ALTER TABLE performance_diaries ALTER COLUMN final_status SET NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_employees_manager_active ON employees (manager_id, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_employees_approver_active ON employees (approver_id, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_employees_role_active ON employees (role, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_performance_cycles_status_created ON performance_cycles (status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_performance_diaries_employee_created ON performance_diaries (employee_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_performance_diaries_manager_cycle ON performance_diaries (manager_id, cycle_id)",
        "CREATE INDEX IF NOT EXISTS ix_performance_diaries_approver_cycle ON performance_diaries (approver_id, cycle_id)",
        "CREATE INDEX IF NOT EXISTS ix_performance_diaries_cycle_status ON performance_diaries (cycle_id, kra_status, self_status, mgr_status, final_status)",
        "CREATE INDEX IF NOT EXISTS ix_diary_kpis_diary_kra_id ON diary_kpis (diary_kra_id)",
        "CREATE INDEX IF NOT EXISTS ix_approval_actions_diary_stage ON approval_actions (diary_id, stage)",
        "CREATE INDEX IF NOT EXISTS ix_approval_actions_actor_actioned ON approval_actions (actor_id, actioned_at)",
        "CREATE INDEX IF NOT EXISTS ix_grievances_diary_status ON grievances (diary_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_grievances_raised_status ON grievances (raised_by, status)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_recipient_created ON notifications (recipient_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_recipient_read ON notifications (recipient_id, is_read)",
        "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_employee_credential_id ON password_reset_tokens (employee_credential_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_password_reset_tokens_token_hash ON password_reset_tokens (token_hash)",
    ]
    for statement in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(statement))
        except Exception as exc:
            print(f"Schema sync statement skipped: {exc}")

def band_reference_data():
    rows = [
        ("B 1.1", "Intern/Associate"),
        ("B 1.2", "Associate Consultant"),
        ("B 1.3", "Consultant"),
        ("B 2.1", "Senior Consultant"),
        ("B 2.2", "Lead Consultant"),
        ("B 3.1", "Principal Consultant / Associate Manager"),
        ("B 3.2", "Technology Evangelist / Program Manager / Delivery Manager"),
        ("B 4.1", "Senior Technology Evangelist / Senior Program Manager / Senior Delivery Manager"),
        ("B 4.2", "Principal Technology Evangelist / Principal Program Manager / Principal Delivery Manager"),
        ("B 5.1", "Group Technology Evangelist / Group Program Manager / Group Delivery Manager"),
        ("B 5.2", "Chief Technology Evangelist / Chief Program Manager / Chief Delivery Manager"),
        ("B 6.1", "Associate Vice President"),
        ("B 6.2", "Vice President"),
        ("B 6.3", "Senior Vice President"),
    ]
    rows += [
        ("D 1.1", "Intern/Associate"), ("D 1.2", "Associate Technical Trainer"),
        ("D 2.1", "Technical Trainer"), ("D 2.2", "Senior Technical Trainer"),
        ("D 3.1", "Lead Technical Trainer"), ("D 3.2", "Principal Technical Trainer"),
        ("D 4.1", "Associate Manager"), ("D 4.2", "Manager"),
        ("D 5.1", "Senior Manager"), ("D 5.2", "Group Manager"),
        ("D 6.1", "Associate Vice President"), ("D 6.2", "Vice President"), ("D 6.3", "Senior Vice President"),
    ]
    rows += [
        ("S 1.1", "Intern/Associate"), ("S 1.2", "Executive"),
        ("S 1.3", "Senior Executive"), ("S 2.1", "Lead"),
        ("S 2.2", "Manager"), ("S 3.1", "Customer Success Manager"),
        ("S 3.2", "Customer Success Manager"), ("S 4.1", "AVP"), ("S 4.2", "AVP"),
        ("S 5.1", "VP"), ("S 5.2", "VP"), ("S 6.1", "Senior Vice President"),
        ("S 6.2", "Senior Vice President"), ("S 6.3", "Senior Vice President"),
    ]
    rows += [
        ("E 1.1", "Intern/Associate"), ("E 1.2", "Executive"),
        ("E 1.3", "Senior Executive"), ("E 2.1", "Specialist"),
        ("E 2.2", "Associate Lead"), ("E 3.1", "Lead"),
        ("E 3.2", "Associate Manager"), ("E 4.1", "Manager"),
        ("E 4.2", "Senior Manager"), ("E 5.1", "Group Manager"),
        ("E 5.2", "Function Head"), ("E 6.1", "Associate Vice President"),
        ("E 6.2", "Vice President"), ("E 6.3", "Senior Vice President"),
    ]
    return [
        {"band_code": code, "band_name": band_name}
        for code, band_name in rows
    ]

def sync_band_reference_data(db):
    existing = {band.band_code: band for band in db.query(Band).all()}
    for row in band_reference_data():
        band = existing.get(row["band_code"])
        if not band:
            band = Band(id=uuid.uuid4(), band_code=row["band_code"])
            db.add(band)
        band.band_name = row["band_name"]
        band.is_active = True
    db.flush()

    refreshed = {band.band_code: band for band in db.query(Band).all()}
    legacy_aliases = {
        "L1": "B 1.1",
        "L2": "B 1.2",
        "L3": "B 1.3",
        "L4": "B 2.1",
        "L5": "B 5.2",
        "L6": "B 6.3",
        "B 3.1.1": "B 3.1",
        "B 3.1.2": "B 3.1",
        "B 3.2.1": "B 3.2",
        "B 3.2.2": "B 3.2",
        "B 4.1.1": "B 4.1",
        "B 4.1.2": "B 4.1",
        "B 4.2.1": "B 4.2",
        "B 4.2.2": "B 4.2",
        "B 5.1.1": "B 5.1",
        "B 5.1.2": "B 5.1",
        "B 5.2.1": "B 5.2",
        "B 5.2.2": "B 5.2",
    }
    for old_code, new_code in legacy_aliases.items():
        old_band = refreshed.get(old_code)
        new_band = refreshed.get(new_code)
        if not old_band or not new_band:
            continue
        db.query(Employee).filter(Employee.band_id == old_band.id).update({Employee.band_id: new_band.id}, synchronize_session=False)
        db.query(KRAMaster).filter(KRAMaster.band_id == old_band.id).update({KRAMaster.band_id: new_band.id}, synchronize_session=False)
        old_band.is_active = False
    db.commit()

def ensure_admin_credential(db):
    if db.query(AdminCredential).filter(AdminCredential.username == "Admin").first():
        return

    band_id = None
    admin_band = db.query(Band).filter(Band.band_code == "S 6.3", Band.is_active == True).first()
    if admin_band:
        band_id = admin_band.id

    admin_emp = db.query(Employee).filter(Employee.employee_code == "ADM001").first()
    if not admin_emp:
        admin_emp = Employee(
            id=uuid.uuid4(),
            employee_code="ADM001",
            full_name="HR Admin",
            email="admin@nss.com",
            band_id=band_id,
            band_code="S 6.3" if band_id else None,
            band_name="Senior Vice President" if band_id else None,
            role=RoleEnum.admin,
        )
        db.add(admin_emp)
        db.flush()
    else:
        admin_emp.role = RoleEnum.admin
        if not admin_emp.band_id and band_id:
            admin_emp.band_id = band_id
            admin_emp.band_code = "S 6.3"
            admin_emp.band_name = "Senior Vice President"

    db.add(AdminCredential(
        id=uuid.uuid4(),
        username="Admin",
        password_hash=_bcrypt.hashpw("Admin@123".encode(), _bcrypt.gensalt()).decode(),
        employee_id=admin_emp.id,
    ))
    db.commit()


def ensure_employee_credentials(db):
    existing_employee_ids = {
        str(row[0])
        for row in db.query(EmployeeCredential.employee_id).all()
    }
    employees = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.role != RoleEnum.admin,
    ).all()
    created = 0
    for employee in employees:
        employee_id = str(employee.id)
        if employee_id in existing_employee_ids:
            continue
        existing_employee_ids.add(employee_id)
        db.add(EmployeeCredential(
            id=uuid.uuid4(),
            employee_id=employee.id,
            password_hash=_bcrypt.hashpw(DEFAULT_EMPLOYEE_PASSWORD.encode(), _bcrypt.gensalt()).decode(),
        ))
        created += 1
    if created:
        db.commit()


def seed_data(db):
    def uid():
        return uuid.uuid4()
    bands = [Band(id=uid(), **row) for row in band_reference_data()]
    for b in bands: db.add(b)
    db.flush()

    band_map = {b.band_code: b.id for b in bands}

    kra_data = {
        "L1": [
            ("KRA-L1-01", "Data Quality & Accuracy", "Maintain high data quality standards", [
                ("KPI-L1-01-1", "Data Accuracy Index", "Percentage of accurate data records"),
                ("KPI-L1-01-2", "Error Rate", "Number of data errors per 1000 records"),
            ]),
            ("KRA-L1-02", "Process Adherence", "Follow defined processes and SOPs", [
                ("KPI-L1-02-1", "SOP Compliance Score", "Adherence to standard operating procedures"),
                ("KPI-L1-02-2", "Task Completion Rate", "Percentage of tasks completed on time"),
            ]),
        ],
    }

    kra_objs = {}
    for band_code, kras in kra_data.items():
        bid = band_map.get(band_code)
        if not bid: continue
        for kra_code, kra_name, kra_desc, kpis in kras:
            kra = KRAMaster(id=uid(), band_id=bid, kra_code=kra_code, kra_name=kra_name, kra_description=kra_desc)
            db.add(kra)
            db.flush()
            kra_objs[kra_code] = kra.id
            for kpi_code, kpi_name, kpi_desc in kpis:
                kpi = KPIMaster(id=uid(), kra_master_id=kra.id, kpi_code=kpi_code, kpi_name=kpi_name, kpi_description=kpi_desc)
                db.add(kpi)

    deep_id = uid()
    shailesh_id = uid()
    rohit_id = uid()
    bhupesh_id = uid()
    sonal_id = uid()
    arsalan_id = uid()

    deep = Employee(id=deep_id, employee_code="EMP007", full_name="Deep Saraf", email="deep@nss.com",
                    band_id=band_map["S 5.1"], role=RoleEnum.approver, manager_id=None, approver_id=None)
    db.add(deep)
    db.flush()

    shailesh = Employee(id=shailesh_id, employee_code="EMP001", full_name="Shailesh Wadhankar", email="shailesh@nss.com",
                        band_id=band_map["S 5.1"], role=RoleEnum.approver, manager_id=deep_id, approver_id=None)
    db.add(shailesh)
    db.flush()

    rohit = Employee(id=rohit_id, employee_code="EMP006", full_name="Rohit Khandelwal", email="rohit@nss.com",
                     band_id=band_map["S 5.1"], role=RoleEnum.approver, manager_id=shailesh_id, approver_id=deep_id)
    db.add(rohit)
    db.flush()

    bhupesh = Employee(id=bhupesh_id, employee_code="EMP008", full_name="Bhupesh Sharma", email="bhupesh@nss.com",
                       band_id=band_map["S 3.1"], role=RoleEnum.approver, manager_id=rohit_id, approver_id=shailesh_id)
    db.add(bhupesh)
    db.flush()

    sonal = Employee(id=sonal_id, employee_code="EMP002", full_name="Sonal Tanna", email="sonal@nss.com",
                     band_id=band_map["B 3.1"], role=RoleEnum.manager, manager_id=bhupesh_id, approver_id=rohit_id)
    db.add(sonal)
    db.flush()

    arsalan = Employee(id=arsalan_id, employee_code="EMP009", full_name="Arsalan Ali", email="arsalan@nss.com",
                       band_id=band_map["B 2.2"], role=RoleEnum.manager, manager_id=rohit_id, approver_id=shailesh_id)
    db.add(arsalan)
    db.flush()

    reportees = [
        Employee(id=uid(), employee_code="EMP003", full_name="Prateek Kumar", email="prateek@nss.com",
                 band_id=band_map["B 1.3"], role=RoleEnum.reportee, manager_id=sonal_id, approver_id=rohit_id),
        Employee(id=uid(), employee_code="EMP004", full_name="Himaja Pendyala", email="hpendyala@nicesoftwaresolutions.com",
                 band_id=band_map["B 3.1"], role=RoleEnum.reportee, manager_id=sonal_id, approver_id=rohit_id),
        Employee(id=uid(), employee_code="EMP005", full_name="Mehul Rao", email="mehul@nss.com",
                 band_id=band_map["B 1.2"], role=RoleEnum.reportee, manager_id=arsalan_id, approver_id=shailesh_id),
    ]
    for r in reportees: db.add(r)

    admin_emp_id = uid()
    admin_emp = Employee(id=admin_emp_id, employee_code="ADM001", full_name="HR Admin", email="admin@nss.com",
                         band_id=band_map["S 6.3"], role=RoleEnum.admin)
    db.add(admin_emp)
    db.flush()

    admin_cred = AdminCredential(
        id=uid(), username="Admin",
        password_hash=_bcrypt.hashpw("Admin@123".encode(), _bcrypt.gensalt()).decode(),
        employee_id=admin_emp_id
    )
    db.add(admin_cred)
    db.commit()
    print("Seed data created successfully")
