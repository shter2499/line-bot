"""
State management now uses Redis via session.RedisSession instead of in-memory dict.
- Session TTL is enforced by Redis; no manual _expire needed. ✅
- Timers are managed in-process per instance (stored outside Redis) as they are not JSON-serializable.
"""
from __future__ import annotations

from sympy import false
from fetchData.fetch import fetch, uploadFile, fetch_store, search_duplicate
from dialog.aiDialog import send_message, process_message
import predict_classifier
import predict_cr_classifier
import predict_image_edc
from session import RedisSession

import os
import re
import time
import threading
import json
from PIL import Image
from typing import Dict, Optional, Callable


SESSION_TIMEOUT_SEC = 600
_reply_cb: Optional[Callable[[str, str], None]] = None
_redis: Optional[RedisSession] = None
_timers: Dict[str, threading.Timer] = {}


def _get_redis() -> RedisSession:
    global _redis
    if _redis is None:
        # Use environment-driven configuration from session.RedisSession
        # This respects REDIS_URL / REDIS_HOST / REDIS_PORT inside Docker
        _redis = RedisSession()
    return _redis


def _default_state(uid: str) -> Dict:
    return {
        "step": 0,
        "answers": [],
        "edc_answers": [],
        "updated": time.time(),
        "uid": uid,
        "image_paths": [],
        "history": [],
        "context_confirm": False,
        "img_confirm": False,
        "edc_confirm": False
    }


def _load_state(uid: str) -> Optional[Dict]:
    try:
        data = _get_redis().get(uid)
        return data
    except Exception as e:
        print(f"[ERROR] load state failed for {uid}: {e}")
        return None


def _save_state(uid: str, state: Dict) -> None:
    try:
        state["updated"] = time.time()
        _get_redis().save(uid, state)
    except Exception as e:
        print(f"[ERROR] save state failed for {uid}: {e}")


def _delete_state(uid: str) -> None:
    try:
        _get_redis().delete(uid)
    except Exception as e:
        print(f"[ERROR] delete state failed for {uid}: {e}")


def set_reply_callback(cb: Callable[[str, str], None]) -> None:
    """Register a callback used to reply later using a stored reply_token.

    cb will be called as cb(reply_token, text).
    """
    global _reply_cb
    _reply_cb = cb


def _start(uid: str):
    st = _default_state(uid)
    _save_state(uid, st)
    return st


def _clear(uid: str):
    # cancel local timer if exists
    t = _timers.pop(uid, None)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    _delete_state(uid)


def _auto_reply(user_id: str):
    state = _load_state(user_id)
    if not state:
        return
    if state.get("image_paths")[0] not in state["history"] and not state.get("context_confirm"):
        state["history"].append(state.get("image_paths")[0])
        _save_state(user_id, state)
        _reply_cb(state.get("reply_token", ""),
                  "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
        return

    res = send_message("ห้ามขอรูปซ้ำอีก", state)
    if state.get("context_confirm") and "ส่วนที่หนึ่ง:" in res:
        _summary(state, res)
    else:
        # _reply_cb(state.get("reply_token", ""), res)
        _reply_cb(state.get("reply_token", ""), "")


def _schedule_auto_submit(user_id: str, delay_sec: float = 5.0):
    old = _timers.get(user_id)
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t = threading.Timer(delay_sec, _auto_reply, args=(user_id,))
    t.daemon = True
    _timers[user_id] = t
    t.start()


def _summary(state: Dict, txt) -> str:
    image_paths = state.get('image_paths', [])
    user_id = state.get("uid")
    state = _load_state(user_id)
    result = find_branch(txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0])
    branch = result["site_name"] if result else None
    standard = result["standard"] if result else None
    company = result["company_name"] if result else None
    print("=" * 50)
    print(f"[BRANCH FOUND] {branch}, {standard}, {company}")
    print("=" * 50)
    header = parse_header(txt.split("ส่วนที่สอง:")[1].split('\n')[0])
    # dup = search_duplicate(branch)

    # if dup["response_status"][0]["status_code"] == 2000 and dup['list_info']['total_count'] > 0:
    #     _reply_cb(state.get("reply_token", ""),
    #               f"สาขาได้แจ้งงานมาแล้วครับ Ticket {dup['requests'][0]['id']}")
    #     _clear(user_id)
    #     return
    try:
        detail = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[1]
        user = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[2]
        phone = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[3].split("\n")[0]
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR] parsing answers failed: {e}")
        print(" ⚠️ " * 20)
        return "ระบบมีปัญหา กรุณารอสักครู่ครับ"

    # อัปโหลดรูปทุกรูปและเก็บ attachment IDs
    print("[INFO] Uploading attachments...")
    attachment_list = []
    for img_path in image_paths:
        if img_path and os.path.isfile(img_path):
            try:
                file_result = uploadFile(img_path)
                if file_result and file_result.get('attachment'):
                    attachment_list.append(
                        {"id": file_result['attachment']['id']})
            except Exception as e:
                print(f"[WARN] upload failed for {img_path}: {e}")
    cr_test = predict_cr_classifier.classify(detail)
    
    payload = {
        "request": {
            "subject": f"{'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}",
            "description": f"ชื่อผู้แจ้ง  : {user}<br />เบอร์ติดต่อ : {phone}<br />สถานที่/บริษัท/สาขา พบปัญหา : {branch if branch is not None else txt.split('ส่วนที่หนึ่ง:')[1].split(',')[0]}<br />ปัญหาที่พบ/คำร้องขอ : {detail}<br />SN : N/A<br />Model : Not Specified",
            "requester": {
                "name": branch if branch is not None else txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0]
            },
            "template": {
                "id": "5101",
                "name": "New Aloha System for Minor (DQ-BT-BS-CF)",
                "is_service_template": 'false'
            },
            "site": {
                "id": "302",
                "name": "Dairy Queen - Standard A"  # ใส่แบบนี้ไปก่อนเพราะยังแยกไม่ได้
            },
            "item": {
                "id": "4501",
                "name": "EDC – Payment - ITMX"
            },
            "priority": {
                "id": "901",
                "name": "Severity 5"
            },
            "mode": {
                "id": "4",
                "name": "Chat"
            },
            "status": {
                "id": "2",
                "name": "Open",
                "color": "#0066ff"
            },
            "group": {
                "id": "463",
                "name": "Service Desk",
                "site": {
                        "id": 302
                }
            },
            "category": {
                "id": "603",
                "name": "SOFTWARE"
            },
            "subcategory": {
                "id": "3310",
                "name": "EDC Payment"
            },
            "technician": {
                "id": "5402",
                "email_id": "Helpdesk@p5-management.com",
                "name": "Service Desk",
                "phone": None,
                "mobile": None
            },
            "udf_fields": {
                "udf_sline_902": phone,
                "udf_sline_62": "สาขา",
                "udf_pick_1801": company,
                "udf_pick_8705": "EDC",
                "udf_pick_9601": "BBL",
                "udf_sline_611": "N/A",
                "udf_sline_1507": f"{'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}",
                "udf_mline_4203": f"ชื่อผู้แจ้ง  : {user}\nเบอร์ติดต่อ : {phone}\nสถานที่/บริษัท/สาขา พบปัญหา : {branch if branch is not None else txt.split('ส่วนที่หนึ่ง:')[1].split(',')[0]}\nปัญหาที่พบ/คำร้องขอ : {detail}\nSN : N/A\nModel : Not Specified",
                "udf_date_68": {
                    "display_value": "2025/11/28 07:35",
                    "value": "1764229800000"
                },
                "udf_pick_64": "กฤตภาส ศิริโสภณพิพัฒน์",
                "udf_pick_612": "NO",
                "udf_pick_4802": "P5",
                "udf_pick_9302": "Software"
            },
            "attachments": attachment_list
        }
    }

    # print("=" * 50)
    # print(f"[PAYLOAD] {json.dumps(payload, ensure_ascii=False)}")
    # print("=" * 50)

    print("[INFO] Sending ticket creation request...")
    # resp = fetch(payload)
    resp = {"ok": False}

    if resp.get("ok"):
        for img_path in image_paths:
            if img_path and os.path.isfile(img_path):
                try:
                    os.remove(img_path)
                except OSError as e:
                    print(f"[WARN] remove image failed: {e}")
        try:
            ticket_id = resp['data']['request']['id']
            res_txt = f"""Ticket {ticket_id} โดยมีรายละเอียดดังนี้\nชื่อสาขาหรือรหัสสาขา: {branch if branch is not None else txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0]}\nปัญหาที่พบ: {detail}\nชื่อ: {user}\nเบอร์โทรติดต่อ: {phone}"""
            _reply_cb(state.get("reply_token", ""), res_txt)
            _clear(user_id)
        except Exception as e:
            ticket_id = "-"
            _reply_cb(state.get("reply_token", ""),
                      "ตอนนี้ระบบมีปัญหาอยู่ รอสักครู่นะครับ")
            return f"[ERROR]: {e}"
    return "ตอนนี้ระบบบันทึกข้อมูลไม่ได้ กรุณารอสักครู่ครับ"


def _handle_edc_message(user_id: str, state: Dict, lower: str) -> Optional[str]:
    """รับมือข้อความกรณี classifier ทำนายว่าเป็น EDC.

    - อัปเดต step / history / context_confirm
    - เรียก AI ผ่าน send_message
    - ถ้าครบส่วนที่สองและสามแล้วจะเรียก _summary และคืนค่า None (เพราะสรุปเสร็จแล้ว)
    - ถ้ายังไม่ครบจะคืนข้อความให้เอาไป reply กลับ
    """

    # ตอนนี้รองรับเฉพาะกรณีเริ่ม flow ใหม่ (step == 0)
    if state.get("step") != 0:
        # อยู่ระหว่าง flow อื่นอยู่ ให้ไม่ทำอะไรเพิ่มเติม
        return None

    state["step"] = 1
    state["history"].append(lower)
    state["context_confirm"] = True
    _save_state(user_id, state)

    res = send_message(lower, state)
    print("=" * 50)
    print(f"[INFO] AI Response: {res}")
    print("=" * 50)

    # ถ้า AI ตอบมาครบทุกส่วนแล้วให้ไปสรุปเลย ไม่ต้องส่งข้อความกลับไปอีก
    if ("ส่วนที่สอง:" in res) and ("ส่วนที่สาม:" in res):
        print("[INFO] Proceeding to summary...")
        _summary(state, res)
        return None

    # ยังไม่ครบ ให้ส่งข้อความนี้กลับไปถามข้อมูลเพิ่ม แล้ว reset step
    state["step"] = 0
    _save_state(user_id, state)
    return 
    # return res


def process_step_message(user_id: str, text: str, reply_token: Optional[str] = None) -> str:
    print("START PROCESS STEP MESSAGE")
    state = _load_state(user_id)
    predic = predict_classifier.classify(text)
    print("=" * 50)
    print(f"[PREDICTION] {predic}")
    print("=" * 50)

    if not state:
        state = _start(user_id)
    if reply_token:
        state["reply_token"] = reply_token

    print(f"[state before] {state['step']}")
    msg = (text or "").strip()
    lower = msg.lower()

    # คำสั่งยกเลิก flow
    if lower == "ยกเลิก":
        _clear(user_id)
        return "ยกเลิกเซสชันแล้ว"

    prediction = predic.get("prediction")
    reply_text: Optional[str] = None

    if prediction == "edc":
        # กรณีเป็น EDC ให้ไปจัดการในฟังก์ชันเฉพาะ
        reply_text = _handle_edc_message(user_id, state, lower)
    elif prediction == "other":
        # ไม่ใช่ EDC ให้ตอบเป็นข้อความว่าง (หรือจะไม่ตอบเลยก็ได้)
        reply_text = ""

    # ส่งข้อความกลับ (ถ้ามี callback และกำหนด reply_text มา)
    if reply_token and _reply_cb and reply_text is not None:
        _reply_cb(reply_token, reply_text)

    return None


def process_image_message(user_id: str, image_path: str, reply_token: Optional[str] = None) -> Optional[str]:
    state = _load_state(user_id)
    predic_img = predict_image_edc.classify_image(image_path)
    print("=" * 50)
    print(f"[PREDICTION IMAGE] {predic_img}")
    print("=" * 50)
    if predic_img.get("prediction") == "not_edc":
        return None
    if not state:
        print(f"[WARN] image from user without session: {user_id}")
        state = _start(user_id)

    image_paths = state.get("image_paths", [])
    image_paths.append(image_path)
    state["image_paths"] = image_paths
    state["updated"] = time.time()
    state["img_confirm"] = True

    if reply_token:
        state["reply_token"] = reply_token

    # _save_state(user_id, state)
    # _schedule_auto_submit(user_id, delay_sec=5.0)
    return None


def find_branch(storeID: str):
    try:
        pattern = r"\d{6}|\d{5}|\d{4}"
        matched = re.search(pattern, storeID)
        print(f"[PATTERN]: {pattern}, Matched: {matched}")

        if matched:
            ID = matched.group(0)
            result = fetch_store(ID)
            return result[0]

    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR] find_branch error: {e}")
        print(" ⚠️ " * 20)
        return None


def parse_header(text: str):
    edc_freeze = text.split(",")[0]
    edc_slip = text.split(",")[2]
    if ("ไม่" in edc_freeze):
        edc_freeze = "ไม่ค้าง"
    elif ("ใช่" in edc_freeze):
        edc_freeze = "ค้าง"

    if ("ไม่" in edc_slip):
        edc_slip = "ไม่ออก"
    elif ("ใช่" in edc_slip):
        edc_slip = "ออก"
    return f"EDC {edc_freeze}, Slip EDC {edc_slip}"


__all__ = ["process_step_message",
           "process_image_message", "set_reply_callback"]
