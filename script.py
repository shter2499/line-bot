import os
import imghdr
import time
from threading import Semaphore

from dotenv import load_dotenv
from flask import Flask, request, abort, Response, jsonify

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

from dialog.edcDialog import process_step_message, process_image_message, set_reply_callback
from cuda_queue import get_cuda_queue_manager

load_dotenv()

app = Flask(__name__)

# จำกัดจำนวน requests พร้อมกันไม่เกิน 3 requests
request_semaphore = Semaphore(3)

def _mask_len(v: str | None) -> str:
    if not v:
        return "<missing>"
    try:
        return f"<provided:{len(v)} chars>"
    except Exception:
        return "<provided>"

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
# print(f"[access token] {CHANNEL_ACCESS_TOKEN}")
# print(f"[channel secret] {CHANNEL_SECRET}")

if not CHANNEL_ACCESS_TOKEN or CHANNEL_ACCESS_TOKEN.startswith("YOUR_"):
    raise RuntimeError(
        "LINE_CHANNEL_ACCESS_TOKEN ไม่ถูกตั้งค่า หรือยังเป็นค่า placeholder. "
        "โปรดตรวจสอบว่า container ได้รับค่า ENV ผ่าน env_file (.env) หรือ --env/--env-file แล้ว")
if not CHANNEL_SECRET or CHANNEL_SECRET.startswith("YOUR_"):
    raise RuntimeError(
        "LINE_CHANNEL_SECRET ไม่ถูกตั้งค่า หรือยังเป็นค่า placeholder. "
        "โปรดตรวจสอบว่า container ได้รับค่า ENV ผ่าน env_file (.env) หรือ --env/--env-file แล้ว")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Register reply callback used by auto-submit to respond with stored reply_token


def _register_reply_callback():
    def _reply(token: str, text: str):
        # print(f"[_reply_callback] token={token}, text={text}")
        try:
            line_bot_api.reply_message(token, TextSendMessage(text=text))
        except Exception as e:
            print("=" * 50)
            print(f"[EMPTY REPLY] {e}")
            print("=" * 50)
    try:
        set_reply_callback(_reply)
    except Exception as e:
        print(f"[ERROR] set_reply_callback failed: {e}")


_register_reply_callback()


def _check_cuda_memory():
    """ตรวจสอบและรายงานการใช้ CUDA memory"""
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1024**2  # MB
            reserved = torch.cuda.memory_reserved() / 1024**2    # MB
            total = torch.cuda.get_device_properties(0).total_memory / 1024**2  # MB
            print(f"[CUDA] Allocated: {allocated:.2f} MB | Reserved: {reserved:.2f} MB | Total: {total:.2f} MB")
            
            # ถ้า memory ใช้เกิน 80% ให้ล้าง cache
            if allocated > (total * 0.8):
                print("[CUDA] Memory usage > 80%, clearing cache...")
                torch.cuda.empty_cache()
                print(f"[CUDA] Cache cleared. New allocated: {torch.cuda.memory_allocated() / 1024**2:.2f} MB")
        else:
            print("[CUDA] CUDA not available, using CPU")
    except ImportError:
        print("[CUDA] PyTorch not installed, cannot check GPU memory")
    except Exception as e:
        print(f"[CUDA] Error checking memory: {e}")


@app.before_request
def _log_request():
    # Log ทุก request ที่เข้า ช่วยดีบักเวลาตั้ง Webhook
    print(f"[REQ] {request.method} {request.path}")


@app.route('/', methods=['GET', 'POST'])
def root():
    if request.method == 'POST':
        return "Posted to /. Did you set Webhook URL to /callback ?", 200
    return "Running. LINE should POST /callback", 200


@app.route('/health', methods=['GET'])
def health():
    return "OK", 200


@app.route("/callback", methods=['POST'])
def callback():
    # ปิดการรับข้อความจาก LINE Messaging API
    # ใช้ /api/message แทน
    print("[INFO] /callback disabled - use /api/message instead")
    return 'OK'
    
    # signature = request.headers.get('X-Line-Signature', '')
    # body = request.get_data(as_text=True)
    # try:
    #     handler.handle(body, signature)
    # except InvalidSignatureError:
    #     print("[ERROR] Invalid signature -> ตรวจสอบ Channel Secret / Access Token")
    #     abort(400)
    # return 'OK'


# Web API endpoint สำหรับรับข้อมูลจากหน้าเว็บในรูปแบบ LINE webhook
@app.route('/api/message', methods=['POST'])
def web_message():
    """
    รับข้อมูลจากหน้าเว็บในรูปแบบ LINE Messaging API webhook format
    
    Expected format (same as LINE webhook):
    {
      "events": [
        {
          "type": "message",
          "replyToken": "optional_token",
          "source": {
            "userId": "web_user_123",
            "type": "user"
          },
          "message": {
            "type": "text",
            "id": "message_id",
            "text": "ข้อความ"
          }
        }
      ]
    }
    
    For image messages:
    {
      "events": [
        {
          "type": "message",
          "replyToken": "optional_token",
          "source": {
            "userId": "web_user_123",
            "type": "user"
          },
          "message": {
            "type": "image",
            "id": "message_id",
            "contentProvider": {
              "type": "external",
              "originalContentUrl": "base64://..." or "http://..."
            }
          }
        }
      ]
    }
    """
    # ลอง acquire semaphore (non-blocking)
    # ถ้าไม่ได้ = มี request มากกว่า 3 ตัวกำลังทำงานอยู่
    if not request_semaphore.acquire(blocking=False):
        print("[API] ⚠️ Server busy - too many concurrent requests (max: 3)")
        return jsonify({
            "status": "error", 
            "message": "เซิร์ฟเวอร์กำลังประมวลผลคำขออื่นอยู่ กรุณารอสักครู่แล้วลองใหม่อีกครั้ง",
            "code": "SERVER_BUSY"
        }), 503
    
    try:
        # เช็ค CUDA memory ก่อนประมวลผล
        _check_cuda_memory()
        
        import json
        
        # รับ body เป็น JSON
        body = request.get_data(as_text=True)
        print(f"[API] Received request: {body[:200]}...")  # แสดง 200 ตัวอักษรแรก
        
        data = json.loads(body)
        
        # รองรับทั้งแบบมี events array และแบบ event เดี่ยว
        if 'events' in data:
            # รูปแบบ LINE webhook standard: {"events": [...]}
            events = data.get('events', [])
        elif 'type' in data:
            # รูปแบบ event เดี่ยว: {"type": "message", "message": {...}}
            events = [data]
        else:
            print(f"[API] Invalid format: {data}")
            return jsonify({"status": "error", "message": "Invalid request format"}), 400
        
        if not events:
            print("[API] No events found in request")
            return jsonify({"status": "error", "message": "No events found"}), 400
        
        for event_data in events:
            print(f"[API] Processing event: {event_data.get('type')}")
            
            # ประมวลผล message event
            if event_data.get('type') == 'message':
                msg_type = event_data.get('message', {}).get('type')
                
                if msg_type == 'text':
                    # ประมวลผลข้อความ
                    user_id = event_data.get('source', {}).get('userId', 'web:unknown')
                    text = event_data.get('message', {}).get('text', '')
                    reply_token = event_data.get('replyToken')
                    
                    print(f"[API] Text message from {user_id}: {text}")
                    
                    process_step_message(user_id, text, reply_token=reply_token)
                    
                elif msg_type == 'image':
                    # ประมวลผลรูปภาพ
                    user_id = event_data.get('source', {}).get('userId', 'web:unknown')
                    message_id = event_data.get('message', {}).get('id', '')
                    reply_token = event_data.get('replyToken')
                    
                    print(f"[API] Image message from {user_id}")
                    
                    # ตรวจสอบว่ามี lineContentUrl (รูปแบบจาก LINE API)
                    line_content_url = event_data.get('lineContentUrl')
                    
                    if line_content_url:
                        # ดาวน์โหลดรูปจาก LINE API
                        print(f"[API] Downloading from LINE API: {message_id}")
                        try:
                            file_path = _download_line_image(message_id)
                            print(f"[API] Image downloaded: {file_path}")
                            
                            process_image_message(user_id, file_path, reply_token=reply_token)
                            
                            print(f"[API] Image processed")
                        except Exception as e:
                            print(f"[ERROR] Failed to download LINE image: {e}")
                    
                    else:
                        # รับรูปภาพจาก contentProvider (รูปแบบเดิม)
                        content_provider = event_data.get('message', {}).get('contentProvider', {})
                        
                        if content_provider.get('type') == 'external':
                            original_url = content_provider.get('originalContentUrl', '')
                            
                            # ถ้าเป็น base64
                            if original_url.startswith('base64://'):
                                import base64
                                base64_data = original_url.replace('base64://', '')
                                
                                os.makedirs("tmp_uploads", exist_ok=True)
                                timestamp = int(time.time())
                                tmp_path = os.path.join("tmp_uploads", f"{timestamp}_{message_id}.bin")
                                
                                with open(tmp_path, 'wb') as f:
                                    f.write(base64.b64decode(base64_data))
                                
                                print(f"[API] Saved base64 image to {tmp_path}")
                                
                                # ตรวจสอบชนิดรูป
                                kind = imghdr.what(tmp_path)
                                if kind:
                                    final_path = os.path.join(
                                        "tmp_uploads", 
                                        f"{timestamp}_{message_id}.{'jpg' if kind == 'jpeg' else kind}"
                                    )
                                    os.replace(tmp_path, final_path)
                                    
                                    print(f"[API] Image type: {kind}, final path: {final_path}")
                                    
                                    process_image_message(user_id, final_path, reply_token=reply_token)
                                    
                                    print(f"[API] Image processed")
                                else:
                                    print(f"[API] Invalid image file")
                                    try:
                                        os.remove(tmp_path)
                                    except OSError:
                                        pass
                            
                            # ถ้าเป็น URL (ต้อง download)
                            elif original_url.startswith('http'):
                                import requests
                                
                                print(f"[API] Downloading image from {original_url}")
                                
                                response = requests.get(original_url)
                                if response.status_code == 200:
                                    os.makedirs("tmp_uploads", exist_ok=True)
                                    timestamp = int(time.time())
                                    tmp_path = os.path.join("tmp_uploads", f"{timestamp}_{message_id}.bin")
                                    
                                    with open(tmp_path, 'wb') as f:
                                        f.write(response.content)
                                    
                                    kind = imghdr.what(tmp_path)
                                    if kind:
                                        final_path = os.path.join(
                                            "tmp_uploads", 
                                            f"{timestamp}_{message_id}.{'jpg' if kind == 'jpeg' else kind}"
                                        )
                                        os.replace(tmp_path, final_path)
                                        
                                        print(f"[API] Downloaded image, type: {kind}")
                                        
                                        process_image_message(user_id, final_path, reply_token=reply_token)
                                        
                                        print(f"[API] Image processed")
                                    else:
                                        print(f"[API] Invalid image file")
                                        try:
                                            os.remove(tmp_path)
                                        except OSError:
                                            pass
                                else:
                                    print(f"[API] Failed to download image: {response.status_code}")
        
        print(f"[API] Processing complete")
        return 'OK', 200
    
    except Exception as e:
        print(f"[ERROR] web_message failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    
    finally:
        # ปล่อย semaphore เพื่อให้ request ถัดไปสามารถเข้ามาได้
        request_semaphore.release()
        print("[API] ✓ Request slot released")


# รับข้อความ (ปิดการใช้งาน - ใช้ /api/message แทน)
# @handler.add(MessageEvent, message=TextMessage)
# def handle_message(event):
#     user_message = (event.message.text or '').strip()
#
#     if event.source.type == "user":
#         user_id = event.source.user_id
#     else:
#         group_key = getattr(event.source, f"{event.source.type}_id", "")
#         user_id = f"{event.source.type}:{group_key}:{getattr(event.source, 'user_id', '')}"
#
#     reply_message = process_step_message(user_id, user_message, reply_token=event.reply_token)
#     # Silent mode: only reply when we have something to say
#     if reply_message is not None:
#         try:
#             line_bot_api.reply_message(
#                 event.reply_token,
#                 TextSendMessage(text=reply_message)
#             )
#         except Exception as e:
#             print(f"[ERROR] reply_message failed: {e}")

# รับรูปภาพ (ปิดการใช้งาน - ใช้ /api/message แทน)
# @handler.add(MessageEvent, message=ImageMessage)
# def handle_image(event):
#     user_id = ""
#     if event.source.type == "user":
#         user_id = event.source.user_id
#     else:
#         group_key = getattr(event.source, f"{event.source.type}_id", "")
#         user_id = f"{event.source.type}:{group_key}:{getattr(event.source, 'user_id', '')}"
#
#     try:
#         file_path = _download_line_image(event.message.id)
#     except Exception as e:
#         print(f"[ERROR] image download failed: {e}")
#         try:
#             line_bot_api.reply_message(event.reply_token, TextSendMessage(
#                 text=""))
#             print("[INFO] replied empty message after download error")
#         except Exception as ee:
#             print(f"[ERROR] reply fail after download error: {ee}")
#         return
#
#     ack = process_image_message(user_id, file_path, reply_token=event.reply_token)
#     # If ack is None, we'll reply later (after 5s debounce) using the stored reply_token
#     if ack is not None:
#         try:
#             line_bot_api.reply_message(
#                 event.reply_token, TextSendMessage(text=ack))
#         except Exception as e:
#             print(f"[ERROR] reply_image_message failed: {e}")


def _download_line_image(message_id: str) -> str:
    try:
        content_resp = line_bot_api.get_message_content(message_id)
    except Exception as e:
        raise RuntimeError(f"get_message_content failed: {e}")

    os.makedirs("tmp_uploads", exist_ok=True)
    tmp_raw_path = os.path.join("tmp_uploads", f"{message_id}.bin")
    with open(tmp_raw_path, "wb") as f:
        for chunk in content_resp.iter_content():
            f.write(chunk)

    # ตรวจชนิดรูป
    kind = imghdr.what(tmp_raw_path)
    if not kind:
        try:
            os.remove(tmp_raw_path)
        except OSError:
            pass
        raise RuntimeError("file is not a recognized image")

    # เปลี่ยนชื่อเป็นนามสกุลที่ถูกต้อง
    final_path = os.path.join(
        "tmp_uploads", f"{int(time.time())}_{message_id}.{'jpg' if kind == 'jpeg' else kind}"
    )
    os.replace(tmp_raw_path, final_path)
    return final_path


@app.errorhandler(404)
def _not_found(e):  # ช่วยชี้ว่าถูกยิง path ผิด (มักลืม /callback)
    print(f"[404] {request.path}")
    return "Not Found", 404

if __name__ == "__main__":
    # Start CUDA queue manager worker thread
    cuda_manager = get_cuda_queue_manager()
    cuda_manager.start()
    print("CUDA queue manager started")
    
    # For local development only; production should use Gunicorn
    port = int(os.environ.get("PORT", "8000"))
    debug = bool(os.environ.get("FLASK_DEBUG"))
    print(f"Starting dev server on port {port} (debug={debug}) ...")
    
    try:
        app.run(host="0.0.0.0", port=port, debug=debug)
    finally:
        # Stop queue manager on shutdown
        cuda_manager.stop()
        print("CUDA queue manager stopped")
