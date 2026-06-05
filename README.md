# موجز الإمارات اليومي - نسخة محلية تجريبية

هذا مشروع Python محلي على Windows يجمع أخبار الإمارات من Google News RSS، يرشح النتائج منخفضة الجودة، يصنف العناوين المهمة، وينشئ ملف PDF عربي متعدد الصفحات مناسب للقراءة والمشاركة.

## الملفات

```text
news sum/
  assets/
    fonts/
      Cairo-Variable.ttf
      NotoNaskhArabic-Variable.ttf
  briefs/
    uae_daily_brief_YYYY-MM-DD_day.pdf
  README.md
  requirements.txt
  send_to_telegram.py
  uae_news_demo.py
  uae_daily_brief.pdf
```

## أوامر Windows PowerShell

```powershell
cd "C:\Users\aaldh\OneDrive\Desktop\news sum"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python .\uae_news_demo.py
```

إذا منع PowerShell تشغيل ملف التفعيل، نفذ الأمر التالي في نفس النافذة ثم فعل البيئة مرة أخرى:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

سيتم حفظ ملف PDF اليومي بنسختين:

```text
C:\Users\aaldh\OneDrive\Desktop\news sum\briefs\uae_daily_brief_YYYY-MM-DD_day.pdf
C:\Users\aaldh\OneDrive\Desktop\news sum\uae_daily_brief.pdf
```

الملف داخل `briefs` هو الأرشيف المؤرخ. ملف `uae_daily_brief.pdf` هو آخر نسخة فقط.

## إرسال PDF إلى Telegram

لا يحتاج هذا إلى OpenAI أو ChatGPT tokens. تحتاج فقط إلى Bot Token من `@BotFather`.

معرف المحادثة الخاص بك:

```text
47329648
```

### حفظ التوكن بشكل آمن على Windows

لا تضع التوكن داخل ملفات Python ولا ترسله في المحادثات. احفظه كمتغير بيئة خاص بمستخدم Windows:

```powershell
[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOTFATHER_TOKEN_HERE", "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", "47329648", "User")
```

بعد ذلك أغلق PowerShell وافتحه من جديد.

للتأكد أن التوكن محفوظ بدون طباعته كاملا:

```powershell
$token = [Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "User")
"Token saved: " + ($token.Length -gt 20)
```

ثم شغل الإرسال:

```powershell
cd "C:\Users\aaldh\OneDrive\Desktop\news sum"
.\.venv\Scripts\Activate.ps1
python .\send_to_telegram.py
```

سيتم إرسال ملف اليوم المؤرخ، وسيظهر في Telegram بعنوان يحتوي على اليوم والتاريخ.

إذا أردت إرسال ملف PDF الموجود بدون إعادة توليده:

```powershell
python .\send_to_telegram.py --skip-generate
```

## التشغيل التلقائي اليومي

تم تجهيز سكربت خاص للتشغيل من Windows Task Scheduler:

```text
C:\Users\aaldh\OneDrive\Desktop\news sum\run_daily_telegram.ps1
```

يسجل كل تشغيل في:

```text
C:\Users\aaldh\OneDrive\Desktop\news sum\logs
```

لتشغيله يدويا:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\aaldh\OneDrive\Desktop\news sum\run_daily_telegram.ps1"
```

## ماذا يفعل المشروع؟

- يستخدم Google News RSS باللغة العربية والإنجليزية لمراقبة أي أخبار حول الإمارات في المصادر المحلية والإقليمية والعالمية.
- يتابع مصادر إماراتية وعربية وعالمية مثل وام، البيان، الإمارات اليوم، الخليج، The National، Reuters، AP، Bloomberg، BBC، CNN، France 24، Al Jazeera، Arab News، وغيرها.
- يركز على الأخبار الحديثة خلال آخر 7 أيام حتى لا تظهر نتائج قديمة من أرشيف RSS.
- يستبعد نتائج منخفضة القيمة مثل الرياضة، الشائعات، الترفيه، المشاهير، والتحقق من الأخبار الكاذبة.
- يحتفظ بأي خبر عالمي مرتبط بالإمارات أو دبي أو أبوظبي أو أدنوك أو مبادلة أو محمد بن زايد، مع استبعاد النتائج منخفضة الجودة.
- يزيل العناوين المكررة بعد تنظيف النص.
- يستخدم فلترة إضافية للعناوين المتشابهة حتى لا تتكرر نفس القصة من أكثر من مصدر بشكل مزعج.
- يصنف الأخبار إلى: القيادة، الحكومة، الدفاع والأمن، الاقتصاد، العلاقات الخارجية، وأخبار إماراتية مهمة.
- يستخدم خطوط عربية محلية من مجلد `assets/fonts`، ويفضل Noto Naskh Arabic عند توفره.
- يحول روابط Google News RSS إلى رابط الناشر الأصلي، ثم يحاول استخراج صورة الخبر الحقيقية من صفحة الناشر عبر OpenGraph.
- يرفض صور الشعارات والصور العامة وصور Google News الافتراضية.
- ينشئ ملف PDF متعدد الصفحات، وكل خبر ظاهر في PDF يحتوي على صورة حقيقية من صفحة الناشر نفسها.
- يضيف موجزا أوضح من 3 إلى 4 أسطر لكل خبر، ويفضل دمج أول فقرات حقيقية من صفحة الناشر إذا كان وصف الصفحة قصيرا أو غير مكتمل.
- يضيف رابطا مباشرا قابلا للنقر بعنوان `فتح الخبر الأصلي` لكل خبر.
- إذا لم يجد السكربت صورة حقيقية موثوقة لخبر معين، لا يعرض هذا الخبر في PDF المصور بدلا من استخدام صورة بديلة مضللة.

## الصور والخطوط

- الخط العربي المحلي: Noto Naskh Arabic.
- الصور تأتي من صفحة الناشر الأصلية فقط، ولا يستخدم السكربت صورة عامة بديلة.

إذا لم يتم العثور على أخبار مطابقة أو فشل RSS، سيظل السكربت ينشئ ملف PDF يحتوي على:

```text
لم يتم العثور على أخبار إماراتية مطابقة اليوم.
```
