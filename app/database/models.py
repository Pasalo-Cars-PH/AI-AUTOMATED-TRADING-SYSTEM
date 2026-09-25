from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from app.config import settings

Base = declarative_base()

class SignalJournal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String, unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    symbol = Column(String)
    direction = Column(String)
    state = Column(String)
    score = Column(Integer)
    entry = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    risk_reward = Column(Float)
    position_size = Column(Float)
    strategy = Column(String)
    m5_confirmation = Column(Boolean)
    news_status = Column(String)
    data_quality = Column(String)
    correlation_status = Column(String)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
