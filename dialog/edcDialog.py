"""
ข้อจำกัดปัจจุบัน:
        - State หายเมื่อโปรเซสรีสตาร์ต
        - ไม่มี lock ป้องกัน race (Flask single-thread ปกติพอ แต่ production ที่มี multi-thread ควรเพิ่ม threading.Lock)
"""
from __future__ import annotations
from fetchData.fetch import fetch, uploadFile
from dialog.aiDialog import send_message

import os
import time
import threading
from typing import Dict, List, Optional, Callable

QUESTIONS: List[str] = [
    "เพื่อเป็นการแก้ปัญหาให้ตรงจุดรบกวนลูกค้าตอบคำถามเบื้องต้นทั้งหมดสามข้อค่ะ \"เครื่อง EDC ค้างหรือไม่คะ\" ตอบเป็นตัวเลขนะคะ\n1. ค้าง\n2. ไม่ค้าง",
    "ลูกค้าได้ทำการ Restart เครื่อง EDC หรือไม่คะ ตอบเป็นตัวเลขนะคะ\n1. ใช่\n2. ไม่",
    "สลิปที่เครื่อง EDC ออกหรือไม่คะ ตอบเป็นตัวเลขนะคะ\n1. ออก\n2. ไม่ออก",
    "รบกวนลูกค้าพิมพ์รายละเอียดเพื่อบันทึกข้อมูลลงระบบค่ะ\nชื่อสาขาหรือรหัสสาขา:\nชื่อผู้แจ้ง:\nเบอร์โทรผู้แจ้ง:\nรายละเอียดปัญหา:",
    "รบกวนขอรูปภาพสลิปที่มีปัญหาด้วยค่ะ",
]

SESSION_TIMEOUT_SEC = 600
_user_states: Dict[str, Dict] = {}
_reply_cb: Optional[Callable[[str, str], None]] = None

def set_reply_callback(cb: Callable[[str, str], None]) -> None:
    """Register a callback used to reply later using a stored reply_token.

    cb will be called as cb(reply_token, text).
    """
    global _reply_cb
    _reply_cb = cb


def _expire():
    """ลบเซสชันที่ idle เกิน SESSION_TIMEOUT_SEC เพื่อลด memory leak.

    ทำงานแบบ 'lazy cleanup' คือเรียกเฉพาะตอนมีข้อความใหม่เข้ามา
    หากระบบ scale มากและต้องการความเที่ยงตรงอาจใช้ background job แทน.
    """
    now = time.time()
    expired = [uid for uid, st in _user_states.items(
    ) if now - st["updated"] > SESSION_TIMEOUT_SEC]
    for uid in expired:
        _user_states.pop(uid, None)


def _start(uid: str):
    st = {
        "step": 0,
        "answers": [],
        "updated": time.time(),
        "uid": uid,
        "image_paths": [],
        "await_confirm": False,
    }
    _user_states[uid] = st
    return st


def _clear(uid: str):
    """ลบ state ของผู้ใช้ (ใช้เมื่อยกเลิก หรือจบครบทุกข้อ)."""
    st = _user_states.pop(uid, None)
    # ยกเลิก timer ถ้ามีเพื่อกันงานค้าง
    try:
        t = st.get("_timer") if st else None
        if t:
            t.cancel()
    except Exception:
        pass


# ========== Auto-submit scheduling (5s debounce) ==========
def _auto_submit_job(user_id: str):
    state = _user_states.get(user_id)
    # print(f"[Auto_submit job state] {state}")
    if not state:
        return
    try:
        if not state.get("answers"):
            print("="*50)
            print("[WARN] auto_submit but no answers")
            print("="*50)
            token = state.get("reply_token")
            warn_msg = "** รบกวนขอข้อมูลตามนี้หน่อยครับ **\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:"
            if token and _reply_cb:
                try:
                    _reply_cb(token, warn_msg)
                except Exception as e:
                    print(f"[ERROR] auto_submit reply failed: {e}")
            return
            
        result = _summary(state)
        # พยายาม reply ด้วย reply_token ที่เก็บไว้ เพื่อลดการใช้ push
        token = state.get("reply_token")
        if result and token and _reply_cb:
            try:
                _reply_cb(token, result)
            except Exception as e:
                print(f"[ERROR] delayed reply failed: {e}")
    finally:
        _clear(user_id)


def _schedule_auto_submit(user_id: str, delay_sec: float = 5.0):
    state = _user_states.get(user_id)
    # print(f"[Auto_submit state] {state}")
    if not state:
        return
    old = state.get("_timer")
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t = threading.Timer(delay_sec, _auto_submit_job, args=(user_id,))
    t.daemon = True
    state["_timer"] = t
    t.start()


def _summary(state: Dict) -> str:
    answers = list(state["answers"])
    image_paths = state.get('image_paths', [])
    print("=" * 50)
    print(f"[ANSWERS] {answers}")
    print(f"[IMG] {image_paths}")
    print("=" * 50)
    try:
        detail = answers[0].split('ปัญหาที่พบ:')[1].split('\n')[0]
        req_name = answers[0].split('รหัสสาขาและชื่อสาขา:')[1].split('\n')[0]
        phone = answers[0].split('เบอร์ติดต่อ:')[1].split('\n')[0]
        user = answers[0].split('ชื่อ:')[1].split('\n')[0]
    except Exception as e:
        print("*" * 50)
        print(f"[ERROR] parsing answers failed: {e}")
        print("*" * 50)
        return "ระบบมีปัญหา กรุณารอสักครู่ครับ"

    # อัปโหลดรูปทุกรูปและเก็บ attachment IDs
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
    payload = {
        "request": {
            # "subject": f"{detail} ({"EDC ค้าง" if answers[0] == "1" else "EDC ไม่ค้าง"}, {"Restart เครื่องแล้ว" if answers[1] == "1" else "ยังไม่ได้ Restart เครื่อง"}, {"สลิปออก" if answers[2] == "1" else "สลิปไม่ออก"})",
            "subject": detail,
            # "description": answers[3].replace('\n', '<br />') + answers[2],
            "description": f"ชื่อสาขาหรือรหัสสาขา: {req_name}<br />ชื่อผู้แจ้ง: {user}<br />เบอร์โทรผู้แจ้ง: {phone}<br />รายละเอียดปัญหา: {detail}",
            "requester": {
                "name": req_name
            },
            "template": {
                "name": "New Aloha System for Minor (DQ-BT-BS-CF) TEST",
                "id": "1501"
            },
            "site": {
                "name": "Dairy Queen - Standard A",
                "id": "602"
            },
            "udf_fields": {
                "udf_sline_2107": "0812345678",
                "udf_sline_2105": "watcharit",
                "udf_pick_2101": {
                    "name": "Dairy Queen",
                    "id": "1815"
                },
                "udf_pick_2113": {
                    "name": "test",
                    "id": "2023"
                },
                "udf_pick_2102": {
                    "name": "E-wallet ตัดเงินลูกค้าแล้วแต่ปิดบิลไม่ได้ (กรณีนี้ที่ตัดเงินลูกค้าแล้ว และ Error Timeout )",
                    "id": "1863"
                },
                "udf_pick_2114": {
                    "name": "test sub category",
                    "id": "2024"
                },
                "udf_pick_2103": {
                    "name": "LINE",
                    "id": "1878"
                },
                "udf_pick_2115": {
                    "name": "Service Desk",
                    "id": "2082"
                },
                "udf_pick_2116": {
                    "name": "test Items",
                    "id": "2032"
                },
                "udf_pick_2117": {
                    "name": "Watcharit Chomklin",
                    "id": "2033"
                }
            },
            "attachments": attachment_list
        }
    }
    # print('=' * 90)
    # print(f"[attachments] {attachment_list}")
    # print('=' * 90)

    resp = fetch(payload)
    if resp.get("ok"):
        # ลบรูปเมื่อสร้าง ticket สำเร็จเท่านั้น (กันเคสต้อง retry)
        for img_path in image_paths:
            if img_path and os.path.isfile(img_path):
                try:
                    os.remove(img_path)
                except OSError as e:
                    print(f"[WARN] remove image failed: {e}")
        try:
            ticket_id = resp['data']['request']['id']
        except Exception:
            ticket_id = "-"
        return (
            f"Ticket {ticket_id} ทีมงานจะตรวจสอบและรีบติดต่อกลับโดยเร็วนะคะ โดยมีรายละเอียดดังนี้\n"
            f"{answers[0].split('กรุณา')[0]}\n"
        )
    return "ไม่สามารถบันทึกข้อมูลในระบบได้ โปรดติดต่อเจ้าหน้าที่โดยตรงหรือลองใหม่อีกครั้งค่ะ"


def process_step_message(user_id: str, text: str) -> str:
    # เคลียร์เซสชันที่หมดอายุ และสร้างใหม่ถ้ายังไม่มี
    print("[PROCESS STEP MESSAGE user_id] ", user_id)
    _expire()
    state = _user_states.get(user_id)
    if not state:
        state = _start(user_id)

        
    msg = (text or "").strip()
    lower = msg.lower()
    # print("=" * 50)
    # print(f"[TEXT] {lower}")
    # print(f"[RES] {res}")
    # print("=" * 50)
    if lower == "ยกเลิก":
        _clear(user_id)
        return "ยกเลิกเซสชันแล้ว"

    if lower == "ยืนยัน":
        result = _summary(state)
        _clear(user_id)
        return result

    print(f"[STATE BEFORE AI MESSAGE] {state}")
    res = send_message(lower)
    print(f"[LEN img_paths] {len(state.get('image_paths'))}")

    if len(state.get("image_paths")) > 0:
        state["answers"].append(res)
        result = _summary(state)
        _clear(user_id)
        return result

    if "ขอรูปภาพ" in res and len(state.get("image_paths")) == 0:
        state["answers"].append(res)
        return "รบกวนขอรูปภาพด้วยครับ"

    print(f"[SETP MESSAGE STATE] {state}")
    return res


# def process_step_message(user_id: str, text: str) -> str:
#     msg = (text or "").strip()
#     lower = msg.lower()
#     _expire()
#     state = _user_states.get(user_id)

#     # ============ เริ่มใหม่ ============
#     if lower in ("แจ้งปัญหา"):
#         _start(user_id)
#         return QUESTIONS[0]

#     # ============ ยกเลิกเซสชัน ============
#     if lower in ("ยกเลิก", "cancel", "หยุด"):
#         if state:
#             _clear(user_id)
#             return "ยกเลิกเซสชันแล้ว"
#         return "ยังไม่มีเซสชัน"

#     # ============ ขอทราบสถานะปัจจุบัน ============
#     if lower in ("สถานะ", "status"):
#         if state:
#             return f"อยู่ที่ข้อ {state['step']+1}/{len(QUESTIONS)}"
#         return "ยังไม่ได้เริ่ม พิมพ์ 'เริ่ม' เพื่อเริ่ม"

#     # ============ ผู้ใช้ยังไม่เริ่ม แต่ส่งข้อความอื่นมา ============
#     if not state:
#         return "หากลูกค้าต้องการแจ้งปัญหาเกี่ยวกับเครื่อง EDC รบกวนลูกค้าพิมพ์ \"แจ้งปัญหา\" หรือพิมพ์ \"ยกเลิก\" หากใส่ข้อมูลผิดพลาดค่ะ"

#     # ============ กำลังอยู่ในเซสชัน ============
#     step = state["step"]
#     if state.get("await_confirm"):
#         if lower == "ยืนยัน":
#             result = _summary(state)
#             _clear(user_id)
#             return result
#         return "กรุณาพิมพ์ 'ยืนยัน' เพื่อส่งข้อมูล หรือพิมพ์ 'ยกเลิก' เพื่อยกเลิกค่ะ"

#     if step >= len(QUESTIONS):
#         return "หากระบบตอบกลับไม่ตอบสนองหรือการตอบกลับมีปัญหา ให้ลูกค้าพิมพ์ \"ยกเลิก\" และตอบคำถามใหม่อีกครั้งค่ะ"

#     # ============ เก็บคำตอบของข้อปัจจุบัน ============
#     if step < 3:
#         if msg not in ("1", "2"):
#             return (
#                 "กรุณาตอบเป็นหมายเลข 1 หรือ 2 เท่านั้นค่ะ\n\n"
#                 f"{QUESTIONS[step]}"
#             )
#     elif step == 3:  # รายละเอียดข้อความยาว
#         if not msg.strip():
#             return f"รบกวนพิมพ์ข้อความตอบกลับด้วยค่ะ\n\n{QUESTIONS[step]}"
#     elif step == 4:  # ต้องเป็นรูปภาพ ไม่รับข้อความ
#         return "รบกวนส่งเป็นรูปภาพสลิป 1 รูปค่ะ หากต้องการยกเลิกพิมพ์ 'ยกเลิก'"

#     if step != 4: 
#         state["answers"].append(msg)
#         state["step"] += 1
#         state["updated"] = time.time()
#         state["uid"] = user_id

#     if state["step"] < len(QUESTIONS):
#         # ถัดไปคือคำถามรูปภาพ (step == 4)
#         if state["step"] == 4:
#             return QUESTIONS[4]
#         return QUESTIONS[state['step']]


def process_image_message(user_id: str, image_path: str, reply_token: Optional[str] = None) -> Optional[str]:
    state = _user_states.get(user_id)
    if not state:
        # สร้างเซสชันใหม่อัตโนมัติถ้ายังไม่มี
        print(f"[WARN] image from user without session: {user_id}")
        state = _start(user_id)
        
    print("=" * 50)
    print(f"[IMAGE MESSAGE STATE] {state}")
    print("=" * 50)
    image_paths = state.get("image_paths", [])

    image_paths.append(image_path)
    state["image_paths"] = image_paths
    state["updated"] = time.time()
    # เก็บ reply_token ล่าสุดไว้เพื่อตอบกลับหลังครบดีเลย์ (ไม่ใช้ push)
    if reply_token:
        state["reply_token"] = reply_token
    _schedule_auto_submit(user_id, delay_sec=5.0)
    return None

__all__ = ["process_step_message", "process_image_message", "QUESTIONS", "set_reply_callback"]
