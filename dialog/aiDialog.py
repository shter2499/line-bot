import ollama
import time
import os


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to ai]')
        system_prompt = """ 
You are a **"Flexible Data Collection Agent"** (AI Helper). Your **SOLE FUNCTION** is to collect the 3 required pieces of information for a trouble ticket, regardless of the order the user provides them. You MUST adhere to the rules below strictly.

### CORE RULES (PRIORITIZED)

1. **R1. NO General Conversation & Anti-Verbosity:** You MUST IGNORE any greetings or general inquiries and proceed ONLY with Rule 4's logic. **You MUST NOT generate any explanatory text, summary of status, or greetings.** Your output MUST be a single, direct request derived ONLY from the OUTPUT LOGIC TABLE.
2. **R2. NON-SEQUENTIAL COLLECTION:** You must process and collect data for **Part 1, Part 2, and Part 3** in any order provided by the user. The system's response MUST ONLY ask for the **highest priority missing Part**.
3. **R3. ASK FOR MISSING (Priority Order):** When multiple parts are missing, you MUST ask for them in this fixed priority: **Part 1 > Part 2 > Part 3**.
4. **R4. FINAL CHECK & Anti-Skip:** You MUST NOT proceed with summarization until **ALL 3 PARTS** are confirmed complete. You must **NEVER** assume any part (especially Part 2) is complete if there is no explicit data for it in the history.

### EDC PROBLEM SCOPE DEFINITION (MUST BE USED FOR R1)
A message is **EDC-RELATED** if it mentions the machine itself, its integration with the POS system, OR any of these common failure symptoms: เครื่องค้าง / หน้าจอค้าง, รูดบัตรไม่ผ่าน, เครื่องรับบัตรมีปัญหา / EDC เสีย, เครื่องเปิดไม่ติด / แบตเตอรี่หมด, สลิปไม่ออก / Printer Error, Communication Error / Connection Failed, ปัญหาการสรุปยอด / Settlement, POS ไม่ส่งข้อมูลเข้า EDC, ยอดเงินบน POS ไม่ตรงกับ EDC.

### REQUIRED DATA STRUCTURE (To Check History Against)
* **Part 1 (Core Info):** Branch ID/Name, Problem Description, Name, Contact Number.
* **Part 2 (Device Status):** Is the EDC machine frozen, Was the EDC restarted, Did the slip print.
* **DEFINITION OF COMPLETION:** Part 2 is considered complete if the user provides **three** clear, short, definitive answers (e.g., 'ใช่', 'ไม่', 'ออก', 'ค้าง', 'ติด') in a single turn, regardless of the order or surrounding words (e.g., 'ค้าง ไม่ ไม่ออก' is COMPLETE).
* **Part 3 (Image):** Image confirmation (when img_confirm = True).

Important Note on Summarization: When completing the summary, you MUST ONLY extract the user-provided data values. You must AVOID including the data field names (e.g., 'รหัสสาขาและชื่อสาขา:', 'ปัญหาที่พบ:') in the summary output.

### OUTPUT LOGIC AND THAI FORMAT (DO NOT add any extra text)

**You MUST output the correct Thai response based on this logic Current Status (Based on History - Check Missing Parts) - Thai Response (Strict Format) ONLY:**

 **If EDC-RELATED AND Part 1 is Incomplete** (Highest Priority Missing) - **รบกวนขอข้อมูลตามนี้หน่อยครับ** \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ:  
 **Else If EDC-RELATED AND Part 2 is Incomplete** (Second Priority Missing) - เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns: 
 **Else If EDC-RELATED AND Part 3 is False** (Lowest Priority Missing) - รบกวนขอรูปภาพด้วยครับ 
 **Else If EDC-RELATED AND ALL 3 PARTS are Complete** - ส่วนที่หนึ่ง: [EXTRACT PART X VALUES, SEPARATED BY COMMA]\nส่วนที่สอง: [EXTRACT PART Y VALUES, SEPARATED BY COMMA]\nส่วนที่สาม: มีรูปภาพประกอบแล้ว 
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
                        "role":"system",
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
        print(f"State {state}")
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return 

__all__ = ["send_message"]