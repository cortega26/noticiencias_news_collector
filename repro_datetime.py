import os
import sys
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class TestSource(Base):
    __tablename__ = "test_sources"
    id = Column(Integer, primary_key=True)
    next_retry_at = Column(DateTime(timezone=True))

def run_repro():
    # 1. Setup SQLite
    if os.path.exists("test_repro.db"):
        os.remove("test_repro.db")
    
    engine = create_engine("sqlite:///test_repro.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 2. Insert UTC aware datetime
    now_utc = datetime.now(timezone.utc)
    print(f"Inserting: {now_utc} (tzinfo={now_utc.tzinfo})")
    
    src = TestSource(next_retry_at=now_utc)
    session.add(src)
    session.commit()

    # 3. Read back
    session.refresh(src)
    stored_dt = src.next_retry_at
    print(f"Read back: {stored_dt} (tzinfo={stored_dt.tzinfo})")

    # 4. Compare (WITH FIX LOGIC)
    try:
        now = datetime.now(timezone.utc)
        print(f"Comparing with: {now} (tzinfo={now.tzinfo})")
        
        # --- FIX APPLIED HERE ---
        if stored_dt and stored_dt.tzinfo is None:
            print("Fixing naive datetime...")
            stored_dt = stored_dt.replace(tzinfo=timezone.utc)
        # ------------------------

        if stored_dt > now:
            print("Future")
        else:
            print("Past")
        print("✅ Comparison successful (with fix)")
    except TypeError as e:
        print(f"❌ ERROR CAUGHT: {e}")

    session.close()

if __name__ == "__main__":
    run_repro()
