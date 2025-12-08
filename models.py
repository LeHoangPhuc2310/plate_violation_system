# models.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# ==========================
# DATABASE CONFIG
# ==========================
DB_URI = "mysql+pymysql://root:123aZZ@localhost/plate_violation?charset=utf8mb4"

engine = create_engine(DB_URI, echo=False)
Session = sessionmaker(bind=engine)
Base = declarative_base()


def get_session():
    """Return một SQLAlchemy Session mới."""
    return Session()


# ==========================
# BẢNG THÔNG TIN CHỦ XE
# ==========================
class VehicleOwner(Base):
    __tablename__ = "vehicle_owner"

    plate = Column(String(20), primary_key=True)
    owner_name = Column(String(255))
    address = Column(String(255))
    phone = Column(String(50))


# ==========================
# BẢNG VI PHẠM
# ==========================
class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plate = Column(String(20))
    speed = Column(Float)
    speed_limit = Column(Integer)
    time = Column(DateTime, default=datetime.now)
    image = Column(String(255))
