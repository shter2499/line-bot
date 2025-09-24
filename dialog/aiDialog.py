import requests
import json
import time

def send_message(message: str, state: dict[str, any]) -> str:
    print('[Send request to OpenRouter.ai]')

    system_prompt = """
    1.ตรวจสอบข้อความใน history ว่ามีข้อมูลตามที่กำหนดไว้ทั้งสามส่วนโดยส่วนแรก รหัสสาขาและชื่อสาขา, ปัญหาที่พบ, ชื่อ, เบอร์ติดต่อ ส่วนที่สอง เครื่อง EDC ค้างหรือไม่, Restart เครื่อง EDC หรือไม่, สลิปจากเครื่องออกหรือไม่ และส่วนที่สาม รูปภาพประกอบปัญหา ส่วนที่สาม รูปภาพประกอบปัญหา
    2.ให้ขอข้อมูลเพิ่มเติมหากมีส่วนไหนไม่ครบถ้วนโดยขอทีละส่วน โดยเริ่มจากส่วนไหนก่อนก็ได้ ถ้าหากใน history ส่วนใดส่วนหนึ่งแล้วให้ข้ามไปขอส่วนที่ยังไม่ครบแทน
    3.หากตรวจสอบใน history แล้วพบว่ามีข้อมูลครบทั้งสามส่วนเท่านั้น ให้ทวนข้อมูลทั้งสามส่วนในรูปแบบสั้นๆแบบนี้ "ส่วนที่หนึ่ง......\nส่วนที่สอง......\nส่วนที่สาม......" หากขาดส่วนใดส่วนหนึ่งไปให้ข้ามไปก่อน
    4.รูปแบบการขอข้อมูลส่วนที่หนึ่ง "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:" ตัวอย่างข้อมูลที่อาจจะได้มา "1024 เซ็นทรัลพระรามสาม", "EDC ไม่ตัดบิลลูกค้า", "พลอย", "0887654321"
    5.รูปแบบการขอข้อมูลส่วนที่สอง "เครื่อง EDC ค้างหรือไม่:\nAns\nRestart เครื่อง EDC หรือไม่:\nAns\nสลิปจากเครื่องออกหรือไม่:\nAns" ตัวอย่างข้อมูลที่อาจจะได้มา "ค้าง", "ไม่ค้าง", "ใช่", "ไม่ใช่"
    6.รูปแบบการขอข้อมูลส่วนที่สาม "รบกวนขอรูปภาพด้วยครับ"
    7.หากมีข้อความเชิงทักทาย สอบถามทั่วไป หรือ แจ้งปัญหาให้ตอบกลับสั้นๆเช่น "สวัสดีครับ", "ติดปัญหาด้านไหนครับ" หากข้อความเกี่ยวข้องกับทั้งสามส่วนให้ตอบกลับส่วนใดส่วนหนึ่งกลับไปก่อน
    """

    history = state.get('history') or []
    short_hist = [str(x) for x in history]
    image_paths = state.get('image_paths') or []
    image_count = len(image_paths)
    last_images = image_paths[-3:]  # keep it short
    context_msg = (
        f"History: {short_hist} | "
        f"Images(count={image_count}, last={last_images}) | "
    )
    print("=" * 50)
    print(f"context_msg: {context_msg}")
    print("=" * 50)



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
                },
                {
                    "role":"system",
                    "content": context_msg
                }
            ],
            "temperature": 0.5,
        })
    )
    res = response.json()

    end = time.perf_counter()
    print("=" * 50)
    print(f"Request took {end - start:.2f} seconds")
    print(f"[AI RES] {res["choices"][0]["message"]["content"]}")
    print("=" * 50)
    if res.get("choices") is None:
        print(" ⚠️ " * 20)
        print("[AI RES] content is None OR Used rate limit")
        print(" ⚠️ " * 20)
        return "ระบบมีปัญหา รอสักครู่ครับ"
    else:
        return res["choices"][0]["message"]["content"]

__all__ = ["send_message"]