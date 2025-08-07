



from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import uvicorn
import os
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session


# --- FastAPI App Initialization ---
app = FastAPI()

# --- CORS Middleware (Allow all origins for development) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- MySQL (XAMPP) Database Setup ---
# Make sure XAMPP MySQL is running and you have created a database named 'factorydb'.
# Default XAMPP MySQL credentials: user 'root', password '' (empty string)
# You can change the database name, user, or password as needed.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:@localhost:3306/factorydb"  # XAMPP default: user=root, password=empty
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class SensorRecord(Base):
    __tablename__ = "sensor_data"
    id = Column(Integer, primary_key=True, index=True)
    temp = Column(Float)
    humid = Column(Float)
    vib = Column(Integer)  # 0: Normal, 1: Alert
    rpm = Column(Float)
    timestamp = Column(DateTime)

Base.metadata.create_all(bind=engine)


# --- Auth Setup ---
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user




def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UserCreate(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class SensorData(BaseModel):
    temp: float
    humid: float
    vib: int  # 0: Normal, 1: Alert
    rpm: float
    timestamp: datetime


# --- Latest Sensor Data Endpoint ---
from fastapi.responses import JSONResponse

@app.get("/latest")
def get_latest_sensor_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = db.query(SensorRecord).order_by(SensorRecord.timestamp.desc()).first()
    if not record:
        return JSONResponse(status_code=404, content={"detail": "No sensor data found"})
    return {
        "temp": record.temp,
        "humid": record.humid,
        "vib": "Alert" if record.vib == 1 else "Normal",
        "rpm": record.rpm,
        "time": record.timestamp.strftime("%H:%M:%S")
    }



# --- Auth Endpoints ---
@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_pw = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_pw)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "User registered"}

@app.post("/login", response_model=Token)
def login(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": db_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/log")
def log_sensor(data: SensorData, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = SensorRecord(
        temp=data.temp,
        humid=data.humid,
        vib=data.vib,
        rpm=data.rpm,
        timestamp=data.timestamp
    )
    db.add(record)
    db.commit()
    return {"status": "ok"}


@app.get("/predict")
def predict_breakdown(metric: str = "temp", threshold: Optional[float] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if metric not in ["temp", "humid", "vib", "rpm"]:
        return {"prediction": "Invalid metric"}
    records = db.query(SensorRecord).order_by(SensorRecord.timestamp).all()
    if len(records) < 2:
        return {"prediction": "Not enough data"}
    values = np.array([getattr(r, metric) for r in records])
    times = np.array([(r.timestamp - records[0].timestamp).total_seconds() for r in records])
    # Set default thresholds if not provided
    default_thresholds = {"temp": 26, "humid": 60, "vib": 1, "rpm": 1600}
    thres = threshold if threshold is not None else default_thresholds.get(metric, None)
    if thres is None:
        return {"prediction": "No threshold set for this metric"}
    coeffs = np.polyfit(times, values, 1)
    slope, intercept = coeffs
    if slope <= 0:
        return {"prediction": "No breakdown expected"}
    time_to_threshold = (thres - intercept) / slope
    eta = records[0].timestamp + timedelta(seconds=time_to_threshold)
    return {"prediction": f"Estimated {metric} breakdown at {eta.strftime('%Y-%m-%d %H:%M:%S')}"}

# --- Analytics Endpoints ---
@app.get("/analytics/summary")
def analytics_summary(metric: str = "temp", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if metric not in ["temp", "humid", "vib", "rpm"]:
        raise HTTPException(status_code=400, detail="Invalid metric")
    records = db.query(SensorRecord).all()
    if not records:
        return {"summary": "No data"}
    values = np.array([getattr(r, metric) for r in records])
    return {
        "average": float(np.mean(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "count": int(len(values))
    }

@app.get("/analytics/anomalies")
def analytics_anomalies(metric: str = "temp", threshold: Optional[float] = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if metric not in ["temp", "humid", "vib", "rpm"]:
        raise HTTPException(status_code=400, detail="Invalid metric")
    records = db.query(SensorRecord).all()
    if not records:
        return {"anomalies": []}
    values = np.array([getattr(r, metric) for r in records])
    if threshold is None:
        threshold = float(np.mean(values) + 2 * np.std(values))
    anomalies = [r for r in records if getattr(r, metric) > threshold]
    return {"anomalies": [{"id": r.id, "value": getattr(r, metric), "timestamp": r.timestamp} for r in anomalies]}



if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)