"""
Byte Alliance | منصة صناعة المواهب التقنية  (النسخة 2)
المتطلبات:  pip install "python-telegram-bot>=20"

المسار:  1) تسجيل بالخاص  ->  2) اختبار ذكي (موافقة تلقائية)
         3) مشروع إثبات تقيّمه الإدارة  ->  4) الإدارة العليا + هوية + مرشد
"""
import asyncio
import html
import json
import logging
import math
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# مكتبة httpx تطبع رابط الطلب وفيه التوكن، لذلك نخفض مستواها
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ───────────────────────── الإعدادات (غيّرها هنا) ─────────────────────────

TOKEN = "8816217301:AAGPuMSjhljtROGDkIxkFrwmmXJqb_PlDy0"
ADMIN_ID = 7739164082
BOT_USERNAME = "ByteAlliance1_bot"

GROUP_1_ID = -1004460046354
GROUP_3_ID = -1003994257622
# المجموعة 2 و4: ارسل /id داخل كل مجموعة (وانت أدمن) وانسخ الرقم هنا.
# إذا بقيت 0 يستخدم البوت الرابط الثابت ويعطّل الروابط ذات المرة الواحدة وطرد المتسللين لها.
GROUP_2_ID = 0
GROUP_4_ID = 0

GROUP_1_LINK = "https://t.me/+CMgupxsAKBc0M2Zi"
GROUP_2_LINK = "https://t.me/+ln2ABEg8W6g0NWUy"
GROUP_3_LINK = "https://t.me/+tzl4_LmYKRY3Yjli"
FINAL_GROUP_4_LINK = "https://t.me/+S3UPBjZdghI1ZGEy"

MIN_AGE = 13                  # الحد الأدنى للعمر
QUIZ_LENGTH = 5               # عدد أسئلة كل اختبار (تُسحب عشوائياً من البنك)
PASS_RATIO = 0.7              # نسبة النجاح
QUESTION_SECONDS = 60         # وقت كل سؤال
MAX_ATTEMPTS = 3              # عدد المحاولات
COOLDOWN_SECONDS = 24 * 3600  # الانتظار بعد استنفاد المحاولات
INVITE_HOURS = 48             # صلاحية رابط الدعوة
MAX_LINK_REGEN = 3            # كم مرة يقدر العضو يطلب رابط جديد لكل مرحلة

if TOKEN.startswith("PUT_"):
    raise SystemExit("حط التوكن بمتغير TOKEN أعلى الملف.")

# ───────────────────────── قاعدة البيانات ─────────────────────────

DB_PATH = Path(__file__).with_name("byte_alliance_v2.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
db.execute(
    "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "ts INTEGER, actor INTEGER, action TEXT, target INTEGER, note TEXT)"
)
db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER)")
db.commit()


def new_user() -> dict:
    return {"stage": 1, "step": "none", "started_bot": False, "xp": 0}


def get_user(user_id: int) -> dict:
    row = db.execute("SELECT data FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            pass
    return new_user()


def save_user(user_id: int, data: dict) -> None:
    db.execute(
        "INSERT OR REPLACE INTO users (user_id, data) VALUES (?, ?)",
        (user_id, json.dumps(data, ensure_ascii=False)),
    )
    db.commit()


def delete_user(user_id: int) -> None:
    db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    db.commit()


def all_users() -> list:
    out = []
    for uid, data in db.execute("SELECT user_id, data FROM users"):
        try:
            out.append((uid, json.loads(data)))
        except (ValueError, TypeError):
            continue
    return out


def log_audit(actor: int, action: str, target: int = 0, note: str = "") -> None:
    db.execute(
        "INSERT INTO audit (ts, actor, action, target, note) VALUES (?, ?, ?, ?, ?)",
        (int(time.time()), actor, action, target, note),
    )
    db.commit()


def next_member_no() -> int:
    row = db.execute("SELECT value FROM meta WHERE key = 'member_no'").fetchone()
    n = (row[0] if row else 0) + 1
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('member_no', ?)", (n,))
    db.commit()
    return n


# ───────────────────────── ثوابت وأدوات ─────────────────────────

esc = html.escape

SPECIALTY_NAMES = {
    "dev": "تطوير الويب والبرمجيات",
    "cyber": "الأمن السيبراني",
    "design": "التصميم الرقمي UI/UX",
    "network": "شبكات الحاسوب",
    "lang": "اللغات والمهارات التقنية",
    "ai": "الذكاء الاصطناعي",
    "hardware": "صيانة الهاردوير",
    "support": "الدعم الفني وتقنية المعلومات",
}
SPEC_BUTTONS = [
    ("dev", "🔹 تطوير الويب (Software Dev)"),
    ("cyber", "🔹 الأمن السيبراني (Cybersecurity)"),
    ("design", "🔹 التصميم الرقمي (UI/UX Design)"),
    ("network", "🔹 شبكات الحاسوب (Networking)"),
    ("ai", "🔹 الذكاء الاصطناعي (AI)"),
    ("lang", "🔹 اللغات والمهارات التقنية (English)"),
    ("hardware", "🔹 صيانة الهاردوير (Hardware)"),
    ("support", "🔹 الدعم الفني (IT Support)"),
]
EDU_LEVELS = ["خريج ابتدائي", "خريج متوسطة", "خريج إعدادية", "طالب جامعي", "خريج بكالوريوس"]
STAGE_NAMES = {1: "التسجيل", 2: "الاختبار", 3: "مشروع الإثبات", 4: "الإدارة العليا"}
LEVELS = [(0, "مبتدئ"), (50, "متدرّب"), (150, "محترف"), (400, "خبير"), (800, "مرشد")]


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def last_part(data: str) -> str:
    return data.rsplit("_", 1)[-1]


def format_wait(seconds: int) -> str:
    hours, rem = divmod(max(seconds, 0), 3600)
    return f"{hours} ساعة و{rem // 60} دقيقة"


def attempts_wait(st: dict, key: str) -> int:
    now = time.time()
    recent = [t for t in st.get(key, []) if now - t < COOLDOWN_SECONDS]
    st[key] = recent
    if len(recent) >= MAX_ATTEMPTS:
        return int(COOLDOWN_SECONDS - (now - min(recent)))
    return 0


def level_info(xp: int):
    idx = 0
    for i, (threshold, _) in enumerate(LEVELS):
        if xp >= threshold:
            idx = i
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    return LEVELS[idx][1], nxt


def add_xp(st: dict, amount: int) -> None:
    st["xp"] = max(0, int(st.get("xp", 0)) + amount)


def member_code(st: dict) -> str:
    n = st.get("member_no")
    return f"BA-{n:04d}" if n else "لم تصدر بعد"


def spec_label(st: dict) -> str:
    return SPECIALTY_NAMES.get(st.get("specialty"), "-")


def display_name(st: dict, fallback: str = "عضو") -> str:
    return st.get("full_name") or fallback


async def alert(query, text: str) -> None:
    await query.answer(text, show_alert=True)


async def make_invite(bot, chat_id: int, fallback: str, label: str) -> str:
    """رابط دعوة لمرة واحدة. إذا فشل (أو ما عندنا آيدي المجموعة) نرجع الرابط الثابت."""
    if not chat_id:
        return fallback
    try:
        link = await bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=INVITE_HOURS),
            member_limit=1,
            name=label[:32],
        )
        return link.invite_link
    except Exception as e:  # noqa: BLE001
        logger.warning(f"invite link failed for {chat_id}: {e}")
        return fallback


def group_for_stage(stage: int):
    return {
        2: (GROUP_2_ID, GROUP_2_LINK),
        3: (GROUP_3_ID, GROUP_3_LINK),
        4: (GROUP_4_ID, FINAL_GROUP_4_LINK),
    }.get(stage)


def required_stage(chat_id: int):
    if GROUP_2_ID and chat_id == GROUP_2_ID:
        return 2
    if chat_id == GROUP_3_ID:
        return 3
    if GROUP_4_ID and chat_id == GROUP_4_ID:
        return 4
    return None


# بنك أسئلة المجموعة الثانية (اختبار التخصص)
QUESTIONS_G2 = {
    "dev": [
        ("ما هي لغة البرمجة الأساسية لتطوير الويب (Frontend)؟", ["Python", "HTML", "C++", "Java"], 1),
        ("ماذا تعني اختصار API في البرمجة؟", ["Application Programming Interface", "Advanced Program Integration", "Automated Process Interaction", "Application Process Integration"], 0),
        ("أي من التالي يُستخدم لإدارة وقواعد البيانات؟", ["RAM", "Database", "CPU", "GPU"], 1),
        ("ما هي أداة التحكم بالنسخ والإصدارات الأكثر شهرة؟", ["Git", "Docker", "Jenkins", "Webpack"], 0)
    ],
    "cyber": [
        ("ما هو الهجوم الذي يغرق الخادم بطلبات وهمية لحجبه؟", ["DDoS", "Phishing", "SQL Injection", "Man in the Middle"], 0),
        ("ماذا يقصد بمصطلح Phishing؟", ["التصيد الاحتيالي", "اختراق الشبكات", "تشفير البيانات", "حماية الجدران النارية"], 0),
        ("أي مما يلي يعتبر كلمة مرور قوية وآمنة؟", ["123456", "password", "P@ssw0rd!2026", "admin"], 2),
        ("ما فائدة جدار الحماية (Firewall) الأساسية؟", ["مراقبة وتصفية حركة المرور", "تسريع الإنترنت", "حذف الفيروسات تلقائياً", "تبريد المعالج"], 0)
    ],
    "design": [
        ("ما هو البرنامج الأساسي لتصميم واجهات المستخدم UI/UX؟", ["Figma", "Excel", "Notepad", "Word"], 0),
        ("ماذا تعني صيغة PNG للصور الرقمية؟", ["تنزيل سريع", "خلفية شفافة", "حجم كبير", "بدون ضغط"], 1),
        ("ما هو نظام الألوان المستخدم للطباعة والنشر؟", ["CMYK", "RGB", "HEX", "HSV"], 0),
        ("ما هي دلالة اللون الأزرق غالباً في التصاميم الاحترافية؟", ["الثقة والاحترافية", "الغضب والخطر", "الطاقة والحماس", "الطبيعة والهدوء"], 0)
    ],
    "network": [
        ("ما هو جهاز التوجيه الأساسي لربط الشبكات؟", ["Router", "Switch", "Hub", "Modem"], 0),
        ("ما هو البروتوكول المسؤول عن تحويل أسماء النطاقات إلى عناوين آيبي (DNS)؟", ["DNS", "FTP", "HTTP", "SMTP"], 0),
        ("ما هو عنوان الآيبي المحلي الافتراضي (Localhost)؟", ["127.0.0.1", "192.168.1.1", "10.0.0.1", "8.8.8.8"], 0),
        ("ما فائدة محول الشبكة (Switch)؟", ["ربط الأجهزة داخل نفس الشبكة المحلية", "توزيع الإنترنت الفضائي", "حماية من الفيروسات", "تخزين الملفات"], 0)
    ],
    "lang": [
        ("ما هو المرادف الصحيح لكلمة 'Successful' باللغة الإنجليزية؟", ["Failed", "Effective", "Useless", "Slow"], 1),
        ("اختر الجملة الصحيحة نحوياً وقواعدياً:", ["He goes to school.", "He go to school.", "He going to school.", "He gone to school."], 0),
        ("ما معنى كلمة 'Environment'؟", ["بيئة", "اقتصاد", "تكنولوجيا", "مستقبل"], 0),
        ("أي من التالي يُعتبر فعلاً مساعداً (Auxiliary Verb)؟", ["Can", "Car", "Apple", "Fast"], 0)
    ],
    "ai": [
        ("ما هو فرع الذكاء الاصطناعي الذي يتيح للأنظمة التعلم من البيانات؟", ["Machine Learning", "Hardware Engineering", "Cyber Security", "Graphic Design"], 0),
        ("من هي الشركة المطورة لنموذج ChatGPT؟", ["OpenAI", "Google", "Microsoft", "Meta"], 0),
        ("ماذا يقصد بمصطلح Generative AI؟", ["الذكاء الاصطناعي التوليدي", "الذكاء الثابت", "الذكاء الأساسي", "الذكاء المنطقي"], 0),
        ("أي من التالي يعتبر نموذج لغة كبير (LLM)؟", ["GPT-4", "Photoshop", "Windows", "Linux"], 0)
    ],
    "hardware": [
        ("ما هو الجزء الملقب بعقل الحاسوب ومعالج البيانات؟", ["CPU", "RAM", "GPU", "HDD"], 0),
        ("أي من التالي يُعد وحدة تخزين فائقة السرعة وثابتة (SSD)؟", ["SSD", "CD", "Floppy Disk", "Cassette"], 0),
        ("ما فائدة وحدة تزويد الطاقة (Power Supply)؟", ["توزيع الكهرباء لمكونات الحاسوب", "تخزين الملفات", "معالجة الرسومات", "تبريد المعالج"], 0),
        ("ما هو منفذ عرض الشاشة الرقمي الحديث؟", ["HDMI", "VGA", "PS/2", "COM"], 0)
    ],
    "support": [
        ("كيف تتعامل بمهنية مع عميل غاضب أو يواجه مشكلة؟", ["الاستماع بهدوء وحل مشكلته", "تجاهله", "إغلاق المكالمة", "الصراخ عليه"], 0),
        ("ما هي الخطوة الأولى لحل أي مشكلة فنية؟", ["تحديد المشكلة وفحصها بدقة", "فرمطة الجهاز فوراً", "شراء جهاز جديد", "ترك العمل"], 0),
        ("ماذا تعني صيانة الأجهزة (Maintenance)؟", ["الحفاظ على كفاءتها وإصلاح أعطالها", "بيعها مستعملة", "تغيير مكانها", "إخفاؤها"], 0),
        ("ما هي الأداة المستخدمة لقياس الفولتية والكهرباء؟", ["Multimeter", "Hammer", "Screwdriver", "Pliers"], 0)
    ]
}


# أسئلة إضافية لتكبير البنك (يُسحب منها عشوائياً بكل اختبار)
EXTRA_QUESTIONS_G2 = {
    "dev": [
        ("ما الفرق بين GET و POST في بروتوكول HTTP؟", ["GET لطلب البيانات وPOST لإرسالها", "GET للحذف وPOST للقراءة", "لا فرق بينهما", "GET للصور فقط"], 0),
        ("أي لغة تُستخدم لتنسيق وتصميم صفحات الويب؟", ["SQL", "CSS", "Bash", "Rust"], 1),
        ("ماذا يفعل الأمر git commit؟", ["يحذف المستودع", "يرفع الملفات للإنترنت مباشرة", "يحفظ لقطة من التغييرات في المستودع المحلي", "يثبّت Python"], 2),
        ("أي من التالي نظام قواعد بيانات علائقي؟", ["Figma", "Chrome", "PostgreSQL", "Photoshop"], 2),
    ],
    "cyber": [
        ("ما المقصود بالمصادقة الثنائية (2FA)؟", ["استخدام كلمتي مرور متشابهتين", "إضافة خطوة تحقق ثانية بعد كلمة المرور", "تشفير القرص بالكامل", "حذف الحساب مرتين"], 1),
        ("ما هو هجوم SQL Injection؟", ["إغراق الشبكة بالطلبات", "سرقة الجهاز فعلياً", "إدخال أوامر SQL خبيثة عبر حقول الإدخال", "تعطيل الكهرباء"], 2),
        ("ما الفرق بين التشفير (Encryption) والتجزئة (Hashing)؟", ["لا فرق بينهما", "التجزئة قابلة للعكس دائماً", "التشفير للصور فقط", "التشفير قابل للعكس بمفتاح والتجزئة باتجاه واحد"], 3),
        ("ما أفضل تصرف عند وصول رابط مشبوه برسالة؟", ["فتحه فوراً", "عدم فتحه والتحقق من مصدره", "إرساله للأصدقاء", "إدخال كلمة المرور فيه"], 1),
    ],
    "design": [
        ("ما المقصود بالتباين (Contrast) في التصميم؟", ["تكرار نفس اللون", "تصغير كل الخطوط", "الفرق بين العناصر لتسهيل القراءة والتمييز", "حذف الخلفية"], 2),
        ("ما هو الـ Wireframe؟", ["صورة نهائية للمنتج", "مخطط أولي لهيكل الواجهة قبل التصميم النهائي", "برنامج مونتاج", "لوحة ألوان"], 1),
        ("أي صيغة صور تناسب الرسوم المتجهة القابلة للتكبير بلا فقد جودة؟", ["BMP", "JPG", "SVG", "GIF"], 2),
        ("ما الهدف من نظام التصميم (Design System)؟", ["زيادة عدد الألوان عشوائياً", "توحيد المكونات والألوان والخطوط عبر المنتج", "تقليل عدد الشاشات", "حذف الأيقونات"], 1),
    ],
    "network": [
        ("كم عدد بتات عنوان IPv4؟", ["64", "128", "32", "16"], 2),
        ("ما وظيفة بروتوكول DHCP؟", ["تشفير الملفات", "تحويل الأسماء لعناوين", "منح عناوين IP تلقائياً للأجهزة", "نقل البريد"], 2),
        ("أي منفذ (Port) يستخدمه HTTPS افتراضياً؟", ["80", "443", "21", "25"], 1),
        ("ما الفرق الأساسي بين TCP وUDP؟", ["UDP أبطأ دائماً وأدق", "TCP موثوق ويضمن التسليم وUDP أسرع بلا ضمان", "لا فرق بينهما", "TCP للصوت فقط"], 1),
    ],
    "lang": [
        ("ما معنى كلمة 'Deadline'؟", ["بداية المشروع", "اجتماع", "الموعد النهائي", "مكافأة"], 2),
        ("اختر الجملة الصحيحة:", ["She have finished the report.", "She has finished the report.", "She finish the report yesterday.", "She finishing the report."], 1),
        ("ما معنى 'Documentation' في المجال التقني؟", ["الحذف", "الحماية", "الترجمة الآلية", "التوثيق والشرح المكتوب للنظام"], 3),
        ("ما معنى 'Feedback'؟", ["فيروس", "جهاز", "ملاحظات وتغذية راجعة", "لغة برمجة"], 2),
    ],
    "ai": [
        ("ما المقصود بـ Training Data؟", ["شاشة العرض", "البيانات التي يتعلم منها النموذج", "كلمة السر", "ملف الإعدادات"], 1),
        ("ما المقصود بـ Overfitting؟", ["سرعة التدريب العالية", "قلة الذاكرة", "حفظ النموذج لبيانات التدريب وضعف أدائه على بيانات جديدة", "كثرة الألوان"], 2),
        ("أي مكتبة بايثون شهيرة لبناء نماذج التعلم الآلي؟", ["Photoshop", "scikit-learn", "Excel", "Notepad"], 1),
        ("ما المقصود بالـ Prompt؟", ["جهاز تخزين", "نوع شبكة", "لغة برمجة", "التعليمة أو النص الذي يُعطى للنموذج"], 3),
    ],
    "hardware": [
        ("ما وظيفة المعجون الحراري؟", ["زيادة سرعة الإنترنت", "تحسين نقل الحرارة بين المعالج والمبرّد", "تنظيف الشاشة", "تخزين البيانات"], 1),
        ("أي مكوّن يخزّن البيانات مؤقتاً أثناء تشغيل الحاسوب؟", ["SSD", "PSU", "RAM", "BIOS"], 2),
        ("ما أول فحص عند عدم تشغيل الحاسوب إطلاقاً؟", ["فرمتة النظام", "استبدال اللوحة الأم", "شراء معالج جديد", "التأكد من توصيل الكهرباء وكابل الطاقة"], 3),
        ("ما وظيفة BIOS/UEFI؟", ["تصفح الإنترنت", "تشغيل وفحص العتاد وبدء تحميل النظام", "تحرير الصور", "حماية من الفيروسات فقط"], 1),
    ],
    "support": [
        ("ما الهدف من توثيق الحلول في قاعدة معرفة (Knowledge Base)؟", ["إخفاء المشاكل", "زيادة التذاكر", "إعادة استخدام الحلول وتسريع حل المشاكل المتكررة", "حذف الأخطاء"], 2),
        ("ما أولوية التذكرة التي توقف عمل قسم كامل؟", ["منخفضة", "تُهمل", "تؤجل شهراً", "عالية/عاجلة"], 3),
        ("ما أفضل أسلوب عند عدم معرفتك بالحل؟", ["تجاهل العميل", "التصعيد لمختص أو البحث ثم إبلاغ العميل بالوقت المتوقع", "التخمين بلا فحص", "إغلاق التذكرة"], 1),
        ("ما فائدة الاتصال عن بعد (Remote Desktop) في الدعم الفني؟", ["تسريع الإنترنت", "تبريد الجهاز", "حل المشكلة على جهاز المستخدم دون الحضور", "طباعة الملفات"], 2),
    ],
}
for _spec, _extra in EXTRA_QUESTIONS_G2.items():
    QUESTIONS_G2[_spec].extend(_extra)


WELCOME_RULES_TEXT = (
    "🦅 <b>أهلاً وسهلاً بك في الإدارة العليا | Byte Alliance</b>\n\n"
    "يسرّ إدارة تحالف Byte Alliance أن ترحب بك بين نخبة الأعضاء الذين أثبتوا جديتهم وكفاءتهم خلال مراحل الانضمام. "
    "وصولك إلى هذه المرحلة ليس صدفة، بل هو نتيجة التزامك وتميزك، ونأمل أن تكون شريكًا في بناء مستقبل تقني احترافي داخل التحالف.\n\n"
    "🪪 <b>الهوية الرسمية</b>\n"
    "سيتم إصدار هوية رقمية خاصة (Byte Alliance ID) لكل عضو يتم اعتماده في الإدارة العليا. "
    "وتُعد هذه الهوية إثباتًا رسميًا لعضويتك داخل التحالف، وتمنحك صفة عضو في الإدارة العليا، وقد تُستخدم مستقبلاً للوصول إلى المشاريع والفرق والفعاليات الخاصة بالتحالف.\n\n"
    "🦅 <b>قوانين الإدارة العليا | Byte Alliance</b>\n\n"
    "1. <b>السرية المطلقة:</b> يُمنع منعًا باتًا تسريب أي معلومة أو مشروع أو كود أو نقاش يخص الإدارة العليا. أي مخالفة تؤدي إلى الطرد النهائي.\n"
    "2. <b>الالتزام:</b> كل عضو مسؤول عن تنفيذ المهام الموكلة إليه ضمن الوقت المحدد، والتأخير دون عذر مقبول يُحسب مخالفة.\n"
    "3. <b>الاحترام:</b> يُمنع الإساءة أو السخرية أو إثارة المشاكل بين الأعضاء، ويجب التعامل باحترام واحترافية.\n"
    "4. <b>النشاط:</b> يجب على كل عضو التفاعل والمشاركة باستمرار. الغياب الطويل دون إشعار قد يؤدي إلى سحب العضوية.\n"
    "5. <b>منع إساءة استخدام المهارات:</b> يُمنع استخدام المعرفة أو الأدوات أو الأكواد التابعة للتحالف في أي أعمال غير قانونية أو تضر بالآخرين.\n"
    "6. <b>عدم مشاركة الروابط:</b> يُمنع إرسال روابط مجموعات أو قنوات أو إعلانات دون موافقة الإدارة.\n"
    "7. <b>المشاريع:</b> أي مشروع يبدأ داخل التحالف يُناقش داخل الإدارة فقط، ولا يجوز نشره خارجها إلا بإذن رسمي.\n"
    "8. <b>القرارات الإدارية:</b> قرارات الإدارة العليا نهائية، وأي اعتراض يكون بأسلوب محترم ومن خلال القنوات المخصصة.\n"
    "9. <b>الهوية:</b> يجب استخدام الاسم الحقيقي أو اسم ثابت معروف لدى الإدارة، ويُمنع انتحال الشخصيات أو استخدام بيانات مضللة.\n"
    "10. <b>العضوية:</b> الانضمام للإدارة العليا امتياز وليس حقًا، ويحق للإدارة إنهاء العضوية عند مخالفة القوانين أو الإضرار بمصلحة التحالف.\n"
    "11. <b>العقوبات:</b> تبدأ العقوبات بالتنبيه، ثم الإنذار، ثم تقييد الصلاحيات، وقد تصل إلى الطرد النهائي حسب نوع المخالفة.\n"
    "12. <b>القبول:</b> دخولك إلى الإدارة العليا يعني موافقتك الكاملة على جميع هذه القوانين والالتزام بها دون استثناء.\n\n"
    "🌟 نتمنى لك رحلة مليئة بالإنجازات والإبداع داخل Byte Alliance، ونسعى معًا لبناء مجتمع تقني احترافي قائم على التعاون والالتزام والابتكار."
)


# ───────────────────────── التسجيل بالخاص (المرحلة 1) ─────────────────────────


def spec_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"spec_{code}")] for code, label in SPEC_BUTTONS])


def edu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton(level, callback_data=f"edu_{i}")] for i, level in enumerate(EDU_LEVELS)])


async def prompt_step(message, st: dict):
    """يعيد سؤال الخطوة الحالية (للمتابعة من وين وقف العضو)."""
    step = st.get("step")
    if step == "wait_spec":
        await message.reply_text("🎯 اختر <b>تخصصك التقني</b>:", reply_markup=spec_keyboard(), parse_mode=ParseMode.HTML)
    elif step == "wait_name":
        await message.reply_text("📝 <b>السؤال 1 من 4:</b> اكتب <b>اسمك الثلاثي</b>:", parse_mode=ParseMode.HTML)
    elif step == "wait_age":
        await message.reply_text("📝 <b>السؤال 2 من 4:</b> اكتب <b>عمرك</b> بالأرقام:", parse_mode=ParseMode.HTML)
    elif step == "wait_edu":
        await message.reply_text("📝 <b>السؤال 3 من 4:</b> اختر <b>مرحلتك الدراسية</b>:", reply_markup=edu_keyboard(), parse_mode=ParseMode.HTML)
    elif step == "wait_location":
        await message.reply_text("📝 <b>السؤال 4 من 4:</b> اكتب <b>محافظتك / مكان إقامتك</b>:", parse_mode=ParseMode.HTML)


async def show_status(message, st: dict):
    stage, step = st.get("stage", 1), st.get("step", "none")
    if stage == 1:
        if step == "none":
            keyboard = [[InlineKeyboardButton("✅ أوافق وأبدأ التسجيل", callback_data="consent_yes")]]
            await message.reply_text(
                "🦅 <b>أهلاً بك في تحالف Byte Alliance!</b>\n\n"
                "قبل التسجيل: نجمع اسمك وعمرك ومرحلتك الدراسية ومحافظتك وتخصصك لغرض التسجيل وتقييم الانضمام فقط، "
                "ولا نشاركها مع أحد خارج الإدارة. تكدر تحذف بياناتك بأي وقت بأمر /delete_me.\n\n"
                f"الحد الأدنى للعمر: {MIN_AGE} سنة.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML,
            )
        elif step == "completed":
            await message.reply_text("⏳ طلبك قيد المراجعة من الإدارة. راح توصلك رسالة عند القرار.")
        elif step == "underage":
            await message.reply_text(f"عذراً، الحد الأدنى للانضمام هو {MIN_AGE} سنة. نتمنى نشوفك لاحقاً 🌱")
        else:
            await message.reply_text("📌 كمّل التسجيل من وين وقفت:")
            await prompt_step(message, st)
    elif stage == 2:
        await message.reply_text(
            "🧪 أنت بالمرحلة 2 (الاختبار). ادخل مختبر المواهب واضغط زر الاختبار هناك.\nإذا ضاع الرابط اكتب /link"
        )
    elif stage == 3:
        await message.reply_text("🌟 أنت بالمرحلة 3. قدّم مشروع الإثبات بأمر /project\nإذا ضاع الرابط اكتب /link")
    else:
        await message.reply_text("🪪 أنت عضو معتمد بالإدارة العليا. اكتب /me لبطاقتك.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    st = get_user(user.id)
    st["started_bot"] = True
    st["username"] = user.username or ""
    save_user(user.id, st)

    payload = context.args[0] if context.args else ""
    if payload == "project":
        await project_cmd(update, context)
        return
    await show_status(update.message, st)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    text = (
        "📚 <b>الأوامر:</b>\n"
        "/start - بدء التسجيل أو معرفة مرحلتك\n"
        "/me - بطاقتك ومستواك ونقاطك\n"
        "/project - تقديم مشروع الإثبات (المرحلة 3)\n"
        "/top - لوحة الشرف (مثال: /top dev)\n"
        "/link - رابط جديد لمجموعة مرحلتك\n"
        "/delete_me - حذف بياناتك"
    )
    if is_admin(update.effective_user.id):
        text += (
            "\n\n🛠 <b>للإدارة:</b>\n"
            "/pending - الطلبات المعلقة\n/stats - الإحصائيات\n"
            "/broadcast نص - رسالة لكل الأعضاء\n/addxp آيدي رقم - إضافة نقاط\n"
            "/setmentor آيدي - تعيين/إلغاء مرشد\n/note آيدي نص - رسالة لعضو\n"
            "/verify BA-0001 - تحقق من عضو\n/audit - آخر القرارات\n"
            "/id - آيدي المجموعة (داخل المجموعة)\n/setup - زر التسجيل بالمجموعة 1\n/quiz - زر الاختبار بالمجموعة 2"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_consent(query, user_id: int):
    st = get_user(user_id)
    if st.get("stage", 1) != 1 or st.get("step") != "none":
        await alert(query, "⚠️ هذه الخطوة غير متاحة الآن.")
        return
    await query.answer()
    st["consent"] = int(time.time())
    st["step"] = "wait_spec"
    save_user(user_id, st)
    await prompt_step(query.message, st)


async def handle_spec(query, user_id: int, data: str):
    code = data[len("spec_"):]
    st = get_user(user_id)
    if code not in SPECIALTY_NAMES or st.get("stage", 1) != 1 or st.get("step") not in ("wait_spec", "wait_name"):
        await alert(query, "⚠️ ما تكدر تغيّر التخصص بهذه المرحلة.")
        return
    await query.answer()
    st["specialty"] = code
    st["step"] = "wait_name"
    save_user(user_id, st)
    await query.message.reply_text(f"✅ التخصص: <b>{esc(SPECIALTY_NAMES[code])}</b>", parse_mode=ParseMode.HTML)
    await prompt_step(query.message, st)


async def handle_edu(query, user_id: int, data: str):
    try:
        level = EDU_LEVELS[int(data[len("edu_"):])]
    except (ValueError, IndexError):
        await query.answer()
        return
    st = get_user(user_id)
    if st.get("step") != "wait_edu":
        await alert(query, "⚠️ هذه الخطوة غير متاحة الآن.")
        return
    await query.answer()
    st["education"] = level
    st["step"] = "wait_location"
    save_user(user_id, st)
    await query.message.reply_text(f"🎓 المرحلة الدراسية: <b>{esc(level)}</b>", parse_mode=ParseMode.HTML)
    await prompt_step(query.message, st)


async def send_reg_request(bot, user_id: int, st: dict):
    keyboard = [[
        InlineKeyboardButton("✅ موافقة للمجموعة 2", callback_data=f"app_g2_{user_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"rej_reg_{user_id}"),
    ]]
    uname = f"@{esc(st['username'])}" if st.get("username") else "-"
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📋 <b>طلب انضمام جديد (المرحلة 1)</b>\n"
            f"الاسم: {esc(display_name(st))}\n"
            f"التخصص: {esc(spec_label(st))}\n"
            f"العمر: {st.get('age')}\n"
            f"المرحلة الدراسية: {esc(st.get('education', '-'))}\n"
            f"المحافظة: {esc(st.get('location', '-'))}\n"
            f"اليوزر: {uname}\n"
            f"الآيدي: <code>{user_id}</code>"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def send_project_request(bot, user_id: int, st: dict):
    prj = st["project"]
    keyboard = [
        [InlineKeyboardButton("✅ اعتماد للمرحلة 4", callback_data=f"prj_ok_{user_id}")],
        [
            InlineKeyboardButton("🔁 يحتاج تعديل", callback_data=f"prj_rev_{user_id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"prj_no_{user_id}"),
        ],
    ]
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🌟 <b>مشروع إثبات جديد (المرحلة 3)</b>\n"
            f"العضو: {esc(display_name(st))} ({esc(spec_label(st))})\n"
            f"العنوان: {esc(prj['title'])}\n"
            f"الرابط: {esc(prj['link'])}\n"
            f"الوصف: {esc(prj['desc'])}\n"
            f"الآيدي: <code>{user_id}</code>"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


# ───────────────────────── مشروع الإثبات (المرحلة 3) ─────────────────────────


async def project_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    st = get_user(user_id)
    if st.get("stage") != 3:
        await update.message.reply_text("⚠️ تقديم المشروع متاح فقط لمن اجتاز الاختبار (المرحلة 3).")
        return
    status = st.get("project", {}).get("status")
    if status == "pending":
        await update.message.reply_text("⏳ مشروعك قيد المراجعة من الإدارة.")
        return
    st["step"] = "proj_title"
    st["project_draft"] = {}
    save_user(user_id, st)
    await update.message.reply_text(
        "🌟 <b>مشروع الإثبات</b>\nقدّم عملاً حقيقياً يثبت موهبتك (GitHub، Figma، تقرير أمني، مخطط شبكة، نموذج AI...).\n\n"
        "<b>1 من 3:</b> اكتب <b>عنوان المشروع</b>:",
        parse_mode=ParseMode.HTML,
    )


async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or not update.effective_user:
        return
    user_id = update.effective_user.id
    text = msg.text.strip()
    st = get_user(user_id)
    step = st.get("step", "none")

    # ── مراحل التسجيل ──
    if st.get("stage", 1) == 1:
        if step == "wait_name":
            if not (3 <= len(text) <= 60):
                await msg.reply_text("⚠️ اكتب اسمك الثلاثي بشكل صحيح (3 إلى 60 حرف).")
                return
            st["full_name"] = text
            st["step"] = "wait_age"
            save_user(user_id, st)
            await prompt_step(msg, st)

        elif step == "wait_age":
            if not text.isdigit() or not (1 <= int(text) <= 99):
                await msg.reply_text("⚠️ اكتب العمر بالأرقام فقط.")
                return
            age = int(text)
            if age < MIN_AGE:
                st["step"] = "underage"
                save_user(user_id, st)
                await msg.reply_text(f"عذراً، الحد الأدنى للانضمام هو {MIN_AGE} سنة. نتمنى نشوفك لاحقاً 🌱")
                return
            st["age"] = age
            st["step"] = "wait_edu"
            save_user(user_id, st)
            await prompt_step(msg, st)

        elif step == "wait_location":
            if not (2 <= len(text) <= 100):
                await msg.reply_text("⚠️ اكتب محافظتك / مكان إقامتك بشكل صحيح.")
                return
            st["location"] = text
            st["step"] = "completed"
            st["registered_at"] = int(time.time())
            add_xp(st, 10)
            save_user(user_id, st)
            await msg.reply_text("✅ تم تسجيل بياناتك (+10 نقاط). انتظر قرار الإدارة.")
            try:
                await send_reg_request(context.bot, user_id, st)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error sending to admin: {e}")
        return

    # ── مراحل المشروع ──
    if st.get("stage") == 3 and step in ("proj_title", "proj_link", "proj_desc"):
        draft = st.setdefault("project_draft", {})
        if step == "proj_title":
            if not (3 <= len(text) <= 80):
                await msg.reply_text("⚠️ العنوان من 3 إلى 80 حرف.")
                return
            draft["title"] = text
            st["step"] = "proj_link"
            save_user(user_id, st)
            await msg.reply_text("<b>2 من 3:</b> ارسل <b>رابط المشروع</b> (يبدأ بـ http):", parse_mode=ParseMode.HTML)
        elif step == "proj_link":
            if not text.lower().startswith(("http://", "https://")) or len(text) > 300 or " " in text:
                await msg.reply_text("⚠️ ارسل رابطاً صحيحاً يبدأ بـ http أو https.")
                return
            draft["link"] = text
            st["step"] = "proj_desc"
            save_user(user_id, st)
            await msg.reply_text("<b>3 من 3:</b> اشرح <b>فكرة المشروع وما أنجزته</b> (30 حرف على الأقل):", parse_mode=ParseMode.HTML)
        else:
            if not (30 <= len(text) <= 1000):
                await msg.reply_text("⚠️ الوصف من 30 إلى 1000 حرف.")
                return
            st["project"] = {
                "title": draft["title"],
                "link": draft["link"],
                "desc": text,
                "status": "pending",
                "submitted_at": int(time.time()),
            }
            st["project_draft"] = {}
            st["step"] = "none"
            save_user(user_id, st)
            await msg.reply_text("✅ تم رفع مشروعك للمراجعة. راح توصلك النتيجة هنا.")
            try:
                await send_project_request(context.bot, user_id, st)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error sending project to admin: {e}")


# ───────────────────────── الاختبار الذكي (المرحلة 2) ─────────────────────────


async def show_question(message, user_id: int, st: dict, edit: bool):
    quiz = st["quiz"]
    pool = QUESTIONS_G2[quiz["spec"]]
    q_text, options, correct_idx = pool[quiz["order"][quiz["pos"]]]

    shuffled = list(options)
    random.shuffle(shuffled)
    quiz["opts"] = shuffled
    quiz["correct"] = options[correct_idx]
    quiz["sent_at"] = time.time()

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"ans_{quiz['pos']}_{i}_{user_id}")]
        for i, opt in enumerate(shuffled)
    ]
    text = (
        f"📝 <b>اختبار تخصصي ({esc(SPECIALTY_NAMES.get(quiz['spec'], quiz['spec']))})</b>\n"
        f"⏱ لديك {QUESTION_SECONDS} ثانية لكل سؤال\n\n"
        f"السؤال {quiz['pos'] + 1} من {len(quiz['order'])}:\n{esc(q_text)}"
    )
    markup = InlineKeyboardMarkup(keyboard)

    if edit:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
            save_user(user_id, st)
            return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"edit failed, sending new message: {e}")
    sent = await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    quiz["msg_id"] = sent.message_id
    save_user(user_id, st)


async def handle_start_quiz(query, user_id: int, data: str):
    last = last_part(data)
    if last.isdigit() and int(last) != user_id:
        await alert(query, "⚠️ هذا الزر مخصص للعضو المعني!")
        return
    st = get_user(user_id)
    if st.get("stage") != 2:
        await alert(query, "⚠️ هذا الاختبار لمن وافقت الإدارة على تسجيله ولم يجتزه بعد.")
        return
    spec = st.get("specialty")
    if spec not in QUESTIONS_G2:
        await alert(query, "⚠️ ما عندك تخصص مسجّل. اكتب /start بالخاص.")
        return
    wait = attempts_wait(st, "g2_attempts")
    if wait:
        save_user(user_id, st)
        await alert(query, f"⏳ استنفدت محاولاتك. حاول بعد {format_wait(wait)}.")
        return

    st["g2_attempts"].append(time.time())
    pool_size = len(QUESTIONS_G2[spec])
    order = random.sample(range(pool_size), min(QUIZ_LENGTH, pool_size))
    st["quiz"] = {"spec": spec, "order": order, "pos": 0, "score": 0}
    await query.answer()
    await show_question(query.message, user_id, st, edit=False)


async def handle_answer(query, context, user_id: int, data: str):
    parts = data.split("_")  # ans_{pos}_{opt}_{uid}
    try:
        pos, opt_idx, target = int(parts[1]), int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        await query.answer()
        return
    if user_id != target:
        await alert(query, "⚠️ هذه الإجابة مخصصة لصاحب الاختبار فقط!")
        return

    st = get_user(user_id)
    quiz = st.get("quiz")
    if (
        not quiz
        or quiz.get("msg_id") != query.message.message_id
        or quiz.get("pos") != pos
        or not (0 <= opt_idx < len(quiz.get("opts", [])))
    ):
        await alert(query, "⚠️ هذا السؤال منتهي أو تمت الإجابة عليه.")
        return

    late = time.time() - quiz.get("sent_at", 0) > QUESTION_SECONDS
    if late:
        await alert(query, "⏱ انتهى وقت السؤال، حُسبت الإجابة خاطئة.")
    else:
        await query.answer()
        if quiz["opts"][opt_idx] == quiz["correct"]:
            quiz["score"] += 1
    quiz["pos"] += 1

    total = len(quiz["order"])
    if quiz["pos"] < total:
        await show_question(query.message, user_id, st, edit=True)
        return

    score = quiz["score"]
    st["quiz"] = None
    need_score = math.ceil(PASS_RATIO * total)

    if score >= need_score:
        await query.message.edit_text(
            f"🎉 اجتزت الاختبار ({score}/{total})! تم فتح المرحلة الثالثة، ووصلك الرابط بالخاص."
        )
        await auto_approve_stage3(context, user_id, st, score, total)
    else:
        save_user(user_id, st)
        left = MAX_ATTEMPTS - len(st.get("g2_attempts", []))
        if left > 0:
            await query.message.edit_text(
                f"❌ نتيجتك ({score}/{total}) والمطلوب {need_score}. تبقّت لك {left} محاولة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 إعادة الاختبار", callback_data=f"qs_{user_id}")]]),
            )
        else:
            await query.message.edit_text(f"❌ نتيجتك ({score}/{total}). استنفدت محاولاتك، حاول بعد 24 ساعة.")


async def auto_approve_stage3(context, user_id: int, st: dict, score: int, total: int):
    st["stage"] = 3
    st["step"] = "none"
    st["g2_score"] = score
    add_xp(st, 50 + 5 * score)
    save_user(user_id, st)
    log_audit(0, "auto_approve_g3", user_id, f"score={score}/{total}")

    link = await make_invite(context.bot, GROUP_3_ID, GROUP_3_LINK, f"g3-{user_id}")
    keyboard = [[InlineKeyboardButton("🔗 انضمام إلى منصة إظهار الموهبة (المجموعة 3)", url=link)]]
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 مبروك! اجتزت الاختبار ({score}/{total}) وحصلت على نقاط.\n"
                "انضم للمجموعة الثالثة، وبعدها قدّم مشروع الإثبات بأمر /project"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"could not DM {user_id}: {e}")
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"ℹ️ {display_name(st)} ({spec_label(st)}) اجتاز الاختبار {score}/{total} وانتقل تلقائياً للمرحلة 3.\nالآيدي: {user_id}",
        )
    except Exception:  # noqa: BLE001
        pass


# ───────────────────────── قرارات الإدارة ─────────────────────────


def pick_mentor(exclude_id: int):
    mentors = [(uid, st) for uid, st in all_users() if st.get("mentor") and st.get("stage") == 4 and uid != exclude_id]
    if not mentors:
        return None
    all_list = all_users()
    load = {uid: 0 for uid, _ in mentors}
    for _, st in all_list:
        m = st.get("mentor_id")
        if m in load:
            load[m] += 1
    return min(load, key=lambda k: load[k])


async def finalize_member(context, target: int, st: dict) -> str:
    if not st.get("member_no"):
        st["member_no"] = next_member_no()
    st["stage"] = 4
    st["step"] = "none"
    st["project"]["status"] = "approved"
    add_xp(st, 100)

    mentor_id = pick_mentor(target)
    mentor_line = ""
    if mentor_id:
        st["mentor_id"] = mentor_id
        mentor_line = f"\n🧑‍🏫 <b>مرشدك:</b> {mention(mentor_id, display_name(get_user(mentor_id), 'المرشد'))}"
    save_user(target, st)

    name, _ = level_info(st["xp"])
    link = await make_invite(context.bot, GROUP_4_ID, FINAL_GROUP_4_LINK, f"g4-{target}")
    keyboard = [[InlineKeyboardButton("🔗 انضمام إلى المجموعة الرابعة (الإدارة العليا)", url=link)]]
    await context.bot.send_message(
        chat_id=target,
        text=(
            f"{WELCOME_RULES_TEXT}\n\n"
            f"🪪 <b>رقم هويتك:</b> <code>{member_code(st)}</code>\n"
            f"🏅 <b>مستواك:</b> {name} ({st['xp']} نقطة){mentor_line}"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )
    if mentor_id:
        try:
            await context.bot.send_message(
                chat_id=mentor_id,
                text=f"🧑‍🏫 تم تعيينك مرشداً للعضو {display_name(st)} ({spec_label(st)}).",
            )
        except Exception:  # noqa: BLE001
            pass
    return member_code(st)


async def handle_admin_action(query, context, user_id: int, data: str):
    if not is_admin(user_id):
        await alert(query, "⛔ هذا الزر للإدارة فقط.")
        return
    await query.answer()
    target = int(last_part(data))
    st = get_user(target)

    if data.startswith("app_g2_"):
        if st.get("stage") != 1 or st.get("step") != "completed":
            await query.edit_message_text("ℹ️ هذا الطلب تمت معالجته سابقاً.")
            return
        link = await make_invite(context.bot, GROUP_2_ID, GROUP_2_LINK, f"g2-{target}")
        keyboard = [[InlineKeyboardButton("🔗 انضمام إلى مختبر المواهب (المجموعة 2)", url=link)]]
        try:
            await context.bot.send_message(
                chat_id=target,
                text="🎉 تمت الموافقة على انضمامك للمجموعة الثانية! انضم الآن واختبر تخصصك:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Forbidden:
            await query.edit_message_text("⚠️ العضو حظر البوت أو لم يفعّله.")
            return
        st["stage"] = 2
        st["step"] = "none"
        save_user(target, st)
        log_audit(user_id, "approve_g2", target)
        await query.edit_message_text(f"✅ تمت الموافقة وإرسال رابط المجموعة 2 لـ {display_name(st)}.")

    elif data.startswith("rej_reg_"):
        if st.get("stage") != 1 or st.get("step") != "completed":
            await query.edit_message_text("ℹ️ هذا الطلب تمت معالجته سابقاً.")
            return
        st["step"] = "none"
        save_user(target, st)
        log_audit(user_id, "reject_reg", target)
        try:
            await context.bot.send_message(chat_id=target, text="❌ عذراً، تم رفض طلبك من قبل الإدارة. تكدر تقدّم مرة ثانية بـ /start")
        except Exception:  # noqa: BLE001
            pass
        await query.edit_message_text("❌ تم رفض الطلب.")

    elif data.startswith("prj_ok_"):
        if st.get("stage") != 3 or st.get("project", {}).get("status") != "pending":
            await query.edit_message_text("ℹ️ هذا المشروع تمت معالجته سابقاً.")
            return
        try:
            code = await finalize_member(context, target, st)
        except Exception as e:  # noqa: BLE001
            logger.exception("finalize failed")
            await query.edit_message_text(f"⚠️ خطأ بإرسال رسالة العضو: {e}")
            return
        log_audit(user_id, "approve_final", target, code)
        await query.edit_message_text(f"✅ اعتمد {display_name(st)} للمرحلة 4. الهوية: {code}")

    elif data.startswith(("prj_rev_", "prj_no_")):
        if st.get("stage") != 3 or st.get("project", {}).get("status") != "pending":
            await query.edit_message_text("ℹ️ هذا المشروع تمت معالجته سابقاً.")
            return
        revise = data.startswith("prj_rev_")
        st["project"]["status"] = "revision" if revise else "rejected"
        save_user(target, st)
        log_audit(user_id, "project_revision" if revise else "project_reject", target)
        msg = (
            "🔁 مشروعك يحتاج تعديلاً. راجع ملاحظات الإدارة (إن وصلتك) وأعد التقديم بأمر /project"
            if revise
            else "❌ لم يُقبل مشروعك هذه المرة. تكدر تقدّم مشروعاً جديداً بأمر /project"
        )
        try:
            await context.bot.send_message(chat_id=target, text=msg)
        except Exception:  # noqa: BLE001
            pass
        await query.edit_message_text(
            ("🔁 أُرسل طلب التعديل. تكدر ترسل ملاحظة بـ /note " if revise else "❌ تم رفض المشروع. ")
            + f"{target}"
        )


# ───────────────────────── أوامر الأعضاء ─────────────────────────


async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    st = get_user(user_id)
    if not st.get("consent"):
        await update.message.reply_text("ما عندك ملف بعد. اكتب /start للتسجيل.")
        return
    xp = st.get("xp", 0)
    level, nxt = level_info(xp)
    progress = f"\n⬆️ المتبقي للمستوى التالي ({nxt[1]}): {nxt[0] - xp} نقطة" if nxt else "\n🏆 وصلت لأعلى مستوى"
    mentor = ""
    if st.get("mentor_id"):
        mentor = f"\n🧑‍🏫 المرشد: {mention(st['mentor_id'], display_name(get_user(st['mentor_id']), 'المرشد'))}"
    elif st.get("mentor"):
        mentor = "\n🧑‍🏫 أنت مرشد معتمد"
    await update.message.reply_text(
        f"🪪 <b>بطاقة Byte Alliance</b>\n"
        f"الهوية: <code>{member_code(st)}</code>\n"
        f"الاسم: {esc(display_name(st))}\n"
        f"التخصص: {esc(spec_label(st))}\n"
        f"المرحلة: {st.get('stage', 1)}/4 ({STAGE_NAMES.get(st.get('stage', 1))})\n"
        f"🏅 المستوى: {level} | النقاط: {xp}{progress}{mentor}",
        parse_mode=ParseMode.HTML,
    )


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    spec = context.args[0].lower() if context.args else None
    if spec and spec not in SPECIALTY_NAMES:
        await update.message.reply_text("التخصصات: " + ", ".join(SPECIALTY_NAMES))
        return
    rows = [
        (uid, st) for uid, st in all_users()
        if st.get("xp", 0) > 0 and st.get("consent") and (not spec or st.get("specialty") == spec)
    ]
    rows.sort(key=lambda r: r[1].get("xp", 0), reverse=True)
    if not rows:
        await update.message.reply_text("لا توجد نقاط بعد.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (_, st) in enumerate(rows[:10]):
        first = display_name(st, "عضو").split()[0]
        lines.append(f"{medals[i] if i < 3 else str(i + 1) + '.'} {esc(first)} - {level_info(st['xp'])[0]} - {st['xp']} نقطة")
    title = f"🏆 <b>لوحة الشرف{' - ' + esc(SPECIALTY_NAMES[spec]) if spec else ''}</b>\n\n"
    await update.message.reply_text(title + "\n".join(lines), parse_mode=ParseMode.HTML)


async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    st = get_user(user_id)
    stage = st.get("stage", 1)
    target = group_for_stage(stage)
    if not target:
        await update.message.reply_text("ما عندك مجموعة لمرحلتك الحالية.")
        return
    used = st.setdefault("links_used", {})
    if used.get(str(stage), 0) >= MAX_LINK_REGEN:
        await update.message.reply_text("استنفدت عدد الروابط المسموحة. تواصل مع الإدارة.")
        return
    used[str(stage)] = used.get(str(stage), 0) + 1
    save_user(user_id, st)
    chat_id, fallback = target
    link = await make_invite(context.bot, chat_id, fallback, f"s{stage}-{user_id}")
    await update.message.reply_text(
        "🔗 رابطك (يصلح لمرة وحدة):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("انضمام", url=link)]]),
    )


async def delete_me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    keyboard = [[
        InlineKeyboardButton("🗑 نعم، احذف بياناتي", callback_data="del_yes"),
        InlineKeyboardButton("إلغاء", callback_data="del_no"),
    ]]
    await update.message.reply_text(
        "⚠️ سيتم حذف ملفك ونقاطك وهويتك نهائياً. متأكد؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ───────────────────────── أوامر الإدارة ─────────────────────────


def admin_only(update: Update) -> bool:
    return bool(update.effective_user) and is_admin(update.effective_user.id)


async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    await update.message.reply_text(f"آيدي هذه المحادثة: {update.effective_chat.id}")


async def setup_group1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" or not admin_only(update):
        return
    keyboard = [[InlineKeyboardButton("📝 ابدأ التسجيل بالخاص", url=f"https://t.me/{BOT_USERNAME}?start=register")]]
    await update.message.reply_text(
        "🦅 <b>أهلاً بكم في المجموعة الأولى (اكتشاف المواهب)</b>\nالتسجيل يتم بالخاص مع البوت حفاظاً على خصوصيتكم.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def setup_quiz_group2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" or not admin_only(update):
        return
    keyboard = [[InlineKeyboardButton("🧠 ابدأ اختبار التخصص", callback_data="qs_gen")]]
    await update.message.reply_text(
        "🧪 <b>مختبر المواهب (المجموعة الثانية)</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    users = all_users()
    regs = [(u, s) for u, s in users if s.get("stage") == 1 and s.get("step") == "completed"]
    prjs = [(u, s) for u, s in users if s.get("stage") == 3 and s.get("project", {}).get("status") == "pending"]
    if not regs and not prjs:
        await update.message.reply_text("✅ لا توجد طلبات معلقة.")
        return
    for uid, st in regs[:10]:
        await send_reg_request(context.bot, uid, st)
    for uid, st in prjs[:10]:
        await send_project_request(context.bot, uid, st)
    await update.message.reply_text(f"المعلّق: {len(regs)} تسجيل، {len(prjs)} مشروع (عُرض حتى 10 من كل نوع).")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    users = [(u, s) for u, s in all_users() if s.get("consent")]
    by_stage = {i: 0 for i in range(1, 5)}
    by_spec: dict = {}
    tried = passed = 0
    for _, s in users:
        by_stage[s.get("stage", 1)] = by_stage.get(s.get("stage", 1), 0) + 1
        if s.get("specialty"):
            by_spec[s["specialty"]] = by_spec.get(s["specialty"], 0) + 1
        if s.get("g2_attempts"):
            tried += 1
            if s.get("stage", 1) >= 3:
                passed += 1
    lines = [f"📊 <b>إحصائيات</b>\nإجمالي المسجلين: {len(users)}\n"]
    for i in range(1, 5):
        lines.append(f"المرحلة {i} ({STAGE_NAMES[i]}): {by_stage[i]}")
    rate = f"{round(100 * passed / tried)}%" if tried else "-"
    lines.append(f"\nنسبة نجاح الاختبار: {rate} ({passed}/{tried})")
    lines.append("\n<b>حسب التخصص:</b>")
    for code, n in sorted(by_spec.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {esc(SPECIALTY_NAMES.get(code, code))}: {n}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("الاستخدام: /broadcast نص الرسالة")
        return
    ok = fail = 0
    for uid, st in all_users():
        if not st.get("started_bot"):
            continue
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}")
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
        await asyncio.sleep(0.05)
    log_audit(ADMIN_ID, "broadcast", 0, text[:100])
    await update.message.reply_text(f"تم الإرسال: {ok} | فشل: {fail}")


async def addxp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: /addxp آيدي عدد   (مثال: /addxp 123456 20)")
        return
    st = get_user(uid)
    if not st.get("consent"):
        await update.message.reply_text("هذا العضو غير مسجل.")
        return
    add_xp(st, amount)
    save_user(uid, st)
    log_audit(ADMIN_ID, "addxp", uid, str(amount))
    await update.message.reply_text(f"✅ {display_name(st)} الآن {st['xp']} نقطة ({level_info(st['xp'])[0]}).")
    try:
        await context.bot.send_message(chat_id=uid, text=f"⭐ حصلت على {amount} نقطة من الإدارة. مجموعك: {st['xp']}")
    except Exception:  # noqa: BLE001
        pass


async def setmentor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: /setmentor آيدي")
        return
    st = get_user(uid)
    if st.get("stage") != 4:
        await update.message.reply_text("المرشد لازم يكون عضواً بالمرحلة 4.")
        return
    st["mentor"] = not st.get("mentor", False)
    save_user(uid, st)
    log_audit(ADMIN_ID, "setmentor", uid, str(st["mentor"]))
    await update.message.reply_text(f"{display_name(st)}: {'مرشد ✅' if st['mentor'] else 'ليس مرشداً'}")


async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    parts = update.message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].lstrip("-").isdigit():
        await update.message.reply_text("الاستخدام: /note آيدي نص الملاحظة")
        return
    try:
        await context.bot.send_message(chat_id=int(parts[1]), text=f"📝 ملاحظة من الإدارة:\n{parts[2]}")
        log_audit(ADMIN_ID, "note", int(parts[1]), parts[2][:100])
        await update.message.reply_text("✅ أُرسلت.")
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"⚠️ فشل: {e}")


async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    code = (context.args[0].upper() if context.args else "")
    for uid, st in all_users():
        if st.get("member_no") and member_code(st) == code:
            await update.message.reply_text(
                f"✅ <b>عضو معتمد</b>\nالاسم: {esc(display_name(st))}\nالتخصص: {esc(spec_label(st))}\n"
                f"المستوى: {level_info(st.get('xp', 0))[0]}\nالآيدي: <code>{uid}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
    await update.message.reply_text("❌ لا يوجد عضو بهذه الهوية.")


async def audit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return
    rows = db.execute("SELECT ts, actor, action, target, note FROM audit ORDER BY id DESC LIMIT 15").fetchall()
    if not rows:
        await update.message.reply_text("السجل فارغ.")
        return
    lines = [
        f"{datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')} | {'auto' if actor == 0 else actor} | {action} | {target} {note}"
        for ts, actor, action, target, note in rows
    ]
    await update.message.reply_text("🧾 آخر القرارات:\n" + "\n".join(lines))


# ───────────────────────── تتبع انضمام الأعضاء ─────────────────────────


async def kick_intruder(context, chat_id: int, user_id: int, reason: str):
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        log_audit(0, "kick_intruder", user_id, f"chat={chat_id} {reason}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⛔ دخلت مجموعة قبل ما توصلها بمسارك. أكمل المراحل بالترتيب عبر البوت: /start",
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"kick failed in {chat_id}: {e}")


async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result is None:
        return
    chat_id = result.chat.id
    old_status, new_status = result.old_chat_member.status, result.new_chat_member.status
    if not (old_status in ("left", "kicked") and new_status in ("member", "administrator")):
        return

    user = result.new_chat_member.user
    if user.is_bot:
        return
    user_id = user.id
    st = get_user(user_id)
    who = mention(user_id, user.full_name)

    # طرد من دخل مجموعة قبل أوانه (روابط مسرّبة)
    req = required_stage(chat_id)
    if req and not is_admin(user_id) and st.get("stage", 1) < req:
        await kick_intruder(context, chat_id, user_id, f"stage={st.get('stage', 1)} < {req}")
        return

    if chat_id == GROUP_1_ID:
        keyboard = [[InlineKeyboardButton("📝 ابدأ التسجيل بالخاص", url=f"https://t.me/{BOT_USERNAME}?start=register")]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🦅 أهلاً بك {who} في <b>المجموعة الأولى</b>!\n\nاضغط الزر لبدء التسجيل بالخاص مع البوت:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    elif chat_id == GROUP_3_ID:
        keyboard = [[InlineKeyboardButton("🌟 قدّم مشروع الإثبات", url=f"https://t.me/{BOT_USERNAME}?start=project")]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎨 أهلاً بك {who} في <b>منصة إظهار الموهبة (المجموعة الثالثة)</b>!\n\n"
                 f"أثبت موهبتك بمشروع حقيقي، اضغط الزر لتقديمه عبر البوت:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    elif GROUP_4_ID and chat_id == GROUP_4_ID:
        return
    elif GROUP_2_ID and chat_id == GROUP_2_ID or (not GROUP_2_ID and st.get("stage") != 4):
        keyboard = [[InlineKeyboardButton("🧠 ابدأ اختبار التخصص", callback_data=f"qs_{user_id}")]]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧪 أهلاً بك {who} في <b>مختبر المواهب (المجموعة الثانية)</b>!\n\n"
                 f"اضغط الزر لبدء اختبارك التخصصي:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )


# ───────────────────────── موزّع الأزرار ─────────────────────────


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data or ""
    try:
        if data == "consent_yes":
            await handle_consent(query, user_id)
        elif data.startswith("spec_"):
            await handle_spec(query, user_id, data)
        elif data.startswith("edu_"):
            await handle_edu(query, user_id, data)
        elif data.startswith("qs_"):
            await handle_start_quiz(query, user_id, data)
        elif data.startswith("ans_"):
            await handle_answer(query, context, user_id, data)
        elif data == "del_yes":
            await query.answer()
            delete_user(user_id)
            log_audit(user_id, "user_deleted", user_id)
            await query.message.edit_text("🗑 تم حذف بياناتك نهائياً.")
        elif data == "del_no":
            await query.answer()
            await query.message.edit_text("تم الإلغاء.")
        elif data.startswith(("app_g2_", "rej_reg_", "prj_ok_", "prj_rev_", "prj_no_")):
            await handle_admin_action(query, context, user_id, data)
        else:
            await query.answer()
    except Exception:
        logger.exception("button_handler failed")
        try:
            await query.answer("⚠️ صار خطأ، حاول مرة ثانية.", show_alert=True)
        except Exception:  # noqa: BLE001
            pass


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)


async def post_init(app: Application):
    user_cmds = [
        BotCommand("start", "ابدأ أو اعرف مرحلتك"),
        BotCommand("me", "بطاقتي ومستواي"),
        BotCommand("project", "تقديم مشروع الإثبات"),
        BotCommand("top", "لوحة الشرف"),
        BotCommand("link", "رابط جديد لمجموعة مرحلتي"),
        BotCommand("delete_me", "حذف بياناتي"),
        BotCommand("help", "مساعدة"),
    ]
    admin_cmds = user_cmds + [
        BotCommand("pending", "الطلبات المعلقة"),
        BotCommand("stats", "الإحصائيات"),
        BotCommand("broadcast", "رسالة لكل الأعضاء"),
        BotCommand("addxp", "إضافة نقاط"),
        BotCommand("setmentor", "تعيين مرشد"),
        BotCommand("note", "ملاحظة لعضو"),
        BotCommand("verify", "تحقق من هوية"),
        BotCommand("audit", "سجل القرارات"),
    ]
    try:
        await app.bot.set_my_commands(user_cmds, scope=BotCommandScopeAllPrivateChats())
        await app.bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(ADMIN_ID))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"set_my_commands failed: {e}")
    if not GROUP_2_ID or not GROUP_4_ID:
        logger.warning("GROUP_2_ID/GROUP_4_ID غير محددين: الروابط ذات المرة الواحدة وطرد المتسللين معطّلة لهما.")


def main():
    application = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(post_init)
        .build()
    )
    private_text = filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE

    for name, fn in [
        ("start", start), ("help", help_cmd), ("me", me_cmd), ("project", project_cmd),
        ("top", top_cmd), ("link", link_cmd), ("delete_me", delete_me_cmd),
        ("id", id_cmd), ("setup", setup_group1), ("quiz", setup_quiz_group2),
        ("pending", pending_cmd), ("stats", stats_cmd), ("broadcast", broadcast_cmd),
        ("addxp", addxp_cmd), ("setmentor", setmentor_cmd), ("note", note_cmd),
        ("verify", verify_cmd), ("audit", audit_cmd),
    ]:
        application.add_handler(CommandHandler(name, fn))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(ChatMemberHandler(track_new_members, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(private_text, handle_private_text))
    application.add_error_handler(on_error)
    print("Byte Alliance v2 is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
