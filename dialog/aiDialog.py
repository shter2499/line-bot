import ollama
import time
import os
import json


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to ai]')
        system_prompt = """ 
System: 
คุณคือผู้ช่วย "ขอข้อมูลในส่วนที่ขาด" เท่านั้น
อ่านข้อความของผู้ใช้ 1 ข้อความ แล้วตอบเป็นข้อความที่ขาดหายไปที่ละส่วน ห้ามพูดอย่างอื่น

ตัวอย่าง:
1) "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ: \nเบอร์ติดต่อ:"
    part1 ->  "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ: \nเบอร์ติดต่อ:"
2) "เครื่อง EDC ค้างหรือไม่\nAns:ไม่\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"
    part2 ->  "เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"
3) img_confirm: False
    part3 ->  "รบกวนขอรูปภาพด้วยครับ"

ตอบทีละ part ตามตัวอย่างนี้เท่านั้นโดยอิงจากข้อมูลที่ได้รับ:
    ขาดข้อมูล part1 -> "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ: \nเบอร์ติดต่อ:"
    ขาดข้อมูล part2 -> "เครื่อง EDC ค้างหรือไม่\nAns:ไม่\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"
    ขาดข้อมูล part3 -> "รบกวนขอรูปภาพด้วยครับ"
 """

        history = state.get('history') or []
        image_paths = state.get('image_paths') or []
        img_confirm = state.get('img_confirm') or False

        # รวม history และ image_paths เข้าด้วยกัน
        combined_history = []
        for item in history:
            combined_history.append(str(item))

        # เพิ่มรูปภาพเข้าไปใน history (เอาแค่ชื่อไฟล์)

        if image_paths:
            filename = os.path.basename(image_paths[0])
            combined_history.append(filename)

        context_msg = f"""History: {combined_history} || img_confirm: {img_confirm}"""

        start = time.perf_counter()

        response = ollama.chat(
            model="qwen2.5:14b",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "system",
                    "content": context_msg
                },
                {
                    "role": "user",
                    "content": message
                },
            ],
            options={
                "temperature": 0.2,
            }
        )
        # res = response.json()

        end = time.perf_counter()
        print("=" * 50)
        print(f"Request took {end - start:.2f} seconds")
        print(f"Response: {response.message.content}")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return

def process_message(message: str, state: dict[str, any]) -> str:
    state_data = state.get('data') or []
    try:
        print('[process_message by AI]')
        system_prompt = """
System:
คุณเป็นตัวช่วย "แยกประเภทข้อความ" เท่านั้น
อ่านข้อความของผู้ใช้ 1 ข้อความ แล้วตอบเป็น JSON เท่านั้น ห้ามพูดอย่างอื่น

กติกาสำคัญ:
- ถ้าข้อความเกี่ยวกับโปรโมชั่น, ส่วนลด, สิทธิพิเศษ, คูปอง, บัตรสมาชิก, สแกนนิ้ว, สิทธิพนักงาน, จอทีวี, ใบเช็คเอ้าท์, ปริ้นเตอร์, เครื่องช้า
  ให้ตอบ {"part1": false, "part2": false} เสมอ
  ถึงแม้ข้อความนั้นจะมีฟอร์ม "** รบกวนขอข้อมูลตามนี้หน่อยครับ **" หรือมีคำว่า "รหัสสาขาและชื่อสาขา" ก็ตาม

ตัวอย่าง:
1) "บิลไม่ตัดครับ"
   -> {"part1": true, "part2": false}
2) "ชื่อเอ เบอร์ 0812345678"
   -> {"part1": true, "part2": false}
3) "ค้าง ไม่ ไม่"
   -> {"part1": false, "part2": true}
4) "ส่วนที่สอง: เครื่อง EDC ค้างหรือไม่
Ans:ไม่ค้าง
Restart เครื่อง EDC หรือไม่
Ans:ไม่
สลิปจากเครื่องออกหรือไม่
Ans:ไม่
"
    -> {"part1": false, "part2": true}
5) "สแกนจ่ายไม่เข้า"
    -> {"part1": true, "part2": false} 
6) "สแกนไม่เข้า 1 บิล"
    -> {"part1": true, "part2": false}

ข้อความที่ไม่เกี่ยวกับ part1/part2 เช่น ปัญหาโปรโมชั่น/สิทธิ์/สแกนนิ้ว/ปริ้นเตอร์/ใบเช็คเอ้าท์/จอทีวี/เครื่องช้า:
1) "สแกนนิ้วไม่ได้"
    -> {"part1": false, "part2": false}
2) "ปริ้นเตอร์"
    -> {"part1": false, "part2": false}
3) "ใบเช็คเอ้าท์"
    -> {"part1": false, "part2": false}
4) "สาขา5186 ระบบหน้าจอช้า+ค้างค่ะ"
    -> {"part1": false, "part2": false}
5) "ระบบช้า"
    -> {"part1": false, "part2": false}
6) "หน้าจอค้าง"
    -> {"part1": false, "part2": false}
7) "POS ช้า"
    -> {"part1": false, "part2": false}
8) "ใช้สิทธิ์ส่วนลดไม่ได้"
    -> {"part1": false, "part2": false}
9) "จอทีวีค้าง"
    -> {"part1": false, "part2": false}

ใน JSON ให้มีช่องดังนี้:
- "part1": true/false  (ข้อความนี้มีข้อมูลส่วนของ Part1 ไหม เช่น สาขา ปัญหาที่พบ ชื่อ เบอร์โทร)
- "part2": true/false  (ข้อความนี้มีข้อมูลส่วนของ Part2 ไหม เช่น เครื่องค้าง รีสตาร์ท สลิปออกไหม)

ตอบแค่ JSON ตามตัวอย่างนี้เท่านั้นโดยอิงจากข้อมูลที่ได้รับ:
{"part1": false, "part2": false}
"""

        start = time.perf_counter()

        response = ollama.chat(
            model="qwen2.5:14b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": f"state_data: {state_data}"},
                {"role": "user", "content": message},
            ],
            options={
                "temperature": 0.2,
            }
        )
        # res = response.json()

        end = time.perf_counter()
        print("=" * 50)
        print(f"Request took {end - start:.2f} seconds")
        print(f"message: {message}")
        print(f"Response process message: {response.message.content}")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return


def process_part(message: str, state: dict[str, any]) -> str:
    state_data = state.get('data') or []
    try:
        print('[process_message by AI]')
        system_prompt = """
System:
คุณเป็นตัวช่วย "เติมข้อความตาม part" เท่านั้น
อ่านข้อความของผู้ใช้ 1 ข้อความ แล้วตอบเป็น JSON เท่านั้น ห้ามพูดอย่างอื่น

ตัวอย่าง:
1) "1234 บิลไม่ตัด เอ เบอร์ 0812345678"
   -> {"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:1234 สาขาสีลม\nปัญหาที่พบ:บิลไม่ตัด\nชื่อ:เอ\nเบอร์ติดต่อ: 0812345678"}
2) "เครื่องค้าง ใช่ รีสตาร์ท ไม่ สลิปออก ใช่" หรือ "ค้าง ไม่ ไม่"
    -> {"part2": "เครื่อง EDC ค้างหรือไม่\nAns:ใช่\nRestart เครื่อง EDC หรือไม่\nAns:ไม่\nสลิปจากเครื่องออกหรือไม่\nAns:ใช่"}
3) "บิลไม่ตัดครับ" (ต้องการข้อมูล part1 เพิ่มเติมเพราะมีแค่ปัญหาที่พบ)
   -> {"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัด \nชื่อ: \nเบอร์ติดต่อ:"}
4) "พพ ไม่ตัด 1234 เอ 0812345678"
   -> {"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา:1234 \nปัญหาที่พบ:พพ ไม่ตัด \nชื่อ:เอ \nเบอร์ติดต่อ:0812345678"}
5) "เครดิตไม่ตัด 1234 แชมป์ 0812345678"
   -> {"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา:1234 \nปัญหาที่พบ:เครดิตไม่ตัด \nชื่อ:แชมป์ \nเบอร์ติดต่อ:0812345678"}
6) "1.EDC ค้างไหมครับ
Ans B
2.มีการ Restart EDC ไหมครับ
Ans B
3.สลิปที่เครื่อง EDC ออกไหมครับ
Ans A"
    -> {"part2": "เครื่อง EDC ค้างหรือไม่\nAns:ไม่\nRestart เครื่อง EDC หรือไม่\nAns:ไม่\nสลิปจากเครื่องออกหรือไม่\nAns:ใช่"}


ใน JSON ให้มีช่องดังนี้:
- "part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ:"  (ข้อความนี้มีข้อมูลส่วนของ Part1 ไหม เช่น สาขา ปัญหาที่พบ ชื่อ เบอร์โทร)
- "part2": "เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"  (ข้อความนี้มีข้อมูลส่วนของ Part2 ไหม เช่น เครื่องค้าง รีสตาร์ท สลิปออกไหม)

ตอบแค่ JSON ตามตัวอย่างนี้เท่านั้นโดยอิงจากข้อมูลที่ได้รับ:
{"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ\\nรหัสสาขาและชื่อสาขา: 123\\nปัญหาที่พบ: ปัญหาบิลไม่ตัด\\nชื่อ: เอ\\nเบอร์ติดต่อ: 0812345678", "part2": "เครื่อง EDC ค้างหรือไม่\\nAns:ค้าง\\nRestart เครื่อง EDC หรือไม่\\nAns:ไม่\\nสลิปจากเครื่องออกหรือไม่\\nAns:ไม่"}
"""
#         system_prompt = """
# System:
# คุณเป็นตัวช่วย "เติมข้อความตาม part" เท่านั้น
# อ่านข้อความของผู้ใช้ 1 ข้อความ แล้วตอบเป็น JSON เท่านั้น ห้ามพูดอย่างอื่น ห้ามขึ้นบรรทัดใหม่

# กติกา JSON (สำคัญมาก):
# - ต้องตอบเป็น JSON Object เดียวเท่านั้น
# - ต้องมี key "part1" และ "part2" เสมอ
# - ค่า "part1" และ "part2" ต้องเป็น object หรือ null เท่านั้น
# - ห้ามตอบ {} เปล่า ๆ เด็ดขาด

# ตัวอย่าง (สังเกตว่าทั้งหมดเป็น JSON ที่ใช้เครื่องหมาย double quote):
# 1) ข้อความ: "1234 บิลไม่ตัด เอ เบอร์ 0812345678"
#    ตอบ: {"part1": {"branch": "1234", "issue": "บิลไม่ตัด", "name": "เอ", "phone": "0812345678"}, "part2": null}
# 2) ข้อความ: "เครื่องค้าง ใช่ รีสตาร์ท ไม่ สลิปออก ใช่"
#    ตอบ: {"part1": null, "part2": {"freeze": "ใช่", "restart": "ไม่", "slip": "ใช่"}}
# 3) ข้อความ: "บิลไม่ตัดครับ"
#    ตอบ: {"part1": {"branch": "", "issue": "บิลไม่ตัดครับ", "name": "", "phone": ""}, "part2": null}
# 4) ข้อความ: "พพ ไม่ตัด 1234 เอ 0812345678"
#    ตอบ: {"part1": {"branch": "1234", "issue": "พพ ไม่ตัด", "name": "เอ", "phone": "0812345678"}, "part2": null}
# 5) ข้อความ: "เครดิตไม่ตัด 1234 แชมป์ 0812345678"
#    ตอบ: {"part1": {"branch": "1234", "issue": "เครดิตไม่ตัด", "name": "แชมป์", "phone": "0812345678"}, "part2": null}
# 6) ข้อความ: "พพไม่ตัด" หรือ "พพ ไม่ตัด"
#    ตอบ: {"part1": {"branch": "", "issue": "พพไม่ตัด", "name": "", "phone": ""}, "part2": null}

# รูปแบบผลลัพธ์ที่ต้องใช้ทุกครั้ง:
# - ถ้ามีแต่ข้อมูลส่วนที่ 1: {"part1": { ... }, "part2": null}
# - ถ้ามีแต่ข้อมูลส่วนที่ 2: {"part1": null, "part2": { ... }}
# - ถ้ามีทั้งสองส่วน: {"part1": { ... }, "part2": { ... }}
# - ถ้าไม่มีข้อมูลเลย: {"part1": null, "part2": null}

# ตอบแค่ JSON ตามรูปแบบด้านบนเท่านั้น ห้ามใส่คำอธิบายหรือข้อความอื่นเพิ่ม
# """
# {"part1": "รบกวนขอข้อมูลตามนี้หน่อยครับ\\nรหัสสาขาและชื่อสาขา: 123\\nปัญหาที่พบ:ปัญหาบิลไม่ตัด\\nชื่อ:เอ\\nเบอร์ติดต่อ:0812345678", "part2": "เครื่อง EDC ค้างหรือไม่\\nAns:ค้าง\\nRestart เครื่อง EDC หรือไม่\\nAns:ไม่\\nสลิปจากเครื่องออกหรือไม่\\nAns:ไม่"}

        start = time.perf_counter()

        response = ollama.chat(
            model="qwen2.5:14b",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "system",
                    "content": f"state_data: {state_data}"
                },
                {
                    "role": "user",
                    "content": message
                },
            ],
            # options={
            #     "temperature": 0.2,
            # }
        )
        # res = response.json()

        end = time.perf_counter()
        print("=" * 50)
        print(f"Request took {end - start:.2f} seconds")
        print(f"message: {message}")
        print(f"Response PART PROCESSOR: {response.message.content}")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return


def requester(data: str) -> str:
    try:
        print('[Send request to requester AI]')
        start = time.perf_counter()
        
        systemprompt = """คุณเป็นตัวช่วย "ขอข้อมูลที่ขาดหาย" เท่านั้น
อ่านข้อความของผู้ใช้ 1 ข้อความ แล้วตอบเป็นประโยคสั้นๆเท่านั้น

ตัวอย่าง:
1) "branch"
    -> "รบกวนขอรหัสสาขาและชื่อสาขาหน่อยครับ"
2) "issue"
    -> "รบกวนขอรายละเอียดปัญหาที่พบหน่อยครับ"
3) "name"
    -> "รบกวนขอชื่อผู้ติดต่อหน่อยครับ"
4) "phone"
    -> "รบกวนขอเบอร์ติดต่อไว้หน่อยครับ"
5) "freeze"
    -> "เครื่อง EDC ค้างไหมครับ"
6) "restart"
    -> "ได้มีการ Restart เครื่อง EDC ไหมครับ"
7) "slip"
    -> "สลิปที่เครื่อง EDC ออกไหมครับ"
    
ตอบแค่ประโยคสั้นๆตามตัวอย่างนี้ถ้าหากขาดข้อมูลหลายอย่างให้รวมประโยคสั้นๆเหล่านั้นเข้าด้วยกัน เช่น:
" branch, name" -> "รบกวนขอรหัสสาขาและชื่อผู้ติดต่อหน่อยครับ"
" issue, phone" -> "รบกวนขอรายละเอียดปัญหาที่พบและเบอร์ติดต่อไว้หน่อยครับ"
" freeze, restart" -> "เครื่อง EDC ค้าง กับ ได้มีการ Restart เครื่อง EDC ไหมครับ"
"""

        response = ollama.chat(
            model="qwen2.5:14b",
            messages=[
                {
                    "role": "system",
                    "content": systemprompt
                },
                {
                    "role": "user",
                    "content": data
                },
            ],
            options={
                "temperature": 0.2,
            }
        )
        # res = response.json()

        end = time.perf_counter()
        print("=" * 50)
        print(f"Request took {end - start:.2f} seconds")
        print(f"message: {data}")
        print(f"Response: {response.message.content}")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return

__all__ = ["send_message", "process_message", "process_part", "requester"]
