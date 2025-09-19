import requests
import json
import time

def send_message(message: str) -> str:
    print('Send request to OpenRouter.ai')
    system_prompt = """
    1.คำถามที่ไม่เกี่ยวกับการแจ้งปัญหาให้ตอบกลับเป็นการขอข้อมูลจากข้อ 2 เท่านั้นไม่ต้องพิมพ์อย่างอื่นเพิ่ม
    2.การตอบกลับปัญหาจะเป็นการแนะนำเบื้องต้นเท่านั้นและต้องขอข้อมูลลูกค้าแบบนี้เท่านั้น "** รบกวนขอข้อมูลตามนี้หน่อยครับ **\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:" ลูกค้าจะใส่หรือไม่ใส่หัวข้อก็ได้
    3.ในส่วนของรายละเอียดข้อมูลที่ลูกค้าใส่มา ห้ามเปลี่ยนแปลงรูปแบบของข้อมูลโดยเฉพาะ ชื่อสาขาหรือรหัสสาขา 
    4.ให้ใช้ศัพท์ที่กระชับเข้าใจง่าย ไม่ใช้ศัพท์เทคนิคและต้องใช้คำสุภาพ
    5.หากได้ข้อมูลครบถ้วนตามข้อ 2 ให้ขอรูปภาพประกอบปัญหาโดยพิมพ์ไปแบบนี้เท่านั้น "รบกวนขอรูปภาพด้วยครับ"
    """
    start = time.perf_counter()
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": "Bearer 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", #เมลหลัก
            # "Authorization": "Bearer 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", #เมลรอง
            "Content-Type": "application/json"
        },
        data=json.dumps({
            "model": "deepseek/deepseek-chat-v3.1:free",
            "messages": [
                {
                    "role": "user",
                    "content": message
                },
                {
                    "role": "system",
                    "content": system_prompt
                }
            ],

        })
    )
    res = response.json()

    end = time.perf_counter()
    # print("=" * 50)
    # print(f"Request took {end - start:.2f} seconds")
    # print(f"[AI RES] {res["choices"][0]["message"]["content"]}")
    # print("=" * 50)
    return res["choices"][0]["message"]["content"]

__all__ = ["send_message"]