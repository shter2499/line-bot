import os
import imghdr
import time

from dotenv import load_dotenv
from flask import Flask, request, abort, Response

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

from dialog.edcDialog import process_step_message, process_image_message, set_reply_callback

load_dotenv()

app = Flask(__name__)
def _mask_len(v: str | None) -> str:
    if not v:
        return "<missing>"
    try:
        return f"<provided:{len(v)} chars>"
    except Exception:
        return "<provided>"

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
print(f"[access token] {CHANNEL_ACCESS_TOKEN}")
print(f"[channel secret] {CHANNEL_SECRET}")

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
        # เช็คว่า token นี้ถูกใช้ไปแล้วหรือไม่
        with _lock:
            if token in _used_tokens:
                print(f"[SKIP] Token {token[:8]}... already used")
                return
            _used_tokens[token] = time.time()
            
            # Cleanup old tokens (เก็บแค่ 100 ตัวล่าสุด)
            if len(_used_tokens) > 100:
                now = time.time()
                expired = [t for t, ts in _used_tokens.items() if now - ts > 300]  # เก่ากว่า 5 นาที
                for t in expired:
                    del _used_tokens[t]
        
        print(f"[CHECK REPLY] token: {token[:8]}..., text: {text}")
        try:
            line_bot_api.reply_message(token, TextSendMessage(text=text))
        except Exception as e:
            print("[EMPTY REPLY]")
    try:
        set_reply_callback(_reply)
    except Exception as e:
        print(f"[ERROR] set_reply_callback failed: {e}")


_register_reply_callback()


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
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[ERROR] Invalid signature -> ตรวจสอบ Channel Secret / Access Token")
        abort(400)
    return 'OK'

# รับข้อความ
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = (event.message.text or '').strip()

    if event.source.type == "user":
        user_id = event.source.user_id
    else:
        group_key = getattr(event.source, f"{event.source.type}_id", "")
        user_id = f"{event.source.type}:{group_key}:{getattr(event.source, 'user_id', '')}"

    reply_message = process_step_message(
        user_id, user_message, reply_token=event.reply_token)
    # Silent mode: only reply when we have something to say
    if reply_message is not None:
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_message)
            )
        except Exception as e:
            print(f"[ERROR] reply_message failed: {e}")

# รับรูปภาพ
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if event.source.type == "user":
        user_id = event.source.user_id
    else:
        group_key = getattr(event.source, f"{event.source.type}_id", "")
        user_id = f"{event.source.type}:{group_key}:{getattr(event.source, 'user_id', '')}"

    try:
        file_path = _download_line_image(event.message.id)
    except Exception as e:
        print(f"[ERROR] image download failed: {e}")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="ไม่สามารถดาวน์โหลดรูปได้ค่ะ ลองใหม่อีกครั้ง"))
        except Exception as ee:
            print(f"[ERROR] reply fail after download error: {ee}")
        return

    ack = process_image_message(
        user_id, file_path, reply_token=event.reply_token)
    # If ack is None, we'll reply later (after 5s debounce) using the stored reply_token
    if ack is not None:
        try:
            line_bot_api.reply_message(
                event.reply_token, TextSendMessage(text=ack))
        except Exception as e:
            print(f"[ERROR] reply_image_message failed: {e}")


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
    # For local development only; production should use Gunicorn
    port = int(os.environ.get("PORT", "8000"))
    debug = bool(os.environ.get("FLASK_DEBUG"))
    print(f"Starting dev server on port {port} (debug={debug}) ...")
    app.run(host="0.0.0.0", port=port, debug=debug)
