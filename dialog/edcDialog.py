"""
State management now uses Redis via session.RedisSession instead of in-memory dict.
- Session TTL is enforced by Redis; no manual _expire needed.
- Timers are managed in-process per instance (stored outside Redis) as they are not JSON-serializable.
"""
from __future__ import annotations
from fetchData.fetch import fetch, uploadFile
from dialog.aiDialog import send_message
from session import RedisSession

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
_reply_cb: Optional[Callable[[str, str], None]] = None

_redis: Optional[RedisSession] = None


def _get_redis() -> RedisSession:
    global _redis
    if _redis is None:
        host = "localhost"
        port = 6379
        db = 0
        password = None
        ttl = SESSION_TIMEOUT_SEC
        _redis = RedisSession(host=host, port=port, db=db,
                              password=password, ttl_seconds=ttl)
    return _redis


_timers: Dict[str, threading.Timer] = {}


def _default_state(uid: str) -> Dict:
    return {
        "step": 0,
        "answers": [],
        "edc_answers": [],
        "updated": time.time(),
        "uid": uid,
        "image_paths": [],
        "history": [],
        "answers_confirm": False,
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


# ========== Auto-submit scheduling (5s debounce) ==========
#แก้จาก auto summit เป็น auto reply แทนเพราะเผื่อเคสที่ลูกค้าส่งรูปมาก่อนเป็นอันดับแรก
def _auto_submit_job(user_id: str):
    state = _load_state(user_id)
    clear_session = False
    if not state:
        return
    try:
        if not state.get("answers"):
            token = state.get("reply_token")
            state["img_confirm"] = True
            if token and _reply_cb:
                try:
                    _save_state(user_id, state)
                    _reply_cb(token, "** รบกวนขอข้อมูลตามนี้หน่อยครับ **\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
                except Exception as e:
                    print(f"[ERROR] auto_submit reply failed: {e}")
            return
        
        if not state.get("edc_confirm"):
            token = state.get("reply_token")
            # state["edc_confirm"] = True
            if token and _reply_cb:
                try:
                    _save_state(user_id, state)
                    _reply_cb(token, "1.EDC ค้างไหมครับ\nAns\n2.มีการ Restart EDC ไหมครับ\nAns\n3.สลิปที่เครื่อง EDC ออกไหมครับ\nAns")
                except Exception as e:
                    print(f"[ERROR] auto_submit reply failed: {e}")
            return
        
        result = _summary(state)
        token = state.get("reply_token")
        if result and token and _reply_cb:
            try:
                _reply_cb(token, result)
                clear_session = True
            except Exception as e:
                print(f"[ERROR] delayed reply failed: {e}")
    finally:
        if clear_session:
            _clear(user_id)


def _auto_reply(user_id: str):
    state = _load_state(user_id)
    clear_session = False
    if not state:
        return
    try:
        res = send_message("", state)
        return res
    finally:
        if clear_session:
            _clear(user_id)



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


def _summary(state: Dict) -> str:
    answers = list(state["answers"])
    image_paths = state.get('image_paths', [])
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
            "subject": detail,
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

    resp = fetch(payload)
    if resp.get("ok"):
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
            f"{answers[0].split('รบกวนขอรูป')[0]}\n"
        )
    return "ตอนนี้ระบบบันทึกข้อมูลไม่ได้ กรุณารอสักครู่ครับ"


def process_step_message(user_id: str, text: str, reply_token: Optional[str] = None) -> str:
    state = _load_state(user_id)
    # จัดประเภทผลลัพธ์จาก AI

    if not state:
        state = _start(user_id)
    if reply_token:
        state["reply_token"] = reply_token
        # _save_state(user_id, state)

    msg = (text or "").strip()
    lower = msg.lower()
    state["history"].append(lower)
    need_image = state.get("img_confirm")
    need_edc   = state.get("edc_confirm")
    need_answers = state.get("answers_confirm")

    if lower == "ยกเลิก":
        _clear(user_id)
        return "ยกเลิกเซสชันแล้ว"
    
    _save_state(user_id, state)

    res = send_message(lower, state)
    #========================================= ยังใช้งานอยู่อย่าพึ่งลบ =============================================================================
    # updated = False
    
    # if not need_image:
    #     # # ข้อความนี้ถือว่าเกี่ยวกับรายละเอียด + ขอรูป (ถือเป็นการได้ detail ชุดหนึ่ง)
    #     if res not in state["answers"]:
    #         state["answers"].append(res)
    #     state["answers_confirm"] = True
    #     updated = True
    #     # ถ้ายังไม่มีรูป ให้แจ้งขอรูป (ถ้ามีรูปแล้วก็ไม่ต้อง return ตัด flow)
    #     if not state.get("img_confirm"):
    #         _save_state(user_id, state)
    #         return "รบกวนขอรูปภาพด้วยครับ" if not need_edc else "ต้องการข้อมูล EDC"

    # elif not need_edc:
    #     if res not in state.get("edc_answers", []):
    #         state.setdefault("edc_answers", []).append(res)
    #     state["edc_confirm"] = True
    #     updated = True
    #     # return "ต้องการข้อมูล EDC"

    # else:
    #     # ถือว่าเป็นรายละเอียดทั่วไป (อาจมาหลังรูปหรือหลัง edc ก็ได้)
    #     if res not in state["answers"]:
    #         state["answers"].append(res)
    #         state["answers_confirm"] = True
    #         updated = True
    #     # res = send_message(lower, state)
    #     # print("=" * 50)
    #     # print(f"[ELSE AI] {res}")
    #     # print("=" * 50)

    # if updated:

    # # สรุปหากครบทั้ง 3 ส่วน ไม่สนลำดับการมาถึง
    # # print("=" * 50)
    # # print(f"[ans con] {state.get('answers_confirm')}, edc: {state.get('edc_confirm')}, img: {state.get('img_confirm')}")
    # # print("=" * 50)
    # if state.get("answers_confirm") and state.get("edc_confirm") and state.get("img_confirm"):
    #     result = _summary(state)
    #     _clear(user_id)
    #     return result
    #========================================= ยังใช้งานอยู่อย่าพึ่งลบ =============================================================================
    return res


def process_image_message(user_id: str, image_path: str, reply_token: Optional[str] = None) -> Optional[str]:
    state = _load_state(user_id)
    # print("=" * 50)
    # print(f"[STATE] {state}")
    # print("=" * 50)
    if not state:
        print(f"[WARN] image from user without session: {user_id}")
        state = _start(user_id)

    image_paths = state.get("image_paths", [])
    image_paths.append(image_path)
    state["image_paths"] = image_paths
    state["updated"] = time.time()
    state["img_confirm"] = True
    state["history"].append("[Image]")

    if reply_token:
        state["reply_token"] = reply_token

    _save_state(user_id, state)
    _schedule_auto_submit(user_id, delay_sec=5.0)
    return None


__all__ = ["process_step_message", "process_image_message",
           "QUESTIONS", "set_reply_callback"]
