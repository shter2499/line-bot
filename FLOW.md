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
