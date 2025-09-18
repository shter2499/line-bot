import ollama
import json
import os


prompt_txt = """ตรวจสลิปการโอนว่าเป็นธนาคารอะไร โอนเวลาไหนวันที่เท่าไหร่"""
path_img = "C:/Users/Asus/Desktop/Work/case/line_oa_chat_250902_093849.jpg"

def process_slip():
    try:
        print("[INFO] Sending request to Ollama...")
        if not os.path.exists(path_img):
            print(f"[ERROR] Image file not found. {path_img}")
        else:
            print(f"[Found] {path_img}")
            print(f"[INFO] Sending request to Ollama...")
        response = ollama.chat(
            model="scb10x/typhoon-ocr-3b:latest",
            messages=[
                {
                    "role": "user", 
                    "content": prompt_txt,
                    "images": [path_img]
                }
            ]
        )
        txt_res = json.loads(response.message.content)
        # print('*'*50)
        # print(f"[Response] {txt_res['natural_text']}")
        # print(f"[Response type] {txt_res.split('content=')[1]}")
        # print('*'*50)
    except Exception as e:
        print(f"[ERROR] {e}")

process_slip()