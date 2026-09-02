from fastapi import FastAPI, Depends ,HTTPException, status
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt
from datetime import datetime, timedelta, timezone


# إعداد قاعدة البيانات 
SQLALCHEMY_DATABASE_URL = "sqlite:///./media_production.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# بناء الجداول (المسلسلات والحلقات)
class Series(Base):
    __tablename__ = "series"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)

class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    series_id = Column(Integer, ForeignKey("series.id"))

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True) # الاسم لازم يكون غير مكرر
    hashed_password = Column(String) # رح نحفظ الباسورد مشفر مش نص عادي
    role = Column(String, default="user") # السطر الجديد: تحديد رتبة المستخدم
    
# إنشاء الجداول
Base.metadata.create_all(bind=engine)

# قوالب البيانات
class SeriesCreate(BaseModel):
    title: str

class EpisodeCreate(BaseModel):
    title: str
    series_id: int

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    
    # إعداد أداة التشفير باستخدام خوارزمية bcrypt القوية
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

# --- إعدادات بطاقة الـ JWT ---
SECRET_KEY = "qasem_super_secret_key" # هذا المفتاح السري تبعك
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 # البطاقة بتنتهي صلاحيتها بعد نص ساعة

# 1. دالة وظيفتها تقارن الباسورد اللي دخله اليوزر بالباسورد المشفر بالداتا بيس
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# 2. دالة وظيفتها تصدر بطاقة الـ JWT (الـ Token)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# تحديد المسار اللي بناخذ منه البطاقة (وهو مسار الـ login تبعنا)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# دالة الاتصال بقاعدة البيانات
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# دالة التفتيش: هاي الدالة بتوقف على باب الـ API وما بتخلي حد يفوت إلا ببطاقة صحيحة
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="غير مصرح لك بالعملية، يرجى تسجيل الدخول",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # فك تشفير البطاقة
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except:
        raise credentials_exception
        
    # التأكد إنه المستخدم لسا موجود بقاعدة البيانات
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# دالة تفتيش المدير (Admin)
def get_current_admin(current_user: User = Depends(get_current_user)):
    # 403 Forbidden: يعني معك بطاقة بس ما معك صلاحية لهاد المكان
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="عذراً، لا تملك صلاحيات الإدارة لإتمام هذه العملية!"
        )
    return current_user


app = FastAPI()






# الـ APIs


@app.post("/login/")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. البحث عن المستخدم في قاعدة البيانات
    user = db.query(User).filter(User.username == form_data.username).first()
    
    # 2. التأكد من وجود المستخدم ومن صحة الباسورد
    if not user or not verify_password(form_data.password, user.hashed_password):
        return {"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}
    
    # 3. إصدار الـ JWT Token إذا كانت المعلومات صحيحة
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# ضفنا شرط التفتيش (current_user) على الدالة
@app.post("/series/")
def create_series(series: SeriesCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    db_series = Series(title=series.title)
    db.add(db_series)
    db.commit()
    db.refresh(db_series)
    
    # رسالة ترحيبية بتثبت إن السيرفر عرف مين اللي ضاف المسلسل!
    return {"message": f"تمت الإضافة بواسطة: {current_user.username}", "series": db_series}


@app.post("/episodes/")
def create_episode(episode: EpisodeCreate, db: Session = Depends(get_db),current_user:User=Depends(get_current_admin)):
    db_episode = Episode(title=episode.title, series_id=episode.series_id)
    db.add(db_episode)
    db.commit()
    db.refresh(db_episode)
    return db_episode

@app.get("/episodes/")
def get_episodes(db: Session = Depends(get_db)):
    return db.query(Episode).all()

@app.post("/register/")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    # 1. نتأكد إذا اسم المستخدم موجود من قبل
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        return {"error": "اسم المستخدم موجود مسبقاً!"}
    
    # 2. تشفير كلمة المرور
    hashed_pw = get_password_hash(user.password)
    
    # 3. حفظ المستخدم في قاعدة البيانات
    new_user = User(username=user.username, hashed_password=hashed_pw, role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": "تم إنشاء الحساب بنجاح", "user_id": new_user.id}

# API لتعديل اسم مسلسل موجود (PUT)
@app.put("/series/{series_id}")
def update_series(series_id: int, series_update: SeriesCreate, db: Session = Depends(get_db),current_user: User =Depends(get_current_admin)):
    # 1. البحث عن المسلسل في قاعدة البيانات (زي جملة SELECT ... WHERE id =)
    db_series = db.query(Series).filter(Series.id == series_id).first()
    
    # 2. التأكد إذا كان المسلسل موجود أصلاً
    if not db_series:
        return {"error": "المسلسل غير موجود!"}
    
    # 3. تعديل البيانات وحفظها
    db_series.title = series_update.title
    db.commit()
    db.refresh(db_series)
    return {"message": "تم التعديل بنجاح", "updated_series": db_series}


# API لحذف مسلسل (DELETE)
@app.delete("/series/{series_id}")
def delete_series(series_id: int, db: Session = Depends(get_db),currnet_user:User=Depends(get_current_admin)):
    # 1. البحث عن المسلسل
    db_series = db.query(Series).filter(Series.id == series_id).first()
    
    # 2. التأكد من وجوده
    if not db_series:
        return {"error": "المسلسل غير موجود!"}
    
    # 3. الحذف من قاعدة البيانات (زي جملة DELETE FROM ... WHERE id =)
    db.delete(db_series)
    db.commit()
    return {"message": f"تم حذف المسلسل رقم {series_id} بنجاح"}