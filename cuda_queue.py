"""
CUDA Queue Manager
จัดการคิวงานที่ต้องใช้ GPU เพื่อป้องกันการใช้ CUDA พร้อมกันมากเกินไป
"""
import threading
import queue
import time
from typing import Callable, Any, Dict


class CUDAQueueManager:
    def __init__(self, max_cuda_memory_percent: float = 80.0, check_interval: float = 0.5):
        """
        Args:
            max_cuda_memory_percent: เปอร์เซ็นต์สูงสุดของ CUDA memory ที่ยอมให้ใช้ (ไม่ได้ใช้แล้ว - ใช้ lock แทน)
            check_interval: ระยะเวลาที่รอระหว่างการเช็ค CUDA (วินาที)
        """
        self.task_queue = queue.Queue()
        self.max_cuda_memory_percent = max_cuda_memory_percent
        self.check_interval = check_interval
        self.worker_thread = None
        self.running = False
        self.cuda_available = False
        self.gpu_lock = threading.Lock()  # ใช้ Lock เพื่อให้ทำงานทีละงาน
        self.current_task_name = None
        
        # ตรวจสอบว่ามี CUDA หรือไม่
        try:
            import torch
            self.cuda_available = torch.cuda.is_available()
            if self.cuda_available:
                print(f"[CUDA Queue] GPU detected: {torch.cuda.get_device_name(0)}")
                total_memory = torch.cuda.get_device_properties(0).total_memory / 1024**2
                print(f"[CUDA Queue] Total GPU memory: {total_memory:.2f} MB")
        except ImportError:
            print("[CUDA Queue] PyTorch not available, CUDA queue disabled")
    
    def _check_cuda_available(self) -> bool:
        """ตรวจสอบว่า CUDA memory ว่างพอหรือไม่"""
        if not self.cuda_available:
            return True  # ถ้าไม่มี GPU ให้ผ่านเลย
        
        try:
            import torch
            allocated = torch.cuda.memory_allocated() / 1024**2  # MB
            total = torch.cuda.get_device_properties(0).total_memory / 1024**2  # MB
            usage_percent = (allocated / total) * 100
            
            is_available = usage_percent < self.max_cuda_memory_percent
            
            if not is_available:
                print(f"[CUDA Queue] GPU busy ({usage_percent:.1f}% used), waiting...")
            
            return is_available
        except Exception as e:
            print(f"[CUDA Queue] Error checking CUDA: {e}")
            return True  # ถ้า error ให้ผ่านเลย
    
    def _clear_cuda_cache(self):
        """ล้าง CUDA cache"""
        if self.cuda_available:
            try:
                import torch
                torch.cuda.empty_cache()
                print("[CUDA Queue] CUDA cache cleared")
            except Exception as e:
                print(f"[CUDA Queue] Error clearing cache: {e}")
    
    def _worker(self):
        """Worker thread ที่คอยประมวลผลงานจาก queue"""
        print("[CUDA Queue] Worker thread started")
        
        while self.running:
            try:
                # ดึงงานจาก queue (รอไม่เกิน 1 วินาที)
                try:
                    task_data = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                func = task_data['func']
                args = task_data['args']
                kwargs = task_data['kwargs']
                callback = task_data.get('callback')
                error_callback = task_data.get('error_callback')
                
                # ใช้ Lock เพื่อให้มั่นใจว่ามีงานเดียวเท่านั้นทำงานพร้อมกัน
                print(f"[CUDA Queue] Waiting for GPU lock: {func.__name__}")
                with self.gpu_lock:
                    self.current_task_name = func.__name__
                    print(f"[CUDA Queue] GPU lock acquired, processing: {func.__name__}")
                    
                    if not self.running:
                        break
                    
                    # ประมวลผลงาน
                    try:
                        result = func(*args, **kwargs)
                        
                        # เรียก callback ถ้ามี
                        if callback:
                            callback(result)
                        
                        print(f"[CUDA Queue] Task completed: {func.__name__}")
                        
                    except Exception as e:
                        print(f"[CUDA Queue] Error in task {func.__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                        if error_callback:
                            error_callback(e)
                    
                    finally:
                        # ล้าง cache หลังทำงานเสร็จ
                        self._clear_cuda_cache()
                        self.current_task_name = None
                        # รอสักครู่ให้ GPU ปล่อย memory จริงๆ
                        time.sleep(0.5)
                        self.task_queue.task_done()
                        print(f"[CUDA Queue] GPU lock released")
                
            except Exception as e:
                print(f"[CUDA Queue] Worker error: {e}")
                import traceback
                traceback.print_exc()
        
        print("[CUDA Queue] Worker thread stopped")
    
    def start(self):
        """เริ่ม worker thread"""
        if self.running:
            print("[CUDA Queue] Already running")
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print("[CUDA Queue] Started")
    
    def stop(self):
        """หยุด worker thread"""
        print("[CUDA Queue] Stopping...")
        self.running = False
        
        if self.worker_thread:
            self.worker_thread.join(timeout=5.0)
        
        print("[CUDA Queue] Stopped")
    
    def submit_task(self, func: Callable, *args, callback: Callable = None, 
                   error_callback: Callable = None, **kwargs) -> None:
        """
        ส่งงานเข้า queue
        
        Args:
            func: ฟังก์ชันที่ต้องการประมวลผล
            *args: arguments สำหรับฟังก์ชัน
            callback: ฟังก์ชันที่จะเรียกเมื่อทำงานเสร็จ (รับผลลัพธ์เป็น parameter)
            error_callback: ฟังก์ชันที่จะเรียกเมื่อเกิด error
            **kwargs: keyword arguments สำหรับฟังก์ชัน
        """
        task_data = {
            'func': func,
            'args': args,
            'kwargs': kwargs,
            'callback': callback,
            'error_callback': error_callback
        }
        
        self.task_queue.put(task_data)
        queue_size = self.task_queue.qsize()
        print(f"[CUDA Queue] Task submitted: {func.__name__} (queue size: {queue_size})")
    
    def get_queue_size(self) -> int:
        """ดูจำนวนงานที่รออยู่ใน queue"""
        return self.task_queue.qsize()
    
    def get_status(self) -> Dict[str, Any]:
        """ดูสถานะของ queue"""
        return {
            'running': self.running,
            'queue_size': self.task_queue.qsize(),
            'current_task': self.current_task_name,
            'gpu_locked': self.gpu_lock.locked()
        }


# Global instance
_cuda_queue_manager = None


def get_cuda_queue_manager() -> CUDAQueueManager:
    """Get global CUDA queue manager instance"""
    global _cuda_queue_manager
    if _cuda_queue_manager is None:
        _cuda_queue_manager = CUDAQueueManager(max_cuda_memory_percent=80.0)
        _cuda_queue_manager.start()
    return _cuda_queue_manager


def shutdown_cuda_queue():
    """Shutdown CUDA queue manager"""
    global _cuda_queue_manager
    if _cuda_queue_manager:
        _cuda_queue_manager.stop()
        _cuda_queue_manager = None
