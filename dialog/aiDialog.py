import ollama
import time
import os


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to OpenRouter.ai]')
        system_prompt = """
        You are a **"Strict Rule-Based Data Collection Agent"** (AI Helper). Your **SOLE FUNCTION** is to collect the 3 required pieces of information sequentially for a trouble ticket. You must adhere to the rules below strictly.

        ### CORE RULES (PRIORITIZED)
        1. **NO General Conversation:** If the user sends greetings or general inquiries that ARE EDC-RELATED, you MUST IGNORE the greeting/inquiry and proceed ONLY with Rule 3's logic.
        2. **STRICT Sequence:** You must only ask for data in the sequence **STEP 1 → STEP 2 → STEP 3**. You MUST NOT proceed to the next step if the current step's data is incomplete.

        ### REQUIRED DATA STRUCTURE (To Check History Against)
        * **Part 1 (Core Info):** Branch ID/Name, Problem Description, Name, Contact Number.
        * **Part 2 (Device Status):** Is the EDC machine frozen, Was the EDC restarted, Did the slip print.
        * **Part 3 (Image):** Image confirmation (when img_confirm = True).

        Important Note on Summarization: When completing the summary, you MUST ONLY extract the user-provided data values. You must AVOID including the data field names (e.g., 'รหัสสาขาและชื่อสาขา:', 'ปัญหาที่พบ:') in the summary output.

        ### OUTPUT LOGIC AND THAI FORMAT (DO NOT add any extra text)

        **You MUST output the correct Thai response based on this logic table ONLY:**

        | Current Status (Based on History) | Thai Response (Strict Format) |
        | :--- | :--- |
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


def process_message(message: str,state: dict[str, any]) -> str:
    history = state.get('history') or []
    # print("=" * 50)
    # print(f"History: {history}")
    # print("=" * 50)
    try:
        print('[process_message by AI]')
        system_prompt = """
        You are a **"Strict Message Classifier"** (AI Helper). Your **SOLE FUNCTION** is to analyze the user's incoming message and strictly classify whether the information is related to the EDC machine, based on the following conditions:

        ### CLASSIFICATION CONDITIONS (STRICTLY OUTPUT IN THAI)
        1.  **NON-EDC (Irrelevant Data):** If the received information is definitively **NOT** related to the EDC machine, your response MUST be **"ไม่เกี่ยวกับ EDC"** ONLY. Immediately cease all further processing or conversation.
        2.  **EDC-RELATED (Relevant Data):** If the received information is definitively related to the EDC machine (e.g., specific known EDC error symptoms or clear mentions of the EDC machine), your response MUST be **"เกี่ยวกับ EDC"** ONLY.
        3.  **AMBIGUOUS/UNCLEAR/GENERALIZED (Uncertain Data):** If the information is uncertain, highly ambiguous, unclear, or relates to a generalized component (such as a printer that is **not specified** as an EDC printer), and polite **Thai question** asking the user to confirm if the reported issue is specifically with the EDC machine.

        ### OUTPUT LANGUAGE AND FORMAT
        * **Language:** ALL responses MUST be in Thai (ภาษาไทย).
        * **Format:** The output MUST be one of the three specified Thai phrases ONLY. Do not add any extra text or conversational elements.
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
                        "role":"system",
                        "content": f"History: {history}"
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