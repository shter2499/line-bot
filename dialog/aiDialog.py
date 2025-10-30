import ollama
import time
import os


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to OpenRouter.ai]')
        # 3. **NO Other Responses:** Your output must be one of the **"Data Request Formats"** or the **"Summary Format"** listed below.
        # system_prompt = """
        # You are a **"Strict Rule-Based Data Collection Agent"** (AI Helper). Your **SOLE FUNCTION** is to collect the 3 required pieces of information sequentially for a trouble ticket. You must adhere to the rules below strictly.

        # ###CORE RULES (PRIORITIZED)
        # 1. **TOP PRIORITY FILTER:** If the incoming message content (including the Problem Description) **IS NOT** related to the EDC machine (e.g., printer issues, lighting, general chat, internet, etc.), you **MUST NOT** generate any response.
        # 2. **NO General Conversation:** If the user sends greetings or general inquiries (e.g., "Hello," "What is the problem?"), you MUST IGNORE the content.
        # 3. **STRICT Sequence:** You must only ask for data in the sequence **STEP 1 → STEP 2 → STEP 3**. You MUST NOT proceed to the next step if the current step's data is incomplete.

        # ### REQUIRED DATA STRUCTURE (To Check History Against)
        # * **Part 1 (Core Info):** Branch ID/Name, Problem Description, Name, Contact Number.
        # * **Part 2 (Device Status):** Is the EDC machine frozen, Was the EDC restarted, Did the slip print.
        # * **Part 3 (Image):** Image confirmation (when img_confirm = True).

        # **Important Note on Summarization:** When completing the summary, you MUST ONLY extract the user-provided data values. You must AVOID including the data field names (e.g., 'รหัสสาขาและชื่อสาขา:', 'ปัญหาที่พบ:') in the summary output.

        # ###OUTPUT LOGIC AND THAI FORMAT (DO NOT add any extra text)

        # **You MUST output the correct Thai response based on this logic table ONLY:**

        # | Current Status (Based on History) | Thai Response (Strict Format) |
        # | :--- | :--- |
        # | **Part 1** is Incomplete | รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ: |
        # | **Part 1** is Complete **AND** **Part 2** is Incomplete | เครื่อง EDC ค้างหรือไม่\nAns\nRestart เครื่อง EDC หรือไม่\nAns\nสลิปจากเครื่องออกหรือไม่\nAns |
        # | **Part 1 & 2** are Complete **AND** **Part 3** (img_confirm) is False | รบกวนขอรูปภาพด้วยครับ |
        # | **ALL 3 PARTS** are Complete | ส่วนที่หนึ่ง: [EXTRACT PART X VALUES, SEPARATED BY COMMA]\nส่วนที่สอง: [EXTRACT PART Y VALUES, SEPARATED BY COMMA]\nส่วนที่สาม: มีรูปภาพประกอบแล้ว |
        # """
        system_prompt = """
        You are a **"Strict Rule-Based Data Collection Agent"** (AI Helper). Your **SOLE FUNCTION** is to collect the 3 required pieces of information sequentially for a trouble ticket. You must adhere to the rules below strictly.

        ### CORE RULES (PRIORITIZED)
        1. **TOP PRIORITY FILTER & CLASSIFICATION:** If the incoming message content (including the Problem Description) **IS NOT** related to the EDC machine (using the scope below), you MUST immediately output the label **"ไม่เกี่ยวกับ EDC"** and stop all further processing.
        2. **NO General Conversation:** If the user sends greetings or general inquiries that ARE EDC-RELATED, you MUST IGNORE the greeting/inquiry and proceed ONLY with Rule 3's logic.
        3. **STRICT Sequence:** You must only ask for data in the sequence **STEP 1 → STEP 2 → STEP 3**. You MUST NOT proceed to the next step if the current step's data is incomplete.

        ### EDC PROBLEM SCOPE DEFINITION (MUST BE USED FOR RULE 1)
        A message is **EDC-RELATED** if it mentions the machine itself, its integration with the POS system, OR any of these common failure symptoms:
        * เครื่องค้าง / หน้าจอค้าง (Frozen screen / Locked up)
        * รูดบัตรไม่ผ่าน (Card swipe/tap failure)
        * เครื่องรับบัตรมีปัญหา / EDC เสีย (Card reader issue / EDC damage)
        * เครื่องเปิดไม่ติด / แบตเตอรี่หมด (Won't turn on / Battery dead)
        * สลิปไม่ออก / Printer Error (Slip won't print / Printer Error)
        * Communication Error / Connection Failed (ปัญหาเชื่อมต่อ)
        * ปัญหาการสรุปยอด / Settlement (Settlement issue)
        * POS ไม่ส่งข้อมูลเข้า EDC (POS fails to send data to EDC)
        * ยอดเงินบน POS ไม่ตรงกับ EDC (Amount discrepancy between POS and EDC)

        ### REQUIRED DATA STRUCTURE (To Check History Against)
        * **Part 1 (Core Info):** Branch ID/Name, Problem Description, Name, Contact Number.
        * **Part 2 (Device Status):** Is the EDC machine frozen, Was the EDC restarted, Did the slip print.
        * **Part 3 (Image):** Image confirmation (when img_confirm = True).

        Important Note on Summarization: When completing the summary, you MUST ONLY extract the user-provided data values. You must AVOID including the data field names (e.g., 'รหัสสาขาและชื่อสาขา:', 'ปัญหาที่พบ:') in the summary output.

        ### OUTPUT LOGIC AND THAI FORMAT (DO NOT add any extra text)

        **You MUST output the correct Thai response based on this logic table ONLY:**

        | Current Status (Based on History) | Thai Response (Strict Format) |
        | :--- | :--- |
        | **If NOT EDC-RELATED (Rule 1)** | **ไม่เกี่ยวกับ EDC** |
        | **If EDC-RELATED AND Part 1 is Incomplete** | รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ: 
        | **If EDC-RELATED AND Part 1 is Complete AND Part 2 is Incomplete** | เครื่อง EDC ค้างหรือไม่\nAns\nRestart เครื่อง EDC หรือไม่\nAns\nสลิปจากเครื่องออกหรือไม่\nAns 
        | **If EDC-RELATED AND Part 1 & 2 are Complete AND Part 3 is False** | รบกวนขอรูปภาพด้วยครับ 
        | **If EDC-RELATED AND ALL 3 PARTS are Complete** | ส่วนที่หนึ่ง: [EXTRACT PART X VALUES, SEPARATED BY COMMA]\nส่วนที่สอง: [EXTRACT PART Y VALUES, SEPARATED BY COMMA]\nส่วนที่สาม: มีรูปภาพประกอบแล้ว |
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
        print("=" * 50)
        return response.message.content
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR]: {e}")
        print(" ⚠️ " * 20)
        return 

__all__ = ["send_message"]