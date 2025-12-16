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


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to ai]')

        data = state.get("data") or {}
        current_state = {
            "part1_done": data.get("part1"),
            "part2_done": data.get("part2"),
            "img_confirm": data.get("part3"),
        }
        print("=" * 50)
        print(f"[send_message] current_state: {current_state}")
        print("=" * 50)
        context_msg = "CURRENT_STATE:\n" + json.dumps(current_state, ensure_ascii=False, indent=2)

        system_prompt = f"""
System:
คุณคือผู้ช่วยเก็บข้อมูลเคส EDC (ไม่ใช่แชทบอทคุยเล่น)
คุณต้องตัดสินใจจาก CURRENT_STATE เท่านั้น

CURRENT_STATE จะมี:
- part1_done: {bool(state.get("part1_done"))}
- part2_done: {bool(state.get("part2_done"))}
- img_confirm: {bool(state.get("img_confirm"))}

กติกาการตอบจะเลือกตอบทีละข้อที่เป็น False ห้ามตอบข้อความอย่างอื่นนอกจากข้อความที่ระบุไว้ในข้อ 1-4 เท่านั้น:

1) ถ้า part1_done เป็น false หรือข้อมูลที่ได้รับมาไม่ครบเช่น "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ: \nเบอร์ติดต่อ:" ให้ขอข้อมูลตามข้อความนี้ (ห้ามขอข้อมูลซ้ำและห้ามตอบอย่างอื่น):
   -  รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:

2) ถ้า part1_done เป็น true หรือข้อมูลที่ได้รับมาครบถ้วนเช่น "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา:1350 \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ:เอ \nเบอร์ติดต่อ:0812345678" ให้ขอข้อมูลตามข้อความนี้ (ห้ามขอข้อมูลซ้ำและห้ามตอบอย่างอื่น):
   -  เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:

3) ถ้า part2_done เป็น false ให้ขอข้อมูลตามข้อความนี้ (ห้ามขอข้อมูลซ้ำและห้ามตอบอย่างอื่น):
   -  เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:

4) ถ้า part1_done และ part2_done เป็น true ให้ขอข้อมูลตามข้อความนี้ (ห้ามขอข้อมูลซ้ำและห้ามตอบอย่างอื่น):
   -  รบกวนขอรูปภาพด้วยครับ

5) ถ้า img_confirm เป็น false ให้ตอบด้วยข้อความนี้เท่านั้น (ห้ามขอข้อมูลซ้ำและห้ามตอบอย่างอื่น):
   -  รบกวนขอรูปภาพด้วยครับ

ข้อสำคัญ:
- ห้ามถามซ้ำส่วนที่ทำเสร็จแล้ว (เช่น ถ้า part2_done เป็น true ห้ามถาม Part2 อีก)
- ห้ามทักทาย พูดคุย หรืออธิบายกติกา ให้ตอบตามข้อ 1-5 เท่านั้น
"""


        context_msg = "CURRENT_STATE:\n" + \
            json.dumps(current_state, ensure_ascii=False, indent=2)

        start = time.perf_counter()

        response = ollama.chat(
            model="qwen2.5:14b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": context_msg},
                {"role": "user", "content": message},
            ],
            options={"temperature": 0.2},
        )

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

ตัวอย่าง:
1) "บิลไม่ตัดครับ"
   -> {"part1": true, "part2": false, "part3": false}
2) "รหัสสาขา 123 สาขาสีลม"
   -> {"part1": true, "part2": false, "part3": false}
3) "ชื่อเอ เบอร์ 0812345678"
   -> {"part1": true, "part2": false, "part3": false}
4) "ค้าง ไม่ ไม่"
   -> {"part1": false, "part2": true, "part3": false}
5) "ส่วนที่สอง: เครื่อง EDC ค้างหรือไม่
Ans:ไม่ค้าง
Restart เครื่อง EDC หรือไม่
Ans:ไม่
สลิปจากเครื่องออกหรือไม่
Ans:ไม่
"

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
        print(f"Response CLASSIFIER: {response.message.content}")
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
   -> {"part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ**\nรหัสสาขาและชื่อสาขา:1234 สาขาสีลม\nปัญหาที่พบ:บิลไม่ตัด\nชื่อ:เอ\nเบอร์ติดต่อ: 0812345678"}
2) "เครื่องค้าง ใช่ รีสตาร์ท ไม่ สลิปออก ใช่" หรือ "ค้าง ไม่ ไม่"
    -> {"part2": "เครื่อง EDC ค้างหรือไม่\nAns:ใช่\nRestart เครื่อง EDC หรือไม่\nAns:ไม่\nสลิปจากเครื่องออกหรือไม่\nAns:ใช่"}
3) "บิลไม่ตัดครับ" (ต้องการข้อมูล part1 เพิ่มเติมเพราะมีแค่ปัญหาที่พบ)
   -> {"part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ:บิลไม่ตัดครับ \nชื่อ: \nเบอร์ติดต่อ:"}
4) "พพ ไม่ตัด 1234 เอ 0812345678"
   -> {"part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา:1234 \nปัญหาที่พบ:พพ ไม่ตัด \nชื่อ:เอ \nเบอร์ติดต่อ:0812345678"}
5) "เครดิตไม่ตัด 1234 แชมป์ 0812345678"
   -> {"part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา:1234 \nปัญหาที่พบ:เครดิตไม่ตัด \nชื่อ:แชมป์ \nเบอร์ติดต่อ:0812345678"}

ใน JSON ให้มีช่องดังนี้:
- "part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ:"  (ข้อความนี้มีข้อมูลส่วนของ Part1 ไหม เช่น สาขา ปัญหาที่พบ ชื่อ เบอร์โทร)
- "part2": "เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"  (ข้อความนี้มีข้อมูลส่วนของ Part2 ไหม เช่น เครื่องค้าง รีสตาร์ท สลิปออกไหม)

ตอบแค่ JSON ตามตัวอย่างนี้เท่านั้นโดยอิงจากข้อมูลที่ได้รับ:
{"part1": "**รบกวนขอข้อมูลตามนี้หน่อยครับ**\\nรหัสสาขาและชื่อสาขา: 123\\nปัญหาที่พบ:ปัญหาบิลไม่ตัด\\nชื่อ:เอ\\nเบอร์ติดต่อ:0812345678", "part2": "เครื่อง EDC ค้างหรือไม่\\nAns:ค้าง\\nRestart เครื่อง EDC หรือไม่\\nAns:ไม่\\nสลิปจากเครื่องออกหรือไม่\\nAns:ไม่"}
"""

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
            options={
                "temperature": 0.2,
            }
        )
        # res = response.json()

        end = time.perf_counter()
        print("=" * 50)
        print(f"Request took {end - start:.2f} seconds")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return


__all__ = ["send_message"]
