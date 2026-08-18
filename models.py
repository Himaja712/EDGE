from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, Numeric, SmallInteger, ForeignKey, Enum as SAEnum, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()

def gen_uuid():
    return uuid.uuid4()    

class RoleEnum(str, enum.Enum):
    reportee = "reportee"
    manager = "manager"
    approver = "approver"
    admin = "admin"

class CyclePeriod(str, enum.Enum):
    H1_MAR = "H1_MAR"
    H2_SEP = "H2_SEP"

class CycleStatus(str, enum.Enum):
    draft = "draft"
    step1 = "step1"
    step2 = "step2"
    closed = "closed"

class DiaryKRAStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    sent_back = "sent_back"
    baselined = "baselined"

class SelfStatus(str, enum.Enum):
    not_open = "not_open"
    open = "open"
    submitted = "submitted"
    auto_submitted = "auto_submitted"

class MgrStatus(str, enum.Enum):
    pending = "pending"
    submitted = "submitted"
    sent_back = "sent_back"
    baselined = "baselined"

class FinalStatus(str, enum.Enum):
    pending = "pending"
    baselined = "baselined"
    closed = "closed"

class ActionType(str, enum.Enum):
    submit = "submit"
    approve = "approve"
    send_back = "send_back"
    baseline = "baseline"

class ActionStage(str, enum.Enum):
    kra = "kra"
    self_rating = "self_rating"
    mgr_rating = "mgr_rating"
    final = "final"

class GrievanceStatus(str, enum.Enum):
    open = "open"
    l1_review = "l1_review"
    l2_review = "l2_review"
    l3_review = "l3_review"
    resolved = "resolved"
    closed = "closed"

class NotifChannel(str, enum.Enum):
    in_app = "in_app"
    email = "email"
    both = "both"


class Band(Base):
    __tablename__ = "bands"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    band_code = Column(String(20), unique=True, nullable=False)
    band_name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    employees = relationship("Employee", back_populates="band")
    kra_masters = relationship("KRAMaster", back_populates="band")


class Employee(Base):
    __tablename__ = "employees"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_code = Column(String(20), unique=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    band_code = Column(String(20), nullable=True)
    band_name = Column(String(200), nullable=True)
    # band_id = Column(String, ForeignKey("bands.id"))
    # manager_id = Column(String, ForeignKey("employees.id"), nullable=True)
    # approver_id = Column(String, ForeignKey("employees.id"), nullable=True)
    role = Column(SAEnum(RoleEnum), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # band = relationship("Band", back_populates="employees")
    # manager = relationship("Employee", foreign_keys=[manager_id], remote_side="Employee.id")
    # approver = relationship("Employee", foreign_keys=[approver_id], remote_side="Employee.id")
    band_id = Column(UUID(as_uuid=True), ForeignKey("bands.id"))
    manager_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    approver_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    band = relationship("Band", back_populates="employees")

    manager = relationship(
        "Employee",
        foreign_keys=[manager_id],
        remote_side=[id]
    )

    approver = relationship(
        "Employee",
        foreign_keys=[approver_id],
        remote_side=[id]
    )
    __table_args__ = (
        Index("ix_employees_manager_active", "manager_id", "is_active"),
        Index("ix_employees_approver_active", "approver_id", "is_active"),
        Index("ix_employees_role_active", "role", "is_active"),
    )


class AdminCredential(Base):
    __tablename__ = "admin_credentials"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    # employee_id = Column(String, ForeignKey("employees.id"))
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmployeeCredential(Base):
    __tablename__ = "employee_credentials"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    must_change_password = Column(Boolean, default=True, nullable=False)
    password_changed_at = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_credential_id = Column(UUID(as_uuid=True), ForeignKey("employee_credentials.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    employee_credential = relationship("EmployeeCredential")


class KRAMaster(Base):
    __tablename__ = "kra_master"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # band_id = Column(String, ForeignKey("bands.id"), nullable=False)
    band_id = Column(UUID(as_uuid=True), ForeignKey("bands.id"), nullable=True)
    kra_code = Column(String(20), nullable=False)
    kra_name = Column(String(200), nullable=False)
    kra_description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    band = relationship("Band", back_populates="kra_masters")
    kpi_masters = relationship("KPIMaster", back_populates="kra_master")
    is_mandatory = Column(Boolean, default=False)
    is_org_mandatory = Column(Boolean, default=False)


class KPIMaster(Base):
    __tablename__ = "kpi_master"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # kra_master_id = Column(String, ForeignKey("kra_master.id"), nullable=False)
    kra_master_id = Column(UUID(as_uuid=True), ForeignKey("kra_master.id"), nullable=False)
    kpi_code = Column(String(20), nullable=False)
    kpi_name = Column(String(200), nullable=False)
    kpi_description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    kra_master = relationship("KRAMaster", back_populates="kpi_masters")


class PerformanceCycle(Base):
    __tablename__ = "performance_cycles"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_name = Column(String(100), nullable=False)
    financial_year = Column(String(10), nullable=False)
    period = Column(SAEnum(CyclePeriod), nullable=False)
    step1_open_date = Column(DateTime, nullable=False)
    step1_kra_deadline = Column(DateTime, nullable=False)
    step1_approval_date = Column(DateTime, nullable=False)
    step2_open_date = Column(DateTime, nullable=True)
    step2_self_deadline = Column(DateTime, nullable=True)
    step2_mgr_deadline = Column(DateTime, nullable=True)
    step2_approval_date = Column(DateTime, nullable=True)
    status = Column(SAEnum(CycleStatus), default=CycleStatus.draft)
    # created_by = Column(String, ForeignKey("employees.id"))
    created_by = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    diaries = relationship("PerformanceDiary", back_populates="cycle")
    __table_args__ = (
        Index("ix_performance_cycles_status_created", "status", "created_at"),
    )


class PerformanceDiary(Base):
    __tablename__ = "performance_diaries"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # cycle_id = Column(String, ForeignKey("performance_cycles.id"), nullable=False)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("performance_cycles.id"), nullable=False)
    # employee_id = Column(String, ForeignKey("employees.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    # manager_id = Column(String, ForeignKey("employees.id"), nullable=False)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    # approver_id = Column(String, ForeignKey("employees.id"), nullable=False)
    approver_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    kra_status = Column(SAEnum(DiaryKRAStatus), nullable=False, default=DiaryKRAStatus.draft, server_default=DiaryKRAStatus.draft.value)
    kra_sendback_count = Column(SmallInteger, default=0)
    kra_baselined_at = Column(DateTime, nullable=True)
    self_status = Column(SAEnum(SelfStatus), nullable=False, default=SelfStatus.not_open, server_default=SelfStatus.not_open.value)
    self_submitted_at = Column(DateTime, nullable=True)
    mgr_status = Column(SAEnum(MgrStatus), nullable=False, default=MgrStatus.pending, server_default=MgrStatus.pending.value)
    mgr_sendback_count = Column(SmallInteger, default=0)
    mgr_submitted_at = Column(DateTime, nullable=True)
    final_status = Column(SAEnum(FinalStatus), nullable=False, default=FinalStatus.pending, server_default=FinalStatus.pending.value)
    final_review_open = Column(Boolean, nullable=False, default=False, server_default="false")
    overall_performance_rating = Column(SmallInteger, nullable=True)
    overall_performance_comments = Column(Text, nullable=True)
    final_baselined_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("cycle_id", "employee_id"),
        Index("ix_performance_diaries_employee_created", "employee_id", "created_at"),
        Index("ix_performance_diaries_manager_cycle", "manager_id", "cycle_id"),
        Index("ix_performance_diaries_approver_cycle", "approver_id", "cycle_id"),
        Index("ix_performance_diaries_cycle_status", "cycle_id", "kra_status", "self_status", "mgr_status", "final_status"),
    )
    cycle = relationship("PerformanceCycle", back_populates="diaries")
    kras = relationship("DiaryKRA", back_populates="diary")
    grievances = relationship("Grievance", back_populates="diary")


class DiaryKRA(Base):
    __tablename__ = "diary_kras"
    # id = Colum    n(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # diary_id = Column(String, ForeignKey("performance_diaries.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("performance_diaries.id"), nullable=False, index=True)
    # kra_master_id = Column(String, ForeignKey("kra_master.id"), nullable=False)
    kra_master_id = Column(UUID(as_uuid=True), ForeignKey("kra_master.id"), nullable=True)
    custom_kra_name = Column(String(200), nullable=True)
    custom_kra_description = Column(Text, nullable=True)
    weightage_pct = Column(Numeric(5, 2), nullable=False)
    self_rating = Column(SmallInteger, nullable=True)
    self_comments = Column(Text, nullable=True)
    mgr_rating = Column(SmallInteger, nullable=True)
    mgr_comments = Column(Text, nullable=True)
    sort_order = Column(SmallInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    diary = relationship("PerformanceDiary", back_populates="kras")
    kra_master = relationship("KRAMaster")
    kpis = relationship("DiaryKPI", back_populates="diary_kra")


class DiaryKPI(Base):
    __tablename__ = "diary_kpis"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # diary_kra_id = Column(String, ForeignKey("diary_kras.id"), nullable=False)
    diary_kra_id = Column(UUID(as_uuid=True), ForeignKey("diary_kras.id"), nullable=False, index=True)
    # kpi_master_id = Column(String, ForeignKey("kpi_master.id"), nullable=False)
    kpi_master_id = Column(UUID(as_uuid=True), ForeignKey("kpi_master.id"), nullable=True)
    custom_kpi_name = Column(String(200), nullable=True)
    measurement_comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    diary_kra = relationship("DiaryKRA", back_populates="kpis")
    kpi_master = relationship("KPIMaster")


class ApprovalAction(Base):
    __tablename__ = "approval_actions"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # diary_id = Column(String, ForeignKey("performance_diaries.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("performance_diaries.id"), nullable=False)
    # actor_id = Column(String, ForeignKey("employees.id"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    action_type = Column(SAEnum(ActionType), nullable=False)
    stage = Column(SAEnum(ActionStage), nullable=False)
    comment = Column(Text)
    sendback_seq = Column(SmallInteger, nullable=True)
    actioned_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_approval_actions_diary_stage", "diary_id", "stage"),
        Index("ix_approval_actions_actor_actioned", "actor_id", "actioned_at"),
    )


class Grievance(Base):
    __tablename__ = "grievances"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # diary_id = Column(String, ForeignKey("performance_diaries.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("performance_diaries.id"), nullable=False, index=True)
    # diary_kra_id = Column(String, ForeignKey("diary_kras.id"), nullable=True)
    diary_kra_id = Column(UUID(as_uuid=True), ForeignKey("diary_kras.id"), nullable=True)
    # raised_by = Column(String, ForeignKey("employees.id"), nullable=False)
    raised_by = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True)
    grievance_type = Column(String(20), default="kra")  # kra | overall
    description = Column(Text, nullable=False)
    status = Column(SAEnum(GrievanceStatus), default=GrievanceStatus.open)
    current_level = Column(SmallInteger, default=1)
    l1_response = Column(Text, nullable=True)
    l1_responded_at = Column(DateTime, nullable=True)
    l2_response = Column(Text, nullable=True)
    l2_responded_at = Column(DateTime, nullable=True)
    l3_response = Column(Text, nullable=True)
    l3_responded_at = Column(DateTime, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)
    raised_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    diary = relationship("PerformanceDiary", back_populates="grievances")
    raised_by_user = relationship("Employee", foreign_keys=[raised_by])
    __table_args__ = (
        Index("ix_grievances_diary_status", "diary_id", "status"),
        Index("ix_grievances_raised_status", "raised_by", "status"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # recipient_id = Column(String, ForeignKey("employees.id"), nullable=False)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True)
    # diary_id = Column(String, ForeignKey("performance_diaries.id"), nullable=True)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("performance_diaries.id"), nullable=True, index=True)
    event_type = Column(String(60), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    channel = Column(SAEnum(NotifChannel), default=NotifChannel.both)
    is_read = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
        Index("ix_notifications_recipient_read", "recipient_id", "is_read"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    # id = Column(String, primary_key=True, default=gen_uuid)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)   
    # actor_id = Column(String, ForeignKey("employees.id"))
    actor_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"))
    entity_type = Column(String(40), nullable=False)
    # entity_id = Column(String, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(60), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
