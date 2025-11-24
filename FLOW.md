# LINE Bot EDC Flow

เอกสารนี้อธิบายการทำงานของบอท ตั้งแต่รับข้อความ/รูปจาก LINE จนถึงสร้าง Ticket และตอบกลับผู้ใช้ รวมถึงกรณีขอบและข้อควรระวังที่สำคัญ

## ส่วนประกอบหลัก
- `script.py`: Flask + LINE SDK webhook
  - แยก event ตามชนิดข้อความ: TextMessage, ImageMessage
  - ดาวน์โหลดรูปเป็นไฟล์ชั่วคราว (tmp_uploads)
  - เรียกใช้ `process_step_message` / `process_image_message`
  - ลงทะเบียน `set_reply_callback` เพื่อตอบกลับด้วย reply_token
- `dialog/edcDialog.py`: จัดการ state และลำดับบทสนทนา (dialog)
  - เก็บสถานะผู้ใช้ใน `_user_states`
  - คำถาม/คำตอบ, การแนบรูป, ตัวตั้งเวลา auto-submit 5 วินาทีแบบ debounce
  - `_summary` ประกอบ payload อัปโหลดรูป และเรียก `fetch`
- `fetchData/fetch.py`: ติดต่อ API ภายนอก สร้างคำร้อง/ทิเก็ต และอัปโหลดไฟล์

## โครงสร้าง State (ต่อผู้ใช้หนึ่งราย)
```json
{
  "step": 0,
  "answers": ["..."],
  "updated": 1690000000.0,
  "uid": "<userId or composite>",
  "image_paths": ["tmp_uploads/123.jpg", "..."]
}
```
หมายเหตุ: โค้ดปัจจุบันใช้ reply_token เก็บใน state ชั่วคราวเป็น `state["reply_token"]` ระหว่างรอ auto-submit

## เส้นทางข้อความ (TextMessage)
1) LINE → `/callback` → `handle_message`
2) สร้าง `user_id` (user/group/room composite) → `process_step_message(user_id, text)`
3) ภายใน `process_step_message`:
   - `_expire()` เคลียร์เซสชันหมดอายุ
   - ถ้าไม่มี state → สร้างด้วย `_start(user_id)`
   - คำสั่งพิเศษ: "ยกเลิก" → `_clear` / "ยืนยัน" → `_summary` แล้วล้าง
   - เรียก AI (`send_massage`) เพื่อช่วยจัดรูปแบบคำตอบที่มี label (เช่น ชื่อสาขา/ชื่อผู้แจ้ง/เบอร์/รายละเอียด)
   - เมื่อ AI ตอบครบตามรูปแบบที่ต้องการ จะบันทึกคำตอบลง `state["answers"]`
   - ถ้า AI ขอรูปภาพ → เปลี่ยนเข้าสเต็ปอัปโหลดรูป (step 4)

ผลลัพธ์: ฟังก์ชันคืน string สำหรับ reply ทันที (ข้อความ)

## เส้นทางรูปภาพ (ImageMessage)
1) LINE → `/callback` → `handle_image`
2) ดาวน์โหลดไฟล์ → ได้ `image_path`
3) เรียก `process_image_message(user_id, image_path, reply_token)`
4) ภายใน `process_image_message`:
   - ถ้า state ไม่มีก็สร้างใหม่
   - เพิ่ม `image_path` ลงใน `state["image_paths"]`
   - เก็บ `reply_token` ล่าสุดไว้ใน `state["reply_token"]`
   - ตั้งตัวจับเวลา auto-submit 5 วินาที (debounce): `_schedule_auto_submit`
   - ปกติไม่ reply ทันที (คืนค่า None) เพราะจะใช้ `reply_token` ตอบเมื่อสรุปผล

หมายเหตุ: ถ้าต้องการแจ้งยอดรูปทันที สามารถให้ฟังก์ชันคืน string แล้ว `script.py` จะ reply ทันทีได้

## Auto-submit 5 วินาที (Debounce)
- ทุกครั้งที่มีรูปเข้า จะรีเซ็ต timer เป็น 5 วินาที
- เมื่อครบเวลา `_auto_submit_job(user_id)` จะทำงาน:
  - ถ้า `answers` ยังว่าง → ใช้ `reply_token` ตอบขอข้อมูลรายละเอียด (ไม่ล้าง state รูปยังอยู่)
  - ถ้ามี `answers` แล้ว → เรียก `_summary(state)`
    - อัปโหลดรูปทั้งหมด → แนบลง payload → `fetch`
    - ถ้าสำเร็จ: ลบไฟล์รูปในเครื่อง, สร้างข้อความ Ticket, `reply` กลับด้วย `reply_token`
    - ถ้าล้มเหลว: `reply` ข้อความแจ้งไม่สามารถบันทึกข้อมูลได้
  - จากนั้น `_clear(user_id)` เพื่อล้าง state และยกเลิก timer

## `_summary(state)` ทำอะไร
- ดึงข้อมูลจาก `state["answers"]` (ข้อความที่มี label ครบ)
- อัปโหลดรูปทั้งหมดด้วย `uploadFile`
- ประกอบ payload และเรียก `fetch`
- สร้างข้อความสรุปผลตอบกลับ

## กรณีขอบที่รองรับ
- ผู้ใช้ส่งรูปก่อนส่งข้อความ: ระบบจะรอ 5 วินาทีแล้วส่งข้อความให้ใส่รายละเอียด แล้วเก็บรูปไว้ใน state ไม่ทิ้ง
- ผู้ใช้ส่งหลายรูปติดกัน: ตัวจับเวลาจะเลื่อนออกทุกครั้ง (5 วินาทีหลังรูปสุดท้าย)
- ผู้ใช้เริ่มใหม่/ยกเลิก: `ยกเลิก` จะล้าง state ทันที
- reply token: หากหมดอายุก่อนสรุป อาจ reply ไม่สำเร็จ (มี log error) ควรคงดีเลย์สั้น ๆ

## การตั้งค่า/ข้อควรระวัง
- ต้องลงทะเบียน `set_reply_callback` ใน `script.py` เพื่อให้ auto-submit สามารถ reply ด้วย reply_token ได้
- เปิดโหมด DEV: ระวัง `verify=False` ใน `fetch.py` (ควรใช้ cert จริงใน PROD)
- ไฟล์ชั่วคราวใน `tmp_uploads` จะถูกลบเมื่อสร้างทิเก็ตสำเร็จเท่านั้น (กันกรณี retry)
- สเกลหลาย instance: แนะนำย้าย state ไป Redis และใช้ lock/TTL สำหรับ production

## ลำดับแบบย่อ (ข้อความ → รูป → สรุป)
1) ผู้ใช้: กรอกข้อความรายละเอียด → AI format → บันทึกลง answers → ขอรูป
2) ผู้ใช้: ส่งรูป 1–N ใบ (แต่ละใบรีเซ็ตดีเลย์ 5 วิ)
3) ดีเลย์ครบ → สรุป/ส่งทิเก็ต → ตอบกลับด้วย reply_token → ล้าง state

## คู่มือ Docker เบื้องต้นสำหรับโปรเจ็กต์นี้

หัวข้อนี้สรุปตั้งแต่ 0 ว่า Docker คืออะไร, ภาพรวม Build → Image → Run → Container และบทบาทไฟล์ Dockerfile, docker-compose.yml, requirements.txt, .env, .dockerignore ในโปรเจ็กต์นี้ รวมถึงกับดักที่พบบ่อยและวิธีทดสอบเร็ว ๆ

### ภาพรวม: Image vs Container
- Image: แม่พิมพ์แบบอ่านอย่างเดียว (เหมือน ISO) เก็บระบบไฟล์และโปรแกรมที่ต้องใช้ตามที่เขียนใน Dockerfile
- Container: อินสแตนซ์ที่กำลังรันซึ่งถูกสร้างจาก Image แต่ละตัวมีไฟล์ระบบ/สิ่งแวดล้อมของตัวเอง
- Build: ขั้นตอนแปลงซอร์สโค้ดของเราให้กลายเป็น Image ตาม Dockerfile
- Run: ขั้นตอนนำ Image มารันเป็น Container พร้อมกำหนดพอร์ต, ENV, โวลุ่ม, เน็ตเวิร์ก

สรุปสั้น: “เขียน Dockerfile → build เป็น Image → run เป็น Container”

### บทบาทไฟล์ในโปรเจ็กต์
- Dockerfile: ระบุวิธีสร้าง Image
  - FROM python:3.11-slim → ใช้ภาพฐาน Python เบา ๆ
  - COPY requirements.txt และ RUN pip install → ติดตั้งไลบรารี Python
  - COPY . . → คัดลอกไฟล์โปรเจ็กต์เข้า Image (ยกเว้นที่ถูกระบุใน .dockerignore)
  - EXPOSE 8000 → บอกว่าบริการฟังพอร์ต 8000 (เพื่ออ้างอิง)
  - CMD ["gunicorn", ..., "script:app"] → รัน Gunicorn โหลด Flask app ชื่อ `app` จากไฟล์ `script.py`

- docker-compose.yml: จัดวิธี “รัน” Container และบริการที่เกี่ยวข้อง
  - build: . → สร้าง Image จาก Dockerfile ในโฟลเดอร์นี้
  - ports: "8000:8000" → เปิดพอร์ต 8000 บนเครื่องไปยัง container:8000
  - env_file: .env → โหลดตัวแปรจากไฟล์ .env แล้ว “ฉีด” เข้าคอนเทนเนอร์ตอนรัน
  - volumes, extra_hosts, depends_on, networks → ตั้งค่าการแมปไฟล์/โฮสต์/เครือข่าย

- requirements.txt: รายการไลบรารี Python ที่แอปรันจริงต้องใช้ ใช้ในขั้นตอน build ของ Dockerfile

- .dockerignore: รายการไฟล์/โฟลเดอร์ที่ไม่ต้องส่งเข้า build context (เช่น .env, __pycache__/, build/)
  - เหตุผล: ลดขนาด image, เพิ่มความปลอดภัย (ไม่ฝัง secrets ลง Image)

- .env: เก็บค่า ENV สำหรับ “ตอนรัน” (runtime) เช่น LINE_CHANNEL_SECRET, REDIS_URL, MYSQL_* ฯลฯ
  - compose จะอ่านและส่งค่าเข้า container เมื่อ run (ผ่าน env_file)
  - .env ไม่ได้ถูกฝังใน Image ตาม best practice

### ลำดับเหตุการณ์เวลาเรียกใช้ docker compose up
1) Compose อ่าน docker-compose.yml ว่ามี services อะไรบ้าง (เช่น app, redis)
2) ถ้ามี build: . → สั่ง Docker สร้าง Image จาก Dockerfile (ใช้ cache เท่าที่เป็นไปได้)
3) สร้าง network ภายในสำหรับ container คุยกันเอง
4) รันแต่ละ service เป็น container:
   - ใส่ ENV (จาก env_file + environment)
   - แมป volumes/ports/extra_hosts
   - รัน CMD ของ container → Gunicorn import `script.py` แล้วใช้ตัวแปร `app`

### ลำดับความสำคัญของ Environment
- environment (ใน compose) > env_file (.env) > ENV ใน Dockerfile
- คีย์ซ้ำกัน ค่าจาก environment จะ override ค่าจาก env_file

### เครือข่าย/พอร์ต/โวลุ่ม แบบเข้าใจเร็ว
- ports: "8000:8000" → host:8000 → container:8000
- host.docker.internal → ชื่อพิเศษให้ container ติดต่อกลับเครื่อง host ได้ (สะดวกบน Windows/Mac)
- ถ้า Redis/MySQL เป็น service ใน compose เดียวกัน ให้ใช้ชื่อ service เป็นโฮสต์ได้ (เช่น redis:6379)
- volumes: ./tmp_uploads:/app/tmp_uploads → ไฟล์ใน container จะไปโผล่บนเครื่องคุณด้วย

### ทำไม .env ไม่ถูก “ฝัง” ลง Image
- เพื่อความปลอดภัยและความยืดหยุ่น: .env คือค่าที่เปลี่ยนตามสภาพแวดล้อม ควรส่งเข้า container ตอนรัน ไม่ควรถูก bake ลง image
- หากรันด้วย docker run (ไม่ใช้ compose) ให้ใช้ `--env-file .env` หรือ `--env KEY=VAL`

### กับดักที่พบบ่อย
- ใช้ `localhost` ใน .env สำหรับ MySQL/Redis ทั้งที่ตัวจริงรันบน host → ใน container, `localhost` คือ container เอง ให้ใช้ `host.docker.internal` หรือชื่อ service ใน network เดียวกัน
- รัน docker run โดยไม่ส่ง ENV → `script.py` จะฟ้องว่าไม่มี LINE_CHANNEL_* (ตั้งใจ fail-fast)
- ลืม recreate container หลังแก้ค่า → ใช้ค่าเก่าอยู่ แก้ด้วย `docker compose down && docker compose up -d --build --force-recreate`

### คำสั่งทดสอบเร็ว (PowerShell)
```powershell
# สร้าง/รันใหม่
docker compose down
docker compose up -d --build --force-recreate

# ตรวจค่า LINE_* ใน container
docker compose exec app printenv | findstr LINE_CHANNEL

# เช็คสุขภาพแอป
curl http://localhost:8000/health

# ทดสอบ Redis URL และ ping
docker compose exec app python -c "import os, redis; print(os.environ.get('REDIS_URL')); r=redis.Redis.from_url(os.environ['REDIS_URL']); print('PING=', r.ping())"

# ทดสอบ MySQL เชื่อมต่อ host
docker compose exec app python -c "import os, mysql.connector as mc; cfg=dict(host=os.environ['MYSQL_HOST'],port=int(os.environ['MYSQL_PORT']),user=os.environ['MYSQL_USER'],password=os.environ['MYSQL_PASSWORD'],database=os.environ['MYSQL_DATABASE']); conn=mc.connect(**cfg); print('MySQL connected:', conn.is_connected()); conn.close()"
```

### คำแนะนำค่าพื้นฐาน (กรณี Redis ใน Docker เดียวกัน, MySQL อยู่บน host)
- ถ้า Redis เปิดพอร์ต 6379 ไปยัง host แล้ว: `REDIS_URL=redis://host.docker.internal:6379/0`
- ถ้า Redis เป็น service ใน compose เดียวกัน: `REDIS_URL=redis://redis:6379/0`
- MySQL บน host เสมอ: `MYSQL_HOST=host.docker.internal`

ต้องการให้ผมเพิ่มตัวอย่างไฟล์ `.env` สำหรับเครื่องปลายทาง หรือ compose ที่เชื่อม external network กับ Redis ที่มีอยู่แล้ว แจ้งได้ครับ ผมจะเติมตัวอย่างให้พร้อมใช้งานทันที
