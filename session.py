import redis
import json
import os
from typing import Dict, Any


class RedisSession:
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0, password: str | None = None, ttl_seconds: int = 600):
        """
        เชื่อมต่อกับ Redis server โดยอ่านค่าจาก Environment Variables ก่อน
        - REDIS_URL: redis://user:pass@host:port/db
        - หากไม่มี REDIS_URL จะใช้ REDIS_HOST/REDIS_PORT/REDIS_DB (fallback ด้วยพารามิเตอร์ที่ส่งเข้า)
        - SESSION_TTL: อายุ session เป็นวินาที (ค่าเริ่มต้น 600)
        """
        # TTL: env overrides parameter; falls back to provided default
        self.ttl = int(os.getenv('SESSION_TTL', str(ttl_seconds)))

        url = os.getenv('REDIS_URL')
<<<<<<< HEAD
        # url = "redis://host.docker.internal:6379/0"
        print(f"[Redis] Initializing RedisSession with TTL={self.ttl} seconds")
        print(f"[Redis] REDIS_URL: {url}")
=======
>>>>>>> 0e14b7f (ปรับให้บอทไม่ตอบถ้าไม่เกี่ยวข้อง)
        try:
            if url:
                print(f"[Redis] connecting via URL: {url}")
                self.redis_client = redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    health_check_interval=30,
                    retry_on_timeout=True,
                )
            else:
                # Fallback to individual components (env first, then params)
                env_host = os.getenv('REDIS_HOST', host)
                env_port = int(os.getenv('REDIS_PORT', str(port)))
                env_db = int(os.getenv('REDIS_DB', str(db)))
                env_password = os.getenv('REDIS_PASSWORD', password if password is not None else None)
                print(f"[Redis] connecting to {env_host}:{env_port}/{env_db}")
                self.redis_client = redis.Redis(
                    host=env_host,
                    port=env_port,
                    db=env_db,
                    password=env_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    health_check_interval=30,
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
        json_data = json.dumps(data, ensure_ascii=False)
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