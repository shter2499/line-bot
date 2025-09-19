import redis
import json
import os
from typing import Dict, Any

class RedisSession:
    def __init__(self, host='localhost', port=6379, db=0, password=None, ttl_seconds=600):
        """
        เชื่อมต่อกับ Redis server และตั้งค่าพื้นฐาน
        
        Args:
            host (str): Redis host.
            port (int): Redis port.
            db (int): Redis database number.
            password (str): Password สำหรับเชื่อมต่อ Redis.
            ttl_seconds (int): ระยะเวลาหมดอายุของ session เป็นวินาที (ค่าเริ่มต้น 10 นาที).
        """
        self.ttl = ttl_seconds
        try:
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=False # เก็บข้อมูลในรูปแบบ bytes
            )
            self.redis_client.ping()
            print("Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            raise ConnectionError(f"Could not connect to Redis: {e}")

    def save(self, session_id: str, data: Dict[str, Any]):
        """
        บันทึกข้อมูล session ลงใน Redis.
        
        Args:
            session_id (str): ID ของ session ที่ใช้เป็น key.
            data (Dict): ข้อมูลที่จะบันทึก.
        """
        key = f"session:{session_id}"
        json_data = json.dumps(data)
        self.redis_client.set(key, json_data, ex=self.ttl)
    
    def get(self, session_id: str) -> Dict[str, Any] | None:
        """
        ดึงข้อมูล session จาก Redis.
        
        Args:
            session_id (str): ID ของ session ที่ต้องการ.
        
        Returns:
            Dict: ข้อมูล session หรือ None ถ้าไม่พบ.
        """
        key = f"session:{session_id}"
        data = self.redis_client.get(key)
        if data:
            return json.loads(data)
        return None

    def delete(self, session_id: str):
        """
        ลบ session ออกจาก Redis.
        
        Args:
            session_id (str): ID ของ session ที่ต้องการลบ.
        """
        key = f"session:{session_id}"
        self.redis_client.delete(key)