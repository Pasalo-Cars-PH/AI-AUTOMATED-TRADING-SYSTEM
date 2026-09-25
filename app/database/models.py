from sqlalchemy import Column, Integer, String, Float, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

Base = declarative_base()

class ExecutionRecord(Base):
    __tablename__ = "execution_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String, index=True)
    symbol = Column(String)
    direction = Column(String)
    volume = Column(Float)
    entry_price = Column(Float)
    status = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

engine = create_engine("sqlite:///./quant_engine.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
