






from fastapi import FastAPI, Depends ,HTTPException, status
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt
from datetime import datetime, timedelta, timezone
from worker import process_heavy_video

import redis
import json

# الاتصال بمكتب الاستقبال (لاحظ إن اسم الهوست هو نفس اسم الخدمة بملف الدوكر كومبوز)
redis_client = redis.Redis(host='cache', port=6379, db=0, decode_responses=True)


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
    user = db.query(User).filter(User.username == form_data.username).first()
    
    # التعديل صار هون: صرنا نرفع Exception (401) بدل ما نرجع return عادية
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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

@app.get("/test-episodes/{series_id}")
def get_episodes(series_id: int):
    # 1. أولاً: نفحص مكتب الاستقبال (Redis)
    cached_data = redis_client.get(f"series_{series_id}_episodes")
    if cached_data:
        # إذا لقيناها بالذاكرة، بنرجعها فوراً مع علامة البرق
        return {"source": "Redis Cache ⚡", "data": json.loads(cached_data)}
    
    # 2. ثانياً: إذا مش موجودة، بنجيبها من المستودع (محاكاة لقاعدة البيانات)
    # هون المفروض يكون كود الاستعلام من الداتابيس تبعتك
    episodes_from_db = [
        {"episode_number": 1, "title": "الحلقة الأولى"},
        {"episode_number": 2, "title": "الحلقة الثانية"}
    ]
    
    # 3. ثالثاً: ننسخ البيانات ونحطها بمكتب الاستقبال للمرات الجاية (لمدة 60 ثانية)
    redis_client.setex(f"series_{series_id}_episodes", 60, json.dumps(episodes_from_db))
    
    # نرجع البيانات مع علامة الداتابيس
    return {"source": "Database 🗄️", "data": episodes_from_db}

@app.post("/episodes/")
def create_episode(episode: EpisodeCreate, db: Session = Depends(get_db),current_user:User=Depends(get_current_admin)):
    db_episode = Episode(title=episode.title, series_id=episode.series_id)
    db.add(db_episode)
    db.commit()
    db.refresh(db_episode)
    return db_episode

# ضفنا {series_id} في الرابط عشان نستلم الرقم
@app.get("/episodes/{series_id}")
def get_episodes_by_series(series_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # بنفلتر الحلقات بناءً على رقم المسلسل
    episodes = db.query(Episode).filter(Episode.series_id == series_id).all()
    return episodes


# API لعرض كل المسلسلات
@app.get("/series/")
def get_all_series(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Series).all()

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
# API لتعديل اسم مسلسل موجود (PUT)
@app.put("/series/{series_id}")
def update_series(series_id: int, new_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. نبحث عن المسلسل برقم الـ ID
    series = db.query(Series).filter(Series.id == series_id).first()
    
    # 2. إذا ما لقيناه بنرجع خطأ
    if not series:
        raise HTTPException(status_code=404, detail="المسلسل غير موجود")
    
    # 3. إذا لقيناه، بنعدل اسمه للاسم الجديد اللي وصلنا
    series.title = new_data.get("title", series.title)
    db.commit()
    db.refresh(series)
    return {"message": "تم التعديل بنجاح", "series": series}


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


# ضيف هذا المسار تحت
@app.post("/start-video-processing/{video_name}")
def start_processing(video_name: str):
    # السحر هون: كلمة delay بتخلي المهمة تروح للخلفية فوراً
    process_heavy_video.delay(video_name)
    
    # السيرفر بيرد فوراً بدون ما يستنى الـ 10 ثواني!
    return {"message": f"تم استلام فيديو '{video_name}' وجاري المعالجة في الخلفية!"}
