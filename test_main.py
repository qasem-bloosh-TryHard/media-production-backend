from fastapi.testclient import TestClient
from main import app  # بنستدعي السيرفر تبعك من ملف main.py

# إنشاء "عميل وهمي" بيقدر يبعث طلبات للسيرفر بدون ما نشغله فعلياً
client = TestClient(app)

# أي دالة فحص لازم تبدأ بكلمة test_
def test_get_episodes():
    # 1. العميل الوهمي بيبعث طلب GET لمسار الحلقات
    response = client.get("/test-episodes/5")
    
    # 2. الفحص الأول: هل السيرفر رد بنجاح (الكود 200)؟
    assert response.status_code == 200
    
    # 3. الفحص الثاني: هل البيانات اللي رجعت بتحتوي على كلمة "source"؟
    data = response.json()
    assert "source" in data