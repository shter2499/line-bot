import requests
import json
import ollama
import time
import os


def send_message(message: str, state: dict[str, any]) -> str:
    try:
        print('[Send request to OpenRouter.ai]')

        system_prompt = """
        You are a **"Strict Rule-Based Data Collection Agent"** (AI Helper). Your **SOLE FUNCTION** is to collect the 3 required pieces of information sequentially for a trouble ticket. You must adhere to the rules below strictly.

        ###CORE RULES (PRIORITIZED)
        1. **NO General Conversation:** If the user sends greetings or general inquiries (e.g., "Hello," "What is the problem?"), you MUST IGNORE the content and proceed ONLY with Rule 3's logic.
        2. **NO Other Responses:** Your output must be one of the **"Data Request Formats"** or the **"Summary Format"** listed below.
        3. **STRICT Sequence:** You must only ask for data in the sequence **STEP 1 → STEP 2 → STEP 3**. You MUST NOT proceed to the next step if the current step's data is incomplete.

        ### REQUIRED DATA STRUCTURE (To Check History Against)
        * **Part 1 (Core Info):** Branch ID/Name, Problem Description, Name, Contact Number.
        * **Part 2 (Device Status):** Is the EDC machine frozen, Was the EDC restarted, Did the slip print.
        * **Part 3 (Image):** Image confirmation (when img_confirm = True).

        **Important Note on Summarization:** When completing the summary, you MUST ONLY extract the user-provided data values. You must AVOID including the data field names (e.g., 'รหัสสาขาและชื่อสาขา:', 'ปัญหาที่พบ:') in the summary output.

        ###OUTPUT LOGIC AND THAI FORMAT (DO NOT add any extra text)

        **You MUST output the correct Thai response based on this logic table ONLY:**

        | Current Status (Based on History) | Thai Response (Strict Format) |
        | :--- | :--- |
        | **Part 1** is Incomplete | รบกวนขอข้อมูลตามนี้หน่อยครับ \nรหัสสาขาและชื่อสาขา: \nปัญหาที่พบ: \nชื่อ: \nเบอร์ติดต่อ: |
        | **Part 1** is Complete **AND** **Part 2** is Incomplete | เครื่อง EDC ค้างหรือไม่\nAns\nRestart เครื่อง EDC หรือไม่\nAns\nสลิปจากเครื่องออกหรือไม่\nAns |
        | **Part 1 & 2** are Complete **AND** **Part 3** (img_confirm) is False | รบกวนขอรูปภาพด้วยครับ |
        | **ALL 3 PARTS** are Complete | ส่วนที่หนึ่ง: [EXTRACT PART X VALUES, SEPARATED BY COMMA]\nส่วนที่สอง: [EXTRACT PART Y VALUES, SEPARATED BY COMMA]\nส่วนที่สาม: มีรูปภาพประกอบแล้ว |
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
        # response = requests.post(
        #     url="https://openrouter.ai/api/v1/chat/completions",
        #     headers={
        #         # "Authorization": "Bearer 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", #เมลหลัก
        #         # "Authorization": "Bearer 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", #เมลรอง
        #         "Authorization": "Bearer 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", #เมลรองอีกอัน
        #         "Content-Type": "application/json"
        #     },
        #     data=json.dumps({
        #         "model": "deepseek/deepseek-chat-v3.1:free",
        #         "messages": [
        #             {
        #                 "role": "system",
        #                 "content": system_prompt
        #             },
        #             {
        #                 "role":"system",
        #                 "content": context_msg
        #             },
        #             {
        #                 "role": "user",
        #                 "content": message
        #             },
        #         ],
        #         "temperature": 0.2,
        #     })
        # )

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